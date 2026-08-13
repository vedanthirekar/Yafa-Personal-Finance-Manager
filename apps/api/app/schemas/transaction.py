from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ..models.transaction import TransactionSource


class TransactionCreate(BaseModel):
    date: date_type
    description: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=12)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    merchant: str | None = Field(default=None, max_length=200)
    source: TransactionSource = TransactionSource.MANUAL
    raw_transcript: str | None = Field(default=None, max_length=1000)


class TransactionUpdate(BaseModel):
    """All fields optional -- this is a PATCH body."""

    date: date_type | None = None
    description: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    amount: Decimal | None = Field(default=None, gt=0, decimal_places=2, max_digits=12)
    merchant: str | None = Field(default=None, max_length=200)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    description: str
    category: str
    amount: Decimal
    currency: str
    source: TransactionSource
    merchant: str | None = None
    raw_transcript: str | None = None
    created_at: datetime

    # Surfaced from the latest CategoryPrediction so the UI can render a
    # confidence chip and prompt for a correction when the model was unsure.
    confidence: float | None = None
    was_auto_categorized: bool = False


class TransactionPage(BaseModel):
    """Paginated envelope. The old endpoint returned an unbounded list, which
    is fine at 300 rows and not fine at 300,000."""

    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class CategoryBreakdownItem(BaseModel):
    category: str
    total_amount: Decimal
    transaction_count: int
    pct_of_total: float
