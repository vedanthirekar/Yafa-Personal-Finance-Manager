"""Forecasting service.

Runs on synthetic frames, so no database is needed. The cases that matter are
the degenerate ones -- the previous implementation collapsed all of them into
a single silent `None`.
"""

from datetime import date
from decimal import Decimal

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
    def test_empty_input_reports_not_enough_history(self) -> None:
        result = forecasting.forecast_series(pd.DataFrame(columns=["date", "amount", "category"]))
        assert result.forecast == []
        assert result.is_fitted is False
        assert result.model == "not-enough-history"

    def test_short_history_produces_no_forecast_at_all(self) -> None:
        """Three months is not a forecast, and the old flat mean baseline
        dressed up as one. The caller gets nothing plus a countdown."""
        result = forecasting.forecast_series(frame(3), steps=6)
        assert result.forecast == []
        assert result.is_fitted is False
        assert result.model == "not-enough-history"
        assert result.months_of_history == 3
        assert result.months_required == forecasting.MIN_MONTHS_TO_FORECAST

    def test_long_history_fits_smoothing(self) -> None:
        result = forecasting.forecast_series(frame(24), steps=6)
        assert result.is_fitted is True
        assert result.model == "exponential smoothing"
        assert len(result.forecast) == 6
        assert result.smoothing_level is not None
        assert 0.0 <= result.smoothing_level <= 1.0

    def test_forecast_is_flat(self) -> None:
        """Exponential smoothing projects a level, not a trajectory. Every
        horizon gets the same point estimate -- only the interval moves."""
        result = forecasting.forecast_series(frame(24), steps=6)
        amounts = {p.amount for p in result.forecast}
        assert len(amounts) == 1

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
        """The lower bound of the interval runs below zero on a declining
        series. Spend can't be negative, so it's clamped."""
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
        """A month with no spending must still exist in the series, or the
        model treats two non-adjacent months as consecutive."""
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


@pytest.mark.parametrize("months", [0, 1, 3, 5])
def test_no_forecast_below_minimum(months: int) -> None:
    result = forecasting.forecast_series(
        frame(months) if months else pd.DataFrame(columns=["date", "amount", "category"])
    )
    assert result.forecast == []
    assert result.is_fitted is False


def test_forecast_appears_exactly_at_the_minimum() -> None:
    """The gate is a promise to the user -- "projections start at six months" --
    so the boundary is pinned rather than left to drift with the model."""
    assert forecasting.forecast_series(frame(5)).is_fitted is False
    assert forecasting.forecast_series(frame(6)).is_fitted is True


class TestPartialMonth:
    """The newest bucket is only as complete as today's date.

    Smoothing weights the most recent observation most heavily, so fitting on a
    half-finished month reads as a sudden collapse in spending and is exactly
    the point the model trusts most.
    """

    def test_current_month_is_dropped_from_the_fit(self) -> None:
        monthly = pd.Series(
            [100.0, 100.0, 100.0],
            index=pd.to_datetime(["2026-06-30", "2026-07-31", "2026-08-31"]),
        )
        trimmed = forecasting._drop_partial_month(monthly, today=date(2026, 8, 15))
        assert len(trimmed) == 2
        assert trimmed.index[-1].month == 7

    def test_a_finished_month_is_kept(self) -> None:
        """Someone who stopped logging in June still has a complete June."""
        monthly = pd.Series(
            [100.0, 100.0],
            index=pd.to_datetime(["2026-05-31", "2026-06-30"]),
        )
        trimmed = forecasting._drop_partial_month(monthly, today=date(2026, 8, 15))
        assert len(trimmed) == 2

    def test_partial_month_stays_in_history(self) -> None:
        """Excluded from the fit, still drawn on the chart.

        Anchored to the real current month, since `forecast_series` reads the
        clock -- a fixed date here would stop exercising the trim the moment
        it fell into the past.
        """
        today = date.today()
        this_month = pd.Timestamp(year=today.year, month=today.month, day=1)
        rows = [
            {
                "date": this_month - pd.DateOffset(months=i),
                "amount": 500.0,
                "category": "Food",
            }
            for i in range(12)
        ]

        result = forecasting.forecast_series(pd.DataFrame(rows))
        assert len(result.history) == 12  # every month charted
        assert result.months_of_history == 11  # the current one is not fitted

    def test_forecast_starts_after_the_last_charted_month(self) -> None:
        """No month may appear as both an observation and a projection.

        The partial month is dropped from the fit but has still happened, so
        anchoring the horizon to the fitted series would emit a forecast for a
        month already in `history` -- the chart would draw it twice, with two
        different numbers.
        """
        today = date.today()
        this_month = pd.Timestamp(year=today.year, month=today.month, day=1)
        rows = [
            {
                "date": this_month - pd.DateOffset(months=i),
                "amount": 500.0,
                "category": "Food",
            }
            for i in range(12)
        ]

        result = forecasting.forecast_series(pd.DataFrame(rows), steps=3)
        charted = {p.date for p in result.history}
        assert all(p.date not in charted for p in result.forecast)
        assert result.forecast[0].date > result.history[-1].date


class TestDormancy:
    """A long stretch of empty months is an absence, not a spending pattern.

    `_to_monthly` zero-fills gaps, which is right for a quiet month inside an
    active stretch and wrong for a year off -- the model would learn that spend
    collapsed to nothing, which drags the level down and inflates the interval.
    """

    @staticmethod
    def _abandoned_then_resumed() -> pd.DataFrame:
        rows = []
        # A year at 5000/month...
        for i in range(12):
            rows.append(
                {
                    "date": pd.Timestamp("2023-01-31") + pd.DateOffset(months=i),
                    "amount": 5000.0,
                    "category": "Food",
                }
            )
        # ...then eight months of nothing at all...
        # ...then eight months back, at a much lower level.
        for i in range(8):
            rows.append(
                {
                    "date": pd.Timestamp("2024-09-30") + pd.DateOffset(months=i),
                    "amount": 500.0,
                    "category": "Food",
                }
            )
        return pd.DataFrame(rows)

    def test_only_the_recent_era_is_fitted(self) -> None:
        result = forecasting.forecast_series(self._abandoned_then_resumed())
        assert result.is_fitted is True
        assert result.months_of_history == 8

    def test_forecast_reflects_the_new_level(self) -> None:
        """Not an average of 5000 and 500, and not dragged toward zero by the
        gap. The account spends 500 a month now."""
        result = forecasting.forecast_series(self._abandoned_then_resumed())
        assert result.forecast[0].amount == pytest.approx(Decimal("500"), abs=Decimal("50"))

    def test_full_history_is_still_charted(self) -> None:
        """Dropped from the fit, not from the record."""
        result = forecasting.forecast_series(self._abandoned_then_resumed())
        assert len(result.history) == 28  # 12 active + 8 empty + 8 active

    def test_a_short_gap_is_not_dormancy(self) -> None:
        """Two quiet months inside an active stretch are real zeros and stay."""
        rows = [
            {
                "date": pd.Timestamp("2025-01-31") + pd.DateOffset(months=i),
                "amount": 500.0,
                "category": "Food",
            }
            for i in range(12)
            if i not in (5, 6)
        ]
        result = forecasting.forecast_series(pd.DataFrame(rows))
        assert result.months_of_history == 12
