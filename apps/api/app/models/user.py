from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from .budget import Budget
    from .transaction import Transaction


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # The demo account is wiped and reseeded on login, so it must never be
    # confused with a real one.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Display/parse currency for this user. The previous build parsed USD
    # ("$", "dollars", "bucks") while rendering "Rs." -- making it explicit and
    # per-user is what stops that mismatch recurring.
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    budgets: Mapped[list["Budget"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"
