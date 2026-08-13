"""A fixed, always-pristine demo account.

``reset_and_seed`` runs on every ``/auth/demo-login``, wiping and re-inserting
the demo user's transactions so the app looks convincing for the next visitor
regardless of what the previous one did.

Known limitation, unchanged and deliberate: all demo visitors share one
account, so a second login resets what the first person is looking at. Proper
per-session isolation isn't worth the complexity for a demo -- the account is
flagged ``is_demo`` precisely so nothing else in the system mistakes it for a
real user.
"""

import random
from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import DATA_DIR
from ..core.logging import get_logger
from ..core.security import hash_password
from ..models import Budget, Transaction, TransactionSource, User

log = get_logger(__name__)

DEMO_USERNAME = "demo"
DEMO_EMAIL = "demo@yafa.app"
DEMO_NAME = "Demo User"
# Never typed by a human -- demo login is button-only and takes no password.
# Set once at creation so the row satisfies the not-null constraint.
DEMO_PASSWORD = "YafaDemo!2026"

MONTHS = 18  # enough history for ARIMA to actually fit (see MIN_MONTHS_FOR_ARIMA)
TXNS_PER_MONTH_RANGE = (20, 30)
SEED = 20260813

# Canonical categories the seed corpus is mapped onto. Duplicated from the
# corpus builder in ml/ on purpose: the API must not import from the offline
# ML tooling, which isn't installed in the API container.
CANONICAL_CATEGORIES = [
    "Food",
    "Transportation",
    "Apparel",
    "Household",
    "Health",
    "Education",
    "Entertainment",
    "Social Life",
    "Tourism",
    "Subscription",
]

DEFAULT_BUDGETS = {
    "Food": Decimal("600.00"),
    "Transportation": Decimal("250.00"),
    "Entertainment": Decimal("200.00"),
    "Household": Decimal("400.00"),
    "Subscription": Decimal("80.00"),
}


def _load_sample_rows() -> pd.DataFrame:
    path = DATA_DIR / "sample-data.csv"
    if not path.exists():
        log.warning("demo_seed.sample_data_missing", path=str(path))
        return pd.DataFrame(columns=["text", "category", "amount"])

    df = pd.read_csv(path)
    df = df.rename(columns={"Description": "text", "Category": "category", "Amount": "amount"})
    df["category"] = df["category"].replace({"Family": "Social Life"})
    df = df[df["category"].isin(CANONICAL_CATEGORIES)]
    return df[["text", "category", "amount"]].dropna()


async def get_or_create_demo_user(db: AsyncSession) -> User:
    user = await db.scalar(select(User).where(User.username == DEMO_USERNAME))
    if user is None:
        user = User(
            username=DEMO_USERNAME,
            email=DEMO_EMAIL,
            name=DEMO_NAME,
            hashed_password=hash_password(DEMO_PASSWORD),
            is_demo=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def reset_and_seed(db: AsyncSession, user: User) -> int:
    """Replace the demo user's data with a fresh ~18 months of transactions.

    Returns the number of rows inserted.
    """
    await db.execute(delete(Transaction).where(Transaction.user_id == user.id))
    await db.execute(delete(Budget).where(Budget.user_id == user.id))

    pool = _load_sample_rows()
    if pool.empty:
        await db.commit()
        return 0

    rng = random.Random(SEED)
    today = date.today()
    inserted = 0

    for months_back in range(MONTHS):
        anchor = pd.Timestamp(today) - pd.DateOffset(months=months_back)
        rows = pool.sample(
            n=rng.randint(*TXNS_PER_MONTH_RANGE),
            random_state=rng.randint(0, 2**31 - 1),
            replace=True,
        )
        # In the current month, cap the day at today -- otherwise a random
        # day 1-28 lands in the future and the forecast starts mid-series.
        max_day = min(28, today.day) if months_back == 0 else 28

        for _, row in rows.iterrows():
            db.add(
                Transaction(
                    user_id=user.id,
                    date=date(anchor.year, anchor.month, rng.randint(1, max_day)),
                    description=str(row["text"]),
                    category=str(row["category"]),
                    # Quantize before insert so the seeded values match the
                    # column's scale exactly rather than relying on the driver.
                    amount=Decimal(str(round(float(row["amount"]), 2))),
                    currency=user.currency,
                    source=TransactionSource.DEMO_SEED,
                )
            )
            inserted += 1

    for category, limit in DEFAULT_BUDGETS.items():
        db.add(
            Budget(
                user_id=user.id,
                category=category,
                monthly_limit=limit,
                currency=user.currency,
            )
        )

    await db.commit()
    log.info("demo_seed.reseeded", transactions=inserted, months=MONTHS)
    return inserted
