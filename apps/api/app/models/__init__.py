"""ORM models.

Every model must be imported here. Alembic's autogenerate walks
``Base.metadata``, and a model that is never imported is invisible to it --
which shows up as a mysteriously empty migration.
"""

from ..core.database import Base
from .budget import Budget
from .merchant import Merchant
from .prediction import CategoryPrediction
from .transaction import Transaction, TransactionSource
from .user import User

__all__ = [
    "Base",
    "Budget",
    "CategoryPrediction",
    "Merchant",
    "Transaction",
    "TransactionSource",
    "User",
]
