"""Monthly spend forecasting and anomaly detection.

Kept behind a small interface so the model can be swapped (statsforecast's
AutoETS/MSTL are the obvious next step) without touching routers.

The previous implementation wrapped the fit in a bare ``except Exception:
return None``, so an under-specified model, a singular matrix, and a genuine
bug all produced the same silent null. Here, "not enough history" is an
explicit, reported state, and unexpected failures are logged.
"""

import warnings
from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.arima.model import ARIMA

from ..core.logging import get_logger
from ..models import Transaction
from ..schemas.forecast import Anomaly, ForecastPoint, ForecastSeries

log = get_logger(__name__)

FORECAST_STEPS = 6
ARIMA_ORDER = (5, 1, 0)
MODEL_NAME = f"ARIMA{ARIMA_ORDER}"

# ARIMA(5,1,0) estimates 5 autoregressive terms on differenced data, so it
# needs more than 6 points to be anything but overfitted noise.
MIN_MONTHS_FOR_ARIMA = 8
# Below that we still show something useful, just labelled honestly.
MIN_MONTHS_FOR_MEAN = 2

ANOMALY_Z_THRESHOLD = 2.0


async def load_transactions(
    db: AsyncSession, user_id: int, category: str | None = None
) -> pd.DataFrame:
    """Fetch a user's transactions as a DataFrame of date/amount/category."""
    stmt = select(Transaction.date, Transaction.amount, Transaction.category).where(
        Transaction.user_id == user_id
    )
    if category:
        stmt = stmt.where(Transaction.category == category)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return pd.DataFrame(columns=["date", "amount", "category"])

    return pd.DataFrame(
        [
            {"date": pd.Timestamp(row.date), "amount": float(row.amount), "category": row.category}
            for row in rows
        ]
    )


def _to_monthly(df: pd.DataFrame) -> pd.Series:
    """Sum to calendar-month totals, filling gaps with zero.

    Without the reindex a month in which nothing was spent simply wouldn't
    exist, and ARIMA would treat two non-adjacent months as consecutive.
    """
    if df.empty:
        return pd.Series(dtype="float64")

    monthly = df.set_index("date")["amount"].resample("ME").sum()
    if len(monthly) > 1:
        full_range = pd.date_range(monthly.index.min(), monthly.index.max(), freq="ME")
        monthly = monthly.reindex(full_range, fill_value=0.0)
    return monthly


def _mean_forecast(monthly: pd.Series, steps: int) -> tuple[list[ForecastPoint], str, bool]:
    """Flat mean projection, for when there isn't enough history to fit."""
    if monthly.empty:
        return [], "insufficient-history", False

    mean = float(monthly.mean())
    std = float(monthly.std()) if len(monthly) > 1 else 0.0
    future = pd.date_range(start=monthly.index[-1], periods=steps + 1, freq="ME")[1:]

    points = [
        ForecastPoint(
            date=stamp.date(),
            amount=Decimal(str(round(mean, 2))),
            lower=Decimal(str(round(max(mean - std, 0.0), 2))),
            upper=Decimal(str(round(mean + std, 2))),
        )
        for stamp in future
    ]
    return points, "mean-baseline", False


def forecast_series(
    df: pd.DataFrame, *, category: str | None = None, steps: int = FORECAST_STEPS
) -> ForecastSeries:
    """Forecast monthly spend, with prediction intervals where available."""
    monthly = _to_monthly(df)

    history = [
        ForecastPoint(date=stamp.date(), amount=Decimal(str(round(value, 2))))
        for stamp, value in monthly.items()
    ]

    if len(monthly) < MIN_MONTHS_FOR_MEAN:
        return ForecastSeries(
            category=category,
            history=history,
            forecast=[],
            model="insufficient-history",
            is_fitted=False,
        )

    if len(monthly) < MIN_MONTHS_FOR_ARIMA:
        points, model_name, fitted = _mean_forecast(monthly, steps)
        return ForecastSeries(
            category=category,
            history=history,
            forecast=points,
            model=model_name,
            is_fitted=fitted,
        )

    try:
        with warnings.catch_warnings():
            # Convergence chatter is expected on short consumer-spend series
            # and would otherwise flood the logs on every request.
            warnings.simplefilter("ignore", ConvergenceWarning)
            warnings.simplefilter("ignore", UserWarning)
            fit = ARIMA(monthly, order=ARIMA_ORDER).fit()

        prediction = fit.get_forecast(steps=steps)
        mean = prediction.predicted_mean
        intervals = prediction.conf_int(alpha=0.20)  # 80% band
        future = pd.date_range(start=monthly.index[-1], periods=steps + 1, freq="ME")[1:]

        points = [
            ForecastPoint(
                date=stamp.date(),
                # Spend can't be negative; ARIMA on a short series can project
                # below zero, which is a modelling artifact, not a prediction.
                amount=Decimal(str(round(max(float(value), 0.0), 2))),
                lower=Decimal(str(round(max(float(low), 0.0), 2))),
                upper=Decimal(str(round(max(float(high), 0.0), 2))),
            )
            for stamp, value, low, high in zip(
                future, mean, intervals.iloc[:, 0], intervals.iloc[:, 1], strict=False
            )
        ]
        return ForecastSeries(
            category=category,
            history=history,
            forecast=points,
            model=MODEL_NAME,
            is_fitted=True,
        )

    except Exception as exc:
        # Genuinely unexpected: log it, then degrade to the baseline rather
        # than returning nothing at all.
        log.warning(
            "forecast.arima_failed",
            category=category,
            months=len(monthly),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        points, model_name, fitted = _mean_forecast(monthly, steps)
        return ForecastSeries(
            category=category,
            history=history,
            forecast=points,
            model=model_name,
            is_fitted=fitted,
        )


def detect_anomalies(df: pd.DataFrame, threshold: float = ANOMALY_Z_THRESHOLD) -> list[Anomaly]:
    """Flag months whose category spend sits far above its own norm.

    Per-category z-scores, because a $400 rent month is normal and a $400
    coffee month is not -- a global threshold can't tell those apart.
    """
    if df.empty:
        return []

    anomalies: list[Anomaly] = []
    for category, group in df.groupby("category"):
        monthly = _to_monthly(group)
        if len(monthly) < 4:
            continue  # too few points for a meaningful standard deviation

        mean = float(monthly.mean())
        std = float(monthly.std())
        if std <= 0:
            continue

        for stamp, value in monthly.items():
            z = (float(value) - mean) / std
            if z >= threshold:
                anomalies.append(
                    Anomaly(
                        date=stamp.date(),
                        category=str(category),
                        amount=Decimal(str(round(float(value), 2))),
                        expected=Decimal(str(round(mean, 2))),
                        z_score=round(z, 2),
                    )
                )

    return sorted(anomalies, key=lambda a: a.z_score, reverse=True)[:10]


def top_categories(df: pd.DataFrame, limit: int = 5) -> list[str]:
    """The categories worth forecasting individually."""
    if df.empty:
        return []
    totals = df.groupby("category")["amount"].sum().sort_values(ascending=False)
    return [str(c) for c in totals.head(limit).index]


def month_start(value: date) -> date:
    return value.replace(day=1)
