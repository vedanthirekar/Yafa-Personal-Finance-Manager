"""One-off migration of the SQLite-era data into Postgres.

    uv run python -m ml.migrate_sqlite_to_postgres --yafa-db backend/yafa.db
    uv run python -m ml.migrate_sqlite_to_postgres --legacy-db /tmp/database.db

Two historical sources, with different schemas:

``backend/yafa.db`` -- the interim SQLAlchemy schema.
    users(id, username, email, name, hashed_password)
    transactions(id, user_id, date, description, category, amount, created_at)

``database.db`` -- the original flat table. Note the table is *named* ``users``
but actually holds transactions, with the username repeated on every row and
no keys of any kind. Recover it with:
    git show 11c4de1:database.db > /tmp/database.db

Both are idempotent: users are matched on username and transactions are
deduplicated on (user, date, description, amount), so re-running does not
double-insert.

Amounts are converted float -> Decimal via ``str()``. Going through the string
avoids inheriting the binary-float representation error into the new
Numeric column -- Decimal(0.1) is 0.1000000000000000055511151231257827,
Decimal(str(0.1)) is exactly 0.1.
"""

import argparse
import asyncio
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Transaction, TransactionSource, User

# Users created by the old test/verification scripts. Migrating them would
# carry throwaway accounts into a fresh database for no reason.
SKIP_USERNAMES = {"verify_test_user", "example"}

# "demo" is reserved: /auth/demo-login wipes and reseeds that account on every
# login, so anything migrated into it is destroyed the first time someone
# clicks "Try Demo". Historical rows go to a parallel account instead.
USERNAME_REMAP = {"demo": "demo_legacy"}


def _parse_date(raw: str | date | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


async def _get_or_create_user(session, username: str, **defaults) -> User:  # type: ignore[no-untyped-def]
    # Trailing whitespace is real in this data -- there is a "Vedant " row.
    username = username.strip()
    username = USERNAME_REMAP.get(username, username)
    user = await session.scalar(select(User).where(User.username == username))
    if user is not None:
        return user

    user = User(
        username=username,
        email=defaults.get("email") or f"{username}@migrated.local",
        name=defaults.get("name") or username,
        # Migrated bcrypt hashes verify fine and are upgraded to argon2 on
        # next login. Where no hash exists, set an unusable random one rather
        # than a guessable placeholder.
        hashed_password=defaults.get("hashed_password") or hash_password(_random_secret()),
    )
    session.add(user)
    await session.flush()
    return user


def _random_secret() -> str:
    import secrets

    return secrets.token_urlsafe(32)


async def _existing_keys(session, user_id: int) -> set[tuple]:  # type: ignore[no-untyped-def]
    rows = (
        await session.execute(
            select(Transaction.date, Transaction.description, Transaction.amount).where(
                Transaction.user_id == user_id
            )
        )
    ).all()
    return {(r.date, r.description, r.amount) for r in rows}


async def migrate_yafa_db(path: Path) -> tuple[int, int]:
    """Migrate the interim SQLAlchemy-schema database."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    users_migrated = 0
    txns_migrated = 0

    async with SessionLocal() as session:
        for row in conn.execute("SELECT * FROM users"):
            if row["username"].strip() in SKIP_USERNAMES:
                continue

            user = await _get_or_create_user(
                session,
                row["username"],
                email=row["email"],
                name=row["name"],
                hashed_password=row["hashed_password"],
            )
            users_migrated += 1
            seen = await _existing_keys(session, user.id)

            for txn in conn.execute("SELECT * FROM transactions WHERE user_id = ?", (row["id"],)):
                when = _parse_date(txn["date"])
                if when is None:
                    continue
                amount = Decimal(str(txn["amount"])).quantize(Decimal("0.01"))
                key = (when, txn["description"], amount)
                if key in seen:
                    continue
                seen.add(key)

                session.add(
                    Transaction(
                        user_id=user.id,
                        date=when,
                        description=txn["description"],
                        category=txn["category"] or "Uncategorized",
                        amount=amount,
                        currency="USD",
                        source=TransactionSource.IMPORT,
                    )
                )
                txns_migrated += 1

        await session.commit()

    conn.close()
    return users_migrated, txns_migrated


async def migrate_legacy_db(path: Path) -> tuple[int, int]:
    """Migrate the original flat table.

    The table is named ``users`` but holds transaction rows; the username is
    repeated on every one.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    users_seen: set[str] = set()
    txns_migrated = 0

    async with SessionLocal() as session:
        rows = list(conn.execute("SELECT * FROM users"))
        by_user: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            username = (row["username"] or "").strip()
            if not username or username in SKIP_USERNAMES:
                continue
            by_user.setdefault(username, []).append(row)

        for username, user_rows in by_user.items():
            user = await _get_or_create_user(session, username)
            users_seen.add(username)
            seen = await _existing_keys(session, user.id)

            for row in user_rows:
                when = _parse_date(row["date"])
                if when is None:
                    continue
                try:
                    amount = Decimal(str(row["amount"])).quantize(Decimal("0.01"))
                except Exception:
                    continue

                description = (row["description"] or "").strip() or "(no description)"
                key = (when, description, amount)
                if key in seen:
                    continue
                seen.add(key)

                session.add(
                    Transaction(
                        user_id=user.id,
                        date=when,
                        description=description,
                        category=(row["category"] or "Uncategorized").strip(),
                        amount=amount,
                        currency="USD",
                        source=TransactionSource.IMPORT,
                    )
                )
                txns_migrated += 1

        await session.commit()

    conn.close()
    return len(users_seen), txns_migrated


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yafa-db", type=Path, help="Path to backend/yafa.db")
    parser.add_argument("--legacy-db", type=Path, help="Path to the original database.db")
    args = parser.parse_args()

    if not args.yafa_db and not args.legacy_db:
        parser.error("give at least one of --yafa-db or --legacy-db")

    if args.yafa_db:
        if not args.yafa_db.exists():
            raise SystemExit(f"not found: {args.yafa_db}")
        users, txns = await migrate_yafa_db(args.yafa_db)
        print(f"yafa.db     -> {users} users, {txns} transactions")

    if args.legacy_db:
        if not args.legacy_db.exists():
            raise SystemExit(f"not found: {args.legacy_db}")
        users, txns = await migrate_legacy_db(args.legacy_db)
        print(f"database.db -> {users} users, {txns} transactions")

    print("\nVerify with:")
    print(
        '  psql -c "SELECT username, COUNT(*) FROM users u '
        'JOIN transactions t ON t.user_id=u.id GROUP BY username;"'
    )


if __name__ == "__main__":
    asyncio.run(main())
