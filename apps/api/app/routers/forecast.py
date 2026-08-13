from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import models, schemas, security
from ..database import get_db
from ..services.forecasting import forecast_expenses, load_transactions_dataframe

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/me", response_model=schemas.ForecastResponse | None)
async def get_my_forecast(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(security.get_current_user),
):
    df = load_transactions_dataframe(db, current_user.id)
    if df.empty:
        return None
    # ARIMA fitting is CPU-bound/blocking -- keep it off the event loop.
    return await run_in_threadpool(forecast_expenses, df)
