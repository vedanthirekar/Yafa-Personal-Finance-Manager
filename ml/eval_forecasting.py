"""Rolling-origin backtest of the spend forecaster against simple baselines.

    uv run python -m ml.eval_forecasting

Answers the question a model name can't: *is this forecast any better than
doing nothing?* Every candidate makes one-step-ahead predictions from an
expanding window, and the mean absolute error is reported against a naive
"next month looks like last month" baseline.

Reads real monthly series straight from Postgres, so the numbers describe the
data the app actually has rather than a synthetic benchmark. Writes
``data/forecast_eval.json``.

Nothing here is wired into the API -- it is a measurement tool. See
``docs/forecasting-notes.md`` for what the current numbers say.
"""

import json
import warnings
from collections.abc import Callable

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.core.config import DATA_DIR, get_settings

# Short consumer-spend series produce convergence chatter on nearly every fit.
# It is expected, not diagnostic, and would bury the actual output.
warnings.simplefilter("ignore", ConvergenceWarning)
warnings.simplefilter("ignore", UserWarning)

# Matches forecasting.MIN_MONTHS_FOR_ARIMA: fewer points than this and the app
# doesn't attempt a fit either, so scoring one here would measure nothing the
# app does.
MIN_TRAIN_MONTHS = 8
# Below this a backtest is a handful of samples and the ranking is noise.
MIN_FOLDS = 5

Forecaster = Callable[[pd.Series], float]


def _fit_arima(history: pd.Series, order: tuple[int, int, int]) -> float:
    try:
        return max(float(ARIMA(history, order=order).fit().forecast(1).iloc[0]), 0.0)
    except Exception:
        return float(history.mean())


def naive(history: pd.Series) -> float:
    """Next month looks like last month. The baseline everything is scored against."""
    return float(history.iloc[-1])


def mean_all(history: pd.Series) -> float:
    return float(history.mean())


def mean_last_3(history: pd.Series) -> float:
    return float(history.tail(3).mean())


def seasonal_naive(history: pd.Series) -> float:
    """This month last year. Falls back to naive before a full year exists."""
    return float(history.iloc[-12]) if len(history) >= 12 else naive(history)


def arima_510(history: pd.Series) -> float:
    """The order the app currently hardcodes."""
    return _fit_arima(history, (5, 1, 0))


def arima_011(history: pd.Series) -> float:
    return _fit_arima(history, (0, 1, 1))


def arima_auto(history: pd.Series) -> float:
    """Small AICc grid search, instead of one order chosen up front."""
    best_forecast, best_ic = None, np.inf
    for p in range(3):
        for d in range(2):
            for q in range(3):
                if p == d == q == 0:
                    continue
                try:
                    fit = ARIMA(history, order=(p, d, q)).fit()
                    if fit.aicc < best_ic:
                        best_ic = fit.aicc
                        best_forecast = max(float(fit.forecast(1).iloc[0]), 0.0)
                except Exception:
                    continue
    return best_forecast if best_forecast is not None else float(history.mean())


def ets(history: pd.Series) -> float:
    try:
        fit = ExponentialSmoothing(history, trend=None, seasonal=None).fit()
        return max(float(fit.forecast(1).iloc[0]), 0.0)
    except Exception:
        return float(history.mean())


CANDIDATES: dict[str, Forecaster] = {
    "naive (last month)": naive,
    "mean (all history)": mean_all,
    "mean (last 3)": mean_last_3,
    "seasonal naive": seasonal_naive,
    "ARIMA(5,1,0) [current]": arima_510,
    "ARIMA(0,1,1)": arima_011,
    "ARIMA auto (AICc grid)": arima_auto,
    "ETS (simple exp smoothing)": ets,
}


def load_monthly_series() -> dict[str, pd.Series]:
    """Monthly spend totals per user, gaps zero-filled."""
    engine = create_engine(get_settings().sync_database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT u.username, t.date, t.amount
                FROM transactions t
                JOIN users u ON u.id = t.user_id
                """
            )
        ).all()
    engine.dispose()

    df = pd.DataFrame(rows, columns=["user", "date", "amount"])
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    df["amount"] = df["amount"].astype(float)

    series: dict[str, pd.Series] = {}
    for user, group in df.groupby("user"):
        monthly = group.set_index("date")["amount"].resample("ME").sum()
        # Same zero-fill the service does: a month with no spending must exist
        # as a zero, or the models treat non-adjacent months as consecutive.
        monthly = monthly.reindex(
            pd.date_range(monthly.index.min(), monthly.index.max(), freq="ME"),
            fill_value=0.0,
        )
        series[str(user)] = monthly
    return series


def backtest(monthly: pd.Series) -> dict[str, float]:
    """Mean absolute error of each candidate over an expanding window."""
    scores: dict[str, float] = {}
    for name, forecaster in CANDIDATES.items():
        errors = [
            abs(forecaster(monthly.iloc[:cut]) - float(monthly.iloc[cut]))
            for cut in range(MIN_TRAIN_MONTHS, len(monthly))
        ]
        scores[name] = float(np.mean(errors))
    return scores


def main() -> None:
    report: dict[str, object] = {}

    for user, monthly in sorted(load_monthly_series().items()):
        folds = len(monthly) - MIN_TRAIN_MONTHS
        if folds < MIN_FOLDS:
            continue

        scores = backtest(monthly)
        baseline = scores["naive (last month)"]
        ranked = sorted(scores.items(), key=lambda kv: kv[1])

        print(f"\n=== {user} — {len(monthly)} months, mean ${monthly.mean():,.0f}/mo ===")
        print(f"    rolling-origin, {folds} one-step-ahead forecasts\n")
        for name, mae in ranked:
            skill = (1 - mae / baseline) * 100 if baseline else 0.0
            marker = "  <-- best" if name == ranked[0][0] else ""
            print(f"    {name:<28} MAE ${mae:>10,.0f}   vs naive {skill:+6.1f}%{marker}")

        report[user] = {
            "months": len(monthly),
            "folds": folds,
            "mean_monthly_spend": round(float(monthly.mean()), 2),
            "mae": {name: round(mae, 2) for name, mae in ranked},
            "best": ranked[0][0],
        }

    if not report:
        print("No account has enough history to backtest.")
        return

    out = DATA_DIR / "forecast_eval.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
