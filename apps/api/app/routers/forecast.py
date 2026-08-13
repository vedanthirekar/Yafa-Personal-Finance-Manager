from fastapi import APIRouter, Query

from ..core.deps import CurrentUser, DbSession
from ..schemas import ForecastResponse, ForecastSeries
from ..services import forecasting

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/me", response_model=ForecastResponse)
async def forecast_me(
    db: DbSession,
    current_user: CurrentUser,
    steps: int = Query(6, ge=1, le=24),
    include_categories: bool = Query(True),
) -> ForecastResponse:
    """Forecast the user's monthly spend, overall and per category.

    Every series carries ``model`` and ``is_fitted`` so the client can say
    which projections are real ARIMA fits and which are a flat mean baseline
    standing in for insufficient history -- rather than drawing both the same
    way and implying equal confidence.
    """
    df = await forecasting.load_transactions(db, current_user.id)

    overall = forecasting.forecast_series(df, category=None, steps=steps)

    by_category: list[ForecastSeries] = []
    if include_categories and not df.empty:
        for category in forecasting.top_categories(df):
            subset = df[df["category"] == category]
            by_category.append(forecasting.forecast_series(subset, category=category, steps=steps))

    return ForecastResponse(
        overall=overall,
        by_category=by_category,
        anomalies=forecasting.detect_anomalies(df),
    )
