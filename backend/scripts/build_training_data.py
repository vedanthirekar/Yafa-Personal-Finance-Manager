"""Synthesize a labeled (text, category) training set for the BERT+Qdrant
categorizer out of the repo's existing data/categories.csv (19 fine-grained
keyword categories) and data/sample-data.csv (already-labeled expense
descriptions), remapped down to the 10 canonical categories used across the
app's UI.

Run from the repo root:
    python -m backend.scripts.build_training_data
"""

import random
from collections import Counter
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Judgment calls, documented here rather than hidden: `gift` reads as a social
# occasion, so it folds into Social Life; `apparel` reads as a household
# shopping expense, so it folds into Household alongside `grooming`.
CATEGORY_REMAP = {
    "education": "Education",
    "self-development": "Education",
    "documents": "Education",
    "culture": "Social Life",
    "entertainment": "Social Life",
    "festivals": "Social Life",
    "family": "Social Life",
    "social life": "Social Life",
    "gift": "Social Life",
    "household": "Household",
    "grooming": "Household",
    "apparel": "Household",
    "transportation": "Transportation",
    "food": "Food",
    "money transfer": "Money transfer",
    "investment": "Investment",
    "tourism": "Tourism",
    "health": "Health",
    "subscription": "Subscription",
}

CANONICAL_CATEGORIES = [
    "Education",
    "Social Life",
    "Transportation",
    "Food",
    "Household",
    "Money transfer",
    "Investment",
    "Tourism",
    "Health",
    "Subscription",
]


# data/categories.csv only has bare keywords ("art", "music"). Real inference
# input is transcript-derived natural phrases, so wrap each keyword into a
# short templated sentence -- this is a much better style/length match for
# what the categorizer actually sees at runtime. Fixed seed keeps the output
# reproducible across reruns.
_KEYWORD_TEMPLATES = [
    "spent money on {kw}",
    "paid for {kw}",
    "{kw} expense",
    "bought {kw}",
]


def load_categories_csv() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "categories.csv")
    df["category"] = df["category"].str.strip().str.lower().map(CATEGORY_REMAP)
    df = df.dropna(subset=["category"])
    df = df.rename(columns={"words": "keyword"})

    rng = random.Random(42)
    df["text"] = df["keyword"].apply(
        lambda kw: rng.choice(_KEYWORD_TEMPLATES).format(kw=kw)
    )
    return df[["text", "category"]]


def load_sample_data_csv() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "sample-data.csv")
    df = df.rename(columns={"Description": "text", "Category": "category"})
    df["category"] = df["category"].replace({"Family": "Social Life"})
    df = df[df["category"].isin(CANONICAL_CATEGORIES)]
    return df[["text", "category"]]


def build() -> pd.DataFrame:
    combined = pd.concat(
        [load_categories_csv(), load_sample_data_csv()], ignore_index=True
    )
    # Drop missing text *before* stringifying -- otherwise a real NaN becomes
    # the literal string "nan", which then round-trips back into a float NaN
    # the next time this CSV is read (pandas' default na_values includes "nan"),
    # crashing the embedding step downstream.
    combined = combined.dropna(subset=["text"])
    combined["text"] = combined["text"].astype(str).str.strip()
    combined = combined[(combined["text"] != "") & (combined["text"].str.lower() != "nan")]
    combined = combined.drop_duplicates(subset=["text", "category"]).reset_index(drop=True)

    counts = Counter(combined["category"])
    print("Per-category training example counts:")
    for cat in CANONICAL_CATEGORIES:
        print(f"  {cat:20s} {counts.get(cat, 0)}")
    missing = [c for c in CANONICAL_CATEGORIES if counts.get(c, 0) == 0]
    if missing:
        print(f"WARNING: no training examples for: {missing}")

    out_path = DATA_DIR / "training_data.csv"
    combined.to_csv(out_path, index=False)
    print(f"Wrote {len(combined)} rows to {out_path}")
    return combined


if __name__ == "__main__":
    build()
