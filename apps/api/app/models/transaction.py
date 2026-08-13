import enum
from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from .merchant import Merchant
    from .prediction import CategoryPrediction
    from .user import User


class TransactionSource(str, enum.Enum):
    """How the transaction got into the system -- useful for both debugging
    and for measuring how much of the app's value actually comes from voice."""

    VOICE = "voice"
    MANUAL = "manual"
    IMPORT = "import"
    DEMO_SEED = "demo_seed"


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    date: Mapped[date_type] = mapped_column(Date, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    # Numeric, not Float. Binary floats cannot represent most decimal
    # fractions, so a Float column silently accumulates error across sums --
    # unacceptable for money and visible in any Power BI total.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    merchant_id: Mapped[int | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source: Mapped[TransactionSource] = mapped_column(
        Enum(TransactionSource, name="transaction_source", native_enum=False),
        default=TransactionSource.MANUAL,
        nullable=False,
    )

    # Verbatim speech-to-text output, kept only for voice rows. Lets a user see
    # what was actually heard when a parse looks wrong.
    raw_transcript: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    user: Mapped["User"] = relationship(back_populates="transactions")
    merchant: Mapped["Merchant | None"] = relationship(lazy="joined")
    predictions: Mapped[list["CategoryPrediction"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Every list and chart query filters by user and orders by date; the
        # composite index serves both without a sort step.
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_user_category", "user_id", "category"),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.date} {self.amount} {self.category!r}>"
