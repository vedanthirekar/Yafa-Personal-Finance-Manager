from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import User


class Budget(Base, TimestampMixin):
    """A monthly spending cap for one category.

    Gives the forecast something to be measured against: a projection is only
    actionable next to a target. Feeds the budget-vs-actual visual in both the
    web app and Power BI.
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    user: Mapped["User"] = relationship(back_populates="budgets")

    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_budget_user_category"),
    )

    def __repr__(self) -> str:
        return f"<Budget {self.category!r} {self.monthly_limit}>"
