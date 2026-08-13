from datetime import date as date_type
from decimal import Decimal

from pydantic import BaseModel


class ForecastPoint(BaseModel):
    date: date_type
    amount: Decimal
    # Prediction interval. Null on historical points, which are observations
    # rather than estimates -- rendering a band around them would be a lie.
    lower: Decimal | None = None
    upper: Decimal | None = None


class ForecastSeries(BaseModel):
    category: str | None  # None == all categories combined
    history: list[ForecastPoint]
    forecast: list[ForecastPoint]
    model: str  # e.g. "ARIMA(5,1,0)" -- shown in the UI footnote
    # False when there wasn't enough history to fit; the client should say so
    # rather than draw a flat line and imply confidence.
    is_fitted: bool


class Anomaly(BaseModel):
    date: date_type
    category: str
    amount: Decimal
    expected: Decimal
    # How many standard deviations above the category's rolling mean.
    z_score: float


class ForecastResponse(BaseModel):
    overall: ForecastSeries
    by_category: list[ForecastSeries]
    anomalies: list[Anomaly]
