"""Build the categorizer's exemplar corpus from ``tools/us_expense_spec.py``.

Run from the repo root:
    uv run python -m tools.build_training_data

What changed, and why
---------------------
This used to expand ``data/categories.csv`` keywords through four fixed
templates ("spent money on {kw}") and append ``data/sample-data.csv``, an
anonymised Indian expense ledger. Both sources are now unused -- the files are
left in place, but nothing reads them. See ``tools/us_expense_spec.py`` for the
full diagnosis; the short version is that the old exemplars didn't resemble the
queries the categorizer actually receives.

The generator targets the shape of a real query. ``pipeline.process_transcript``
categorizes on ``"{description} {merchant}"``, so the most heavily weighted
pattern here is exactly that join -- "coffee starbucks". Bare merchants and
bare items are next, because plenty of real descriptions are one or two words.

Deliberately *not* a single template applied to everything: the previous
corpus put 65% of its rows behind one of four stems, and for short strings a
shared stem is a large fraction of the sentence embedding. Every pattern below
either adds no stem at all or a different one, so what distinguishes two
exemplars is the merchant and the item rather than the scaffolding.
"""

import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .us_expense_spec import SPEC, CategorySpec

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Exemplars per category. Equal by construction -- the old corpus ranged from
# 701 (Social Life) to 60 (Subscription), and under a similarity-weighted kNN
# vote a sparse class loses ties it should win. Subscription's 0.50 recall was
# mostly this.
PER_CATEGORY = 800

SEED = 20260815


def _candidates(spec: CategorySpec) -> list[tuple[str, int]]:
    """All exemplar strings for one category, each with a sampling weight.

    Weights encode how common that phrasing is in real input, not how many
    strings the pattern can produce -- otherwise the cross-product patterns
    would drown out the bare forms that short descriptions actually look like.
    """
    out: list[tuple[str, int]] = []

    for group in spec.groups:
        for merchant in group.merchants:
            m = merchant.lower()
            out.append((m, 6))
            for item in group.items:
                out.append((f"{item} {m}", 8))  # the pipeline's own join order
                out.append((f"{m} {item}", 5))
                out.append((f"{item} at {m}", 4))
        for item in group.items:
            out.append((item, 6))

    for item in spec.standalone:
        out.append((item, 9))  # "copay", "electric bill" -- already query-shaped

    # Bills pair with the bill, never with merchandise.
    for biller in spec.billers:
        b = biller.lower()
        out.append((b, 6))
        out.append((f"{b} bill", 8))
        for item in spec.standalone:
            out.append((f"{item} {b}", 5))

    return out


def build_category(name: str, spec: CategorySpec, rng: random.Random) -> list[str]:
    candidates = _candidates(spec)
    pool = {text for text, _ in candidates}

    if len(pool) <= PER_CATEGORY:
        # Small vocabulary -- take everything rather than sampling a subset.
        return sorted(pool)

    texts = [t for t, _ in candidates]
    weights = [w for _, w in candidates]

    chosen: set[str] = set()
    # Weighted sampling without replacement. Draw until the quota fills; the
    # pool is far larger than the quota so this converges quickly.
    while len(chosen) < PER_CATEGORY:
        for pick in rng.choices(texts, weights=weights, k=PER_CATEGORY):
            chosen.add(pick)
            if len(chosen) >= PER_CATEGORY:
                break

    return sorted(chosen)


def build() -> pd.DataFrame:
    rng = random.Random(SEED)
    rows: list[dict[str, str]] = []

    for name, spec in SPEC.items():
        for text in build_category(name, spec, rng):
            rows.append({"text": text, "category": name})

    df = pd.DataFrame(rows)
    df["text"] = df["text"].astype(str).str.strip()
    df = df[df["text"] != ""]
    df = df.drop_duplicates(subset=["text", "category"]).reset_index(drop=True)

    # A string carrying two different labels is unanswerable by construction --
    # the old corpus had 127 such keywords and no model can beat that. Drop
    # every side of a collision and say so, rather than letting it sit.
    dupes = df[df.duplicated(subset=["text"], keep=False)]
    if not dupes.empty:
        print(f"Dropping {len(dupes)} rows across {dupes['text'].nunique()} colliding texts:")
        for text, group in list(dupes.groupby("text"))[:10]:
            print(f"  {text!r}: {sorted(group['category'])}")
        df = df[~df["text"].isin(dupes["text"])]

    counts = Counter(df["category"])
    print("\nPer-category exemplar counts:")
    for cat in SPEC:
        print(f"  {cat:20s} {counts.get(cat, 0)}")

    out_path = DATA_DIR / "training_data.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} rows to {out_path}")
    return df


if __name__ == "__main__":
    build()
