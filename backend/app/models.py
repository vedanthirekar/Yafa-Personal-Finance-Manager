from datetime import date as date_type, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    date: Mapped[date_type] = mapped_column(Date, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="transactions")
