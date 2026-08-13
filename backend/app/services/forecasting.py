import pandas as pd
from sqlalchemy.orm import Session
from statsmodels.tsa.arima.model import ARIMA

from .. import models

FORECAST_STEPS = 6
ARIMA_ORDER = (5, 1, 0)


def load_transactions_dataframe(db: Session, user_id: int) -> pd.DataFrame:
    rows = (
        db.query(models.Transaction)
        .filter(models.Transaction.user_id == user_id)
        .all()
    )
    return pd.DataFrame([{"date": pd.to_datetime(r.date), "amount": r.amount} for r in rows])


def forecast_expenses(df: pd.DataFrame, steps: int = FORECAST_STEPS) -> dict | None:
    """Monthly-resampled ARIMA forecast of expenses.

    `df` must have a `date` column (datetime-like) and an `amount` column.
    Returns None when there isn't enough history for ARIMA to fit, mirroring
    the original pages/forecast.py behavior.
    """
    monthly = df.set_index("date")[["amount"]].resample("ME").sum()

    try:
        model = ARIMA(monthly["amount"], order=ARIMA_ORDER).fit()
    except Exception:
        return None

    forecast = model.forecast(steps=steps)
    future_index = pd.date_range(start=monthly.index[-1], periods=steps + 1, freq="ME")[1:]

    return {
        "history": [
            {"date": d.date().isoformat(), "amount": float(a)}
            for d, a in monthly["amount"].items()
        ],
        "forecast": [
            {"date": d.date().isoformat(), "amount": float(a)}
            for d, a in zip(future_index, forecast)
        ],
    }
