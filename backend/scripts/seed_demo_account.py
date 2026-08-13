"""Idempotent demo-account seeding: creates the fixed `demo` user if it
doesn't already exist, then always wipes and reseeds its transactions with a
fresh realistic 12-month dataset. Safe to rerun any time to manually reset
the demo account to a pristine state (the same reset-and-seed logic also
runs automatically on every /auth/demo-login call).

Run from the repo root:
    python -m backend.scripts.seed_demo_account
"""

from backend.app.database import Base, SessionLocal, engine
from backend.app.services import demo_seed


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = demo_seed.get_or_create_demo_user(db)
        count = demo_seed.reset_and_seed(db, user)
        print(f"Seeded {count} transactions for demo user '{user.username}'")
    finally:
        db.close()


if __name__ == "__main__":
    main()
