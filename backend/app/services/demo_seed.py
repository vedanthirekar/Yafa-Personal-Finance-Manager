"""Seeds a fixed, always-pristine demo account so a visitor can explore the
app with realistic data via a single "Try Demo Account" click, with no
registration or manual data entry needed.

`reset_and_seed` is called on every demo login (see
backend/app/routers/auth.py's /auth/demo-login), wiping and re-inserting the
demo user's transactions each time -- this keeps the demo convincing for the
*next* visitor regardless of what a previous visitor added, edited, or
deleted during their session. Known limitation: concurrent demo visitors
share one account, so a second click resets what the first person is
looking at -- out of scope to build full per-session isolation for this.
"""

import random
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from .. import models, security
from ...scripts.build_training_data import CANONICAL_CATEGORIES

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"

DEMO_USERNAME = "demo"
DEMO_EMAIL = "demo@yafa.app"
DEMO_NAME = "Demo User"
DEMO_PASSWORD = "YafaDemo!2026"  # never typed by a real user; login is button-only

MONTHS = 12
TXNS_PER_MONTH_RANGE = (20, 30)
SEED = 20260813


def _load_sample_rows() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "sample-data.csv")
    df = df.rename(columns={"Description": "text", "Category": "category", "Amount": "amount"})
    df["category"] = df["category"].replace({"Family": "Social Life"})
    df = df[df["category"].isin(CANONICAL_CATEGORIES)]
    return df[["text", "category", "amount"]].dropna()


def get_or_create_demo_user(db: Session) -> models.User:
    user = db.query(models.User).filter(models.User.username == DEMO_USERNAME).first()
    if user is None:
        user = models.User(
            username=DEMO_USERNAME,
            email=DEMO_EMAIL,
            name=DEMO_NAME,
            hashed_password=security.hash_password(DEMO_PASSWORD),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def reset_and_seed(db: Session, user: models.User) -> int:
    """Wipes `user`'s existing transactions and inserts a fresh ~12-month
    spread of realistic, category-labeled transactions sourced from
    data/sample-data.csv, so the Expense Stats page (pie/line charts) and
    Forecast page (needs enough monthly history for ARIMA to fit) both look
    populated and convincing. Returns the number of rows inserted.
    """
    db.query(models.Transaction).filter(models.Transaction.user_id == user.id).delete()

    pool = _load_sample_rows()
    rng = random.Random(SEED)
    today = date.today()

    inserted = 0
    for months_back in range(MONTHS):
        month_anchor = pd.Timestamp(today) - pd.DateOffset(months=months_back)
        n = rng.randint(*TXNS_PER_MONTH_RANGE)
        rows = pool.sample(n=n, random_state=rng.randint(0, 2**31 - 1), replace=True)
        # Cap the current month's transactions to today's day-of-month --
        # otherwise a random day 1-28 can land after today, producing
        # future-dated transactions in the current month.
        max_day = min(28, today.day) if months_back == 0 else 28
        for _, row in rows.iterrows():
            day = rng.randint(1, max_day)
            txn_date = date(month_anchor.year, month_anchor.month, day)
            db.add(
                models.Transaction(
                    user_id=user.id,
                    date=txn_date,
                    description=str(row["text"]),
                    category=row["category"],
                    amount=float(row["amount"]),
                )
            )
            inserted += 1

    db.commit()
    return inserted
