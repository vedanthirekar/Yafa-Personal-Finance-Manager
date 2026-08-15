"""Offline evaluation of the BERT + Qdrant categorizer.

    uv run python -m ml.eval_categorizer

Stratified 80/20 split of the labeled corpus, indexed into a throwaway
collection kept separate from the production one, then scored on the held-out
split. Writes ``data/eval_report.json``.

Two numbers are reported, and the second is the one that matters:

* **held_out** -- a stratified 80/20 split of the generated corpus. Both sides
  come from the same generator, so this measures internal consistency only. It
  will always look good and should be read as a floor, not an achievement.
* **probes** -- ``data/eval_probes.csv``, hand-written phrases using merchants
  and wordings the corpus has never seen ("grabbed a sandwich downtown",
  "uber back from the bar"). Nothing here was generated from
  ``ml/us_expense_spec.py``, so this is the number that estimates real-world
  behaviour.

The old version reported only the first kind, against a corpus where 65% of
rows were four templates over a keyword list -- so the test split was drawn
from the same templates as the training split and the figure flattered itself.
Keeping both makes the gap between them visible, and that gap is the useful
diagnostic: when it widens, the corpus is drifting away from real input.

Two things this deliberately does NOT do:

* It does not touch the production collection, so running it never disturbs
  a live API or pollutes real data with evaluation rows.
* It does not include user-correction exemplars. Those are real labels, but
  mixing them in would make the number drift for reasons unrelated to the
  model and break comparability across runs.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd
from qdrant_client.http import models as qmodels
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from app.core.config import DATA_DIR
from app.services import categorizer

EVAL_COLLECTION = "expense_categories_eval"
RANDOM_STATE = 42
TEST_SIZE = 0.2
BATCH_SIZE = 256


async def _index_train_split(train_df: pd.DataFrame) -> None:
    client = categorizer.get_client()

    if await client.collection_exists(EVAL_COLLECTION):
        await client.delete_collection(EVAL_COLLECTION)
    await categorizer.ensure_collection(EVAL_COLLECTION)

    texts = train_df["text"].tolist()
    categories = train_df["category"].tolist()

    for start in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[start : start + BATCH_SIZE]
        batch_categories = categories[start : start + BATCH_SIZE]
        vectors = await categorizer.embed_batch(batch_texts)
        await client.upsert(
            collection_name=EVAL_COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=start + offset,
                    vector=vector,
                    payload={"text": text, "category": category},
                )
                for offset, (text, category, vector) in enumerate(
                    zip(batch_texts, batch_categories, vectors, strict=True)
                )
            ],
        )


async def _score(df: pd.DataFrame, label: str) -> dict[str, Any]:
    """Categorize every row of ``df`` against the eval collection and score it."""
    y_true: list[str] = []
    y_pred: list[str] = []
    for text, true_category in zip(df["text"], df["category"], strict=True):
        predicted, _confidence, _alts = await categorizer.categorize(
            text, collection_name=EVAL_COLLECTION
        )
        y_true.append(true_category)
        # A below-threshold result is a real outcome, not a missing value --
        # scoring it as its own class keeps the accuracy honest rather than
        # quietly dropping the hard cases.
        y_pred.append(predicted or "Uncategorized")

    accuracy = accuracy_score(y_true, y_pred)
    labels = sorted(set(y_true) | set(y_pred))

    print(f"\n===== {label}: accuracy {accuracy:.4f} (n={len(y_true)}) =====")
    print(classification_report(y_true, y_pred, zero_division=0))

    return {
        "accuracy": accuracy,
        "n": len(y_true),
        "report": classification_report(y_true, y_pred, zero_division=0, output_dict=True),
        # Kept because the interesting failures are confusions between
        # specific pairs, which per-class F1 alone doesn't show.
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        },
        "misses": [
            {"text": t, "expected": a, "predicted": p}
            for t, a, p in zip(df["text"], y_true, y_pred, strict=True)
            if a != p
        ],
    }


async def run_eval() -> dict[str, Any]:
    df = pd.read_csv(DATA_DIR / "training_data.csv", keep_default_na=False)
    train_df, test_df = train_test_split(
        df, test_size=TEST_SIZE, stratify=df["category"], random_state=RANDOM_STATE
    )

    print(f"Train {len(train_df)} / test {len(test_df)}")
    await _index_train_split(train_df)

    held_out = await _score(test_df, "held-out split (same generator as training)")

    probe_path = DATA_DIR / "eval_probes.csv"
    probes: dict[str, Any] | None = None
    if probe_path.exists():
        probe_df = pd.read_csv(probe_path, keep_default_na=False)
        probes = await _score(probe_df, "hand-written probes (unseen wording)")
    else:
        print(f"\nNo probe set at {probe_path} -- skipping the out-of-distribution score.")

    result = {
        # The probe number is the headline: it is the one measured on text the
        # corpus generator never produced.
        "accuracy": probes["accuracy"] if probes else held_out["accuracy"],
        "accuracy_basis": "probes" if probes else "held_out",
        "train_size": len(train_df),
        "test_size": len(test_df),
        "model": categorizer.settings.embedding_model_name,
        "model_version": categorizer.settings.embedding_model_version,
        "top_k": categorizer.settings.categorize_top_k,
        "confidence_threshold": categorizer.settings.categorize_confidence_threshold,
        "held_out": held_out,
        "probes": probes,
    }

    out_path = Path(DATA_DIR / "eval_report.json")
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {out_path}")
    return result


async def main() -> None:
    try:
        await run_eval()
    finally:
        client = categorizer.get_client()
        if await client.collection_exists(EVAL_COLLECTION):
            await client.delete_collection(EVAL_COLLECTION)
        await categorizer.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
