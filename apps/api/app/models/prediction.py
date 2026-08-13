from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from .transaction import Transaction


class CategoryPrediction(Base, TimestampMixin):
    """What the model said, versus what the user kept.

    Recorded on every categorization. Cheap to write, and it is what makes
    three otherwise-impossible things possible:

    * Power BI can chart average confidence and low-confidence volume.
    * Accuracy can be measured against real user behaviour rather than only
      against the synthetic training corpus.
    * Corrections become labeled training data, with provenance.

    ``confidence`` is a Float on purpose -- unlike money, a similarity score
    has no exact-decimal requirement.
    """

    __tablename__ = "category_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Null means the model returned nothing above the confidence threshold.
    predicted_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Which model produced this, so metrics stay interpretable after a swap.
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)

    # False once the user overrides the suggestion. Set at correction time.
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    corrected_to: Mapped[str | None] = mapped_column(String(100), nullable=True)

    transaction: Mapped["Transaction"] = relationship(back_populates="predictions")

    def __repr__(self) -> str:
        return f"<CategoryPrediction {self.predicted_category!r} @{self.confidence:.2f}>"
