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
    model: str  # "exponential smoothing", or why there is no forecast
    # False when there wasn't enough history to fit. `forecast` is empty in
    # that case -- the client should say how much more history is needed
    # rather than draw a flat line and imply confidence.
    is_fitted: bool
    # Complete months available, and how many the forecaster needs. Lets the
    # client render "3 of 6 months" instead of a bare "unavailable".
    months_of_history: int = 0
    months_required: int = 0
    # The fitted smoothing parameter, when there is one. Near 1 means this
    # account's spend is best predicted by last month alone; near 0 means the
    # long-run average wins. Exposed because it is the entire model.
    smoothing_level: float | None = None


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
