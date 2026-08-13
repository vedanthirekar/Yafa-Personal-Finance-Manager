from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base, TimestampMixin


class Merchant(Base, TimestampMixin):
    """A normalized payee.

    Extracted descriptions are messy and repetitive ("starbucks", "Starbucks
    #4412", "STARBUCKS COFFEE"). Collapsing them onto one row gives Power BI a
    real dimension to slice by, and gives the categorizer a stable key to
    remember a user's correction against.
    """

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Lowercased, punctuation-stripped form used for lookup.
    normalized_name: Mapped[str] = mapped_column(
        String(200), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Sticky category: once a user corrects "starbucks" to Food & Dining, later
    # transactions for that merchant skip the model entirely.
    default_category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<Merchant {self.display_name!r}>"
