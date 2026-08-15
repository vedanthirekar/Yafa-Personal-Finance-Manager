"""Generate the demo account's transaction pool from ``tools/us_expense_spec.py``.

Run from the repo root:
    uv run python -m tools.build_demo_data

Writes ``data/demo-transactions.csv`` (description, category, amount), which
``app.services.demo_seed`` samples to fill 18 months of history.

This replaces ``data/sample-data.csv``, which was one person's anonymised
Indian expense ledger. Two things were wrong with using it here:

* **The descriptions were placeholder soup.** 70% of its Transportation rows
  read like "2 Current Residence to Place 0" -- an artifact of whoever
  anonymised it, shown to every demo visitor.
* **The amounts were rupees rendered as dollars.** Median "Money transfer" was
  10,000, so the demo displayed $10,000 transfers and $1,000 investments
  against a $600 monthly food budget.

It also only covered 7 of the 10 categories -- no Household, Apparel, or
Entertainment rows existed at all, so the demo's spending breakdown was missing
three slices and two of the seeded budgets could never show progress.

``WEIGHTS`` below is transaction *frequency*, not spend. People buy coffee far
more often than they book flights, and since the seeder samples this pool
uniformly, these weights are what make the demo's charts look like a real
month rather than a flat spread across categories.
"""

import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .us_expense_spec import SPEC, CategorySpec, Group

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

POOL_SIZE = 900
SEED = 20260815

# Relative frequency of a *transaction* in each category, not dollars spent.
WEIGHTS = {
    "Food": 30,
    "Transportation": 16,
    "Household": 10,
    "Social Life": 9,
    "Subscription": 8,
    "Entertainment": 7,
    "Health": 6,
    "Apparel": 5,
    "Education": 4,
    "Tourism": 3,
}


def _amount(spec: CategorySpec, group: Group | None, rng: random.Random) -> float:
    """Pick a plausible amount, occasionally a big-ticket one.

    Group ranges win over the category default where they exist: a coffee and a
    grocery haul are both Food, and seeding $80 lattes would look absurd.
    """
    if spec.big_ticket and rng.random() < spec.big_ticket_rate:
        low, high = spec.big_ticket
    elif group is not None and group.amount_range is not None:
        low, high = group.amount_range
    else:
        low, high = spec.amount_range

    # Skew toward the low end -- real spending is many small and a few large,
    # not a uniform smear across the range.
    value = low + (high - low) * (rng.random() ** 1.7)
    return round(value, 2)


def _description(group: Group, rng: random.Random) -> str:
    """A description in the shape a bank statement or a person would write."""
    merchant = rng.choice(group.merchants)
    item = rng.choice(group.items)
    return rng.choices(
        [merchant, f"{merchant} {item}", f"{item} at {merchant}", item],
        weights=[34, 38, 16, 12],
    )[0]


def build() -> pd.DataFrame:
    rng = random.Random(SEED)
    total_weight = sum(WEIGHTS.values())
    rows: list[dict[str, object]] = []

    for category, spec in SPEC.items():
        quota = round(POOL_SIZE * WEIGHTS[category] / total_weight)
        seen: set[str] = set()
        attempts = 0

        while len(seen) < quota and attempts < quota * 60:
            attempts += 1
            # Standalone phrases ("electric bill", "copay") are a real slice of
            # how people describe spending, so they get a share of the pool
            # rather than being training-only.
            if spec.standalone and rng.random() < 0.22:
                description = rng.choice(spec.standalone)
                group = None
            else:
                group = rng.choice(spec.groups)
                description = _description(group, rng)

            if description in seen:
                continue
            seen.add(description)
            rows.append(
                {
                    "description": description,
                    "category": category,
                    "amount": _amount(spec, group, rng),
                }
            )

    df = pd.DataFrame(rows).drop_duplicates(subset=["description"]).reset_index(drop=True)

    counts = Counter(df["category"])
    print("Demo pool composition (drives the demo's category breakdown):")
    for category in SPEC:
        n = counts.get(category, 0)
        median = df[df["category"] == category]["amount"].median()
        print(f"  {category:16s} {n:4d} rows   median ${median:7.2f}")

    out_path = DATA_DIR / "demo-transactions.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} rows to {out_path}")
    return df


if __name__ == "__main__":
    build()
