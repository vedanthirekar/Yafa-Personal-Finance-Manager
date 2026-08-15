"""Monthly spend forecasting and anomaly detection.

The forecaster is **simple exponential smoothing** -- one method, the same one
for every account. See ``docs/forecasting-notes.md`` for the backtest that
chose it.

Why this and not something more impressive: monthly household spending is
close to a stable level plus noise, and on a rolling-origin backtest of eight
candidates the simple methods won outright. The previous ARIMA(5,1,0) placed
*last of eight* on an 18-month account -- 45% worse than just repeating last
month's total -- because it estimates five autoregressive coefficients from
seventeen differenced points and ends up fitting noise.

Exponential smoothing is a weighted average of past months where recent months
count more, and *how much* more is a single parameter (alpha) estimated from
each user's own history. That one parameter spans both of the things that beat
ARIMA in the backtest:

    alpha -> 1    "next month looks like last month"      (won on 75 months)
    alpha -> 0    "next month looks like the long average" (won on 18 months)

So the model adapts per account without any per-user model selection, branching,
or hardcoded window. It is also exactly ARIMA(0,1,1) -- the same family as
before, with the right number of parameters instead of five.
"""

import warnings
from datetime import date
from decimal import Decimal
from typing import cast

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.holtwinters import SimpleExpSmoothing

from ..core.logging import get_logger
from ..models import Transaction
from ..schemas.forecast import Anomaly, ForecastPoint, ForecastSeries

log = get_logger(__name__)

FORECAST_STEPS = 6
MODEL_NAME = "exponential smoothing"

# Below this we don't forecast at all -- the client is told how many months it
# has and how many it needs, and says so.
#
# Six is where the two estimated parameters (alpha and the initial level) stop
# being guesses. Under that, alpha is essentially unidentifiable: the optimiser
# will still return a number, but it is fitted to three or four points and the
# prediction interval built from it means nothing. Showing a flat average and
# calling it a projection -- which is what this used to do -- is worse than
# saying "not yet".
MIN_MONTHS_TO_FORECAST = 6

# A run of this many consecutive empty months is read as dormancy -- the
# account was abandoned and later picked back up -- and everything before it is
# dropped from the fit.
#
# ``_to_monthly`` zero-fills gaps, which is right for one or two quiet months
# inside an active stretch and badly wrong for a long absence: an account with
# an 18-month hole teaches the model that spending collapsed to nothing for a
# year and a half, which inflates the residual variance enormously and drags
# the level down. The imported historical account has exactly that shape.
DORMANCY_MONTHS = 6

# Two-sided 80% normal quantile, for the prediction interval.
Z_80 = 1.2815515655446004

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
    exist, and the model would treat two non-adjacent months as consecutive.
    """
    if df.empty:
        return pd.Series(dtype="float64")

    monthly = df.set_index("date")["amount"].resample("ME").sum()
    if len(monthly) > 1:
        full_range = pd.date_range(monthly.index.min(), monthly.index.max(), freq="ME")
        monthly = monthly.reindex(full_range, fill_value=0.0)
    return monthly


def _drop_partial_month(monthly: pd.Series, today: date | None = None) -> pd.Series:
    """Drop a trailing point for the month we're currently living through.

    The newest bucket is only as complete as today's date. Fitting on it teaches
    the model that spending just fell off a cliff -- on the 14th of the month it
    looks like a ~50% drop -- and since exponential smoothing weights the most
    recent observation most heavily, that is exactly the point it trusts most.

    The partial month stays in ``history`` for the chart; it is only excluded
    from the fit.
    """
    if monthly.empty:
        return monthly

    now = today or date.today()
    last = monthly.index[-1]
    if last.year == now.year and last.month == now.month:
        return monthly.iloc[:-1]
    return monthly


def _recent_era(monthly: pd.Series) -> pd.Series:
    """Keep only what follows the most recent long stretch of empty months.

    A genuine zero-spend month is rare; six in a row is not a spending pattern,
    it's an absence. Whatever the account looked like before it came back is a
    different regime and shouldn't inform the forecast.

    A filled zero and a real zero are indistinguishable by this point, which is
    fine -- six consecutive months of spending exactly nothing is dormancy
    either way.
    """
    if monthly.empty:
        return monthly

    values = monthly.to_numpy(dtype=float)
    run = 0
    cut = 0
    for i, value in enumerate(values):
        if value == 0.0:
            run += 1
            if run >= DORMANCY_MONTHS:
                # Keep advancing while the gap continues, so `cut` lands on the
                # first active month after it rather than mid-gap.
                cut = i + 1
        else:
            run = 0
    return monthly.iloc[cut:]


def _empty_series(
    category: str | None, history: list[ForecastPoint], months: int, model: str
) -> ForecastSeries:
    return ForecastSeries(
        category=category,
        history=history,
        forecast=[],
        model=model,
        is_fitted=False,
        months_of_history=months,
        months_required=MIN_MONTHS_TO_FORECAST,
    )


def forecast_series(
    df: pd.DataFrame, *, category: str | None = None, steps: int = FORECAST_STEPS
) -> ForecastSeries:
    """Forecast monthly spend with an 80% prediction interval.

    Returns an unfitted series with ``months_of_history`` / ``months_required``
    when there isn't enough history yet, so the client can say how far off the
    user is rather than drawing a line nobody should trust.
    """
    monthly = _to_monthly(df)

    history = [
        # pandas-stubs types Series.items() keys as Hashable regardless of the
        # actual index dtype, so the monthly-Timestamp index needs a cast.
        ForecastPoint(date=cast(pd.Timestamp, stamp).date(), amount=Decimal(str(round(value, 2))))
        for stamp, value in monthly.items()
    ]

    fitting = _recent_era(_drop_partial_month(monthly))
    if len(fitting) < MIN_MONTHS_TO_FORECAST:
        return _empty_series(category, history, len(fitting), "not-enough-history")

    try:
        with warnings.catch_warnings():
            # Convergence chatter is expected on short consumer-spend series
            # and would otherwise flood the logs on every request.
            warnings.simplefilter("ignore", ConvergenceWarning)
            warnings.simplefilter("ignore", UserWarning)
            fit = SimpleExpSmoothing(
                fitting.to_numpy(dtype=float), initialization_method="estimated"
            ).fit(optimized=True)

        alpha = float(fit.params["smoothing_level"])

        # Exponential smoothing forecasts a flat line: every horizon gets the
        # same point estimate. The interval is what widens.
        point = float(fit.forecast(1)[0])

        # Residual scale, with a degree of freedom taken back for each of the
        # two estimated parameters (alpha, initial level).
        n = len(fitting)
        sigma = float(np.sqrt(fit.sse / max(n - 2, 1)))

        # ETS(A,N,N) h-step variance: sigma^2 * [1 + (h-1) * alpha^2].
        # Hyndman & Athanasopoulos, *Forecasting: Principles and Practice*,
        # 3rd ed. §7.7. Derived from the model rather than bootstrapped, which
        # matters here -- there is not enough history to bootstrap from.
        if not np.isfinite(point) or not np.isfinite(sigma) or not np.isfinite(alpha):
            raise ValueError("smoothing produced a non-finite fit")

        # Anchored to the *full* series, not the fitted one. The partial
        # current month is excluded from the fit but it has still happened --
        # starting the horizon after `fitting` would emit a "forecast" for a
        # month already sitting in `history`, and the chart would draw August
        # twice with two different numbers.
        future = pd.date_range(start=monthly.index[-1], periods=steps + 1, freq="ME")[1:]

        points: list[ForecastPoint] = []
        for horizon, stamp in enumerate(future, start=1):
            half = Z_80 * sigma * float(np.sqrt(1.0 + (horizon - 1) * alpha**2))
            points.append(
                ForecastPoint(
                    date=stamp.date(),
                    # Spend can't be negative, so the band is clipped rather
                    # than shown crossing zero.
                    amount=Decimal(str(round(max(point, 0.0), 2))),
                    lower=Decimal(str(round(max(point - half, 0.0), 2))),
                    upper=Decimal(str(round(max(point + half, 0.0), 2))),
                )
            )

        return ForecastSeries(
            category=category,
            history=history,
            forecast=points,
            model=MODEL_NAME,
            is_fitted=True,
            months_of_history=len(fitting),
            months_required=MIN_MONTHS_TO_FORECAST,
            smoothing_level=round(alpha, 4),
        )

    except Exception as exc:
        # Genuinely unexpected: log it, then report the series as unfitted
        # rather than inventing a projection to fill the gap.
        log.warning(
            "forecast.smoothing_failed",
            category=category,
            months=len(fitting),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return _empty_series(category, history, len(fitting), "unavailable")


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
                        date=cast(pd.Timestamp, stamp).date(),
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
