"""Forecasting service.

Runs on synthetic frames, so no database is needed. The cases that matter are
the degenerate ones -- the previous implementation collapsed all of them into
a single silent `None`.
"""

from datetime import date

import pandas as pd
import pytest

from app.services import forecasting


def frame(months: int, amount: float = 1000.0, category: str = "Food") -> pd.DataFrame:
    """`months` consecutive month-ends, one transaction each."""
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2025-01-31") + pd.DateOffset(months=i),
                "amount": amount,
                "category": category,
            }
            for i in range(months)
        ]
    )


class TestForecastSeries:
    def test_empty_input_reports_insufficient_history(self) -> None:
        result = forecasting.forecast_series(pd.DataFrame(columns=["date", "amount", "category"]))
        assert result.forecast == []
        assert result.is_fitted is False
        assert result.model == "insufficient-history"

    def test_short_history_falls_back_to_baseline(self) -> None:
        """Three months can't support ARIMA(5,1,0). The caller gets a labelled
        baseline rather than nothing, and is_fitted says which it is."""
        result = forecasting.forecast_series(frame(3), steps=6)
        assert len(result.forecast) == 6
        assert result.is_fitted is False
        assert result.model == "mean-baseline"

    def test_long_history_fits_arima(self) -> None:
        result = forecasting.forecast_series(frame(24), steps=6)
        assert result.is_fitted is True
        assert result.model.startswith("ARIMA")
        assert len(result.forecast) == 6

    def test_forecast_has_prediction_intervals(self) -> None:
        result = forecasting.forecast_series(frame(24), steps=3)
        for point in result.forecast:
            assert point.lower is not None
            assert point.upper is not None
            assert point.lower <= point.amount <= point.upper

    def test_history_points_have_no_interval(self) -> None:
        """History is observed, not estimated -- a band around it would be a
        lie."""
        result = forecasting.forecast_series(frame(24))
        assert all(p.lower is None and p.upper is None for p in result.history)

    def test_forecast_never_negative(self) -> None:
        """ARIMA on a declining short series will happily project below zero.
        Spend can't be negative, so it's clamped."""
        declining = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2025-01-31") + pd.DateOffset(months=i),
                    "amount": max(2000.0 - i * 180, 10.0),
                    "category": "Food",
                }
                for i in range(24)
            ]
        )
        result = forecasting.forecast_series(declining, steps=12)
        assert all(p.amount >= 0 for p in result.forecast)
        assert all(p.lower is None or p.lower >= 0 for p in result.forecast)

    def test_missing_months_are_zero_filled(self) -> None:
        """A month with no spending must still exist in the series, or ARIMA
        treats two non-adjacent months as consecutive."""
        sparse = pd.DataFrame(
            [
                {"date": pd.Timestamp("2025-01-31"), "amount": 100.0, "category": "Food"},
                # February skipped entirely
                {"date": pd.Timestamp("2025-03-31"), "amount": 100.0, "category": "Food"},
            ]
        )
        result = forecasting.forecast_series(sparse)
        assert len(result.history) == 3
        assert result.history[1].amount == 0


class TestAnomalies:
    def test_flags_a_genuine_spike(self) -> None:
        rows = [
            {
                "date": pd.Timestamp("2025-01-31") + pd.DateOffset(months=i),
                "amount": 100.0,
                "category": "Food",
            }
            for i in range(12)
        ]
        rows.append({"date": pd.Timestamp("2026-01-31"), "amount": 5000.0, "category": "Food"})

        anomalies = forecasting.detect_anomalies(pd.DataFrame(rows))
        assert len(anomalies) == 1
        assert anomalies[0].category == "Food"
        assert anomalies[0].z_score >= 2.0

    def test_steady_spending_is_not_anomalous(self) -> None:
        assert forecasting.detect_anomalies(frame(12)) == []

    def test_thresholds_are_per_category(self) -> None:
        """A $400 rent month is normal; a $400 coffee month is not. A global
        threshold cannot tell those apart."""
        rows = []
        for i in range(12):
            when = pd.Timestamp("2025-01-31") + pd.DateOffset(months=i)
            rows.append({"date": when, "amount": 2000.0, "category": "Household"})
            rows.append({"date": when, "amount": 20.0, "category": "Food"})
        # A 400 coffee month: huge for Food, unremarkable next to Household.
        rows.append({"date": pd.Timestamp("2026-01-31"), "amount": 400.0, "category": "Food"})

        anomalies = forecasting.detect_anomalies(pd.DataFrame(rows))
        assert [a.category for a in anomalies] == ["Food"]

    def test_too_few_points_yields_nothing(self) -> None:
        """Two observations produce a meaningless standard deviation."""
        assert forecasting.detect_anomalies(frame(2)) == []

    def test_empty_frame(self) -> None:
        assert (
            forecasting.detect_anomalies(pd.DataFrame(columns=["date", "amount", "category"])) == []
        )


class TestTopCategories:
    def test_ranks_by_spend(self) -> None:
        df = pd.concat(
            [
                frame(6, amount=100.0, category="Food"),
                frame(6, amount=500.0, category="Household"),
                frame(6, amount=50.0, category="Health"),
            ]
        )
        assert forecasting.top_categories(df, limit=2) == ["Household", "Food"]

    def test_empty(self) -> None:
        assert forecasting.top_categories(pd.DataFrame(columns=["category", "amount"])) == []


def test_month_start() -> None:
    assert forecasting.month_start(date(2026, 8, 13)) == date(2026, 8, 1)


@pytest.mark.parametrize("months", [0, 1])
def test_no_forecast_below_minimum(months: int) -> None:
    result = forecasting.forecast_series(
        frame(months) if months else pd.DataFrame(columns=["date", "amount", "category"])
    )
    assert result.forecast == []
