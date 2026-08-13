"""One-time migration of the legacy `config.yaml` (streamlit_authenticator
bcrypt credentials) and `database.db` (flat `users` table that actually holds
transactions) into the new SQLAlchemy schema (backend/yafa.db).

Idempotent: safe to re-run against the same backend/yafa.db, it skips users
and transactions that already exist.

Run from the repo root:
    python -m backend.scripts.migrate_config_users
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

from backend.app import models
from backend.app.database import Base, SessionLocal, engine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_YAML = REPO_ROOT / "config.yaml"
LEGACY_DB = REPO_ROOT / "database.db"


def migrate_users(db) -> dict[str, models.User]:
    with open(CONFIG_YAML) as f:
        config = yaml.safe_load(f)

    users_by_name: dict[str, models.User] = {}
    for username, info in config["credentials"]["usernames"].items():
        existing = db.query(models.User).filter(models.User.username == username).first()
        if existing:
            users_by_name[username] = existing
            continue
        # info["password"] is already a bcrypt hash ($2b$12$...) written by
        # streamlit_authenticator -- passlib verifies it natively, no re-hash needed.
        user = models.User(
            username=username,
            email=info["email"],
            name=info["name"],
            hashed_password=info["password"],
        )
        db.add(user)
        db.flush()
        users_by_name[username] = user
        print(f"Migrated user: {username}")

    db.commit()
    return users_by_name


def migrate_transactions(db, users_by_name: dict[str, models.User]) -> None:
    if not LEGACY_DB.exists():
        print(f"No legacy database.db found at {LEGACY_DB}, skipping transaction migration.")
        return

    conn = sqlite3.connect(LEGACY_DB)
    cur = conn.cursor()
    cur.execute("select date, username, description, category, amount from users")
    rows = cur.fetchall()
    conn.close()

    migrated = 0
    for date_str, username, description, category, amount in rows:
        user = users_by_name.get(username)
        if user is None:
            print(f"Skipping row for unknown user '{username}'")
            continue
        try:
            txn_date = datetime.strptime(date_str, "%d-%m-%Y").date()
        except (ValueError, TypeError):
            print(f"Skipping row with unparseable date '{date_str}'")
            continue

        already_migrated = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.user_id == user.id,
                models.Transaction.date == txn_date,
                models.Transaction.description == description,
                models.Transaction.amount == float(amount),
            )
            .first()
        )
        if already_migrated:
            continue

        db.add(
            models.Transaction(
                user_id=user.id,
                date=txn_date,
                description=str(description),
                category=str(category) if category else "Uncategorized",
                amount=float(amount),
            )
        )
        migrated += 1

    db.commit()
    print(f"Migrated {migrated} transactions.")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        users_by_name = migrate_users(db)
        migrate_transactions(db, users_by_name)
    finally:
        db.close()


if __name__ == "__main__":
    main()
