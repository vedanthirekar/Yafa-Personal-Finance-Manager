"""Offline evaluation of the BERT + Qdrant categorizer.

    uv run python -m ml.eval_categorizer

Stratified 80/20 split of the labeled corpus, indexed into a throwaway
collection kept separate from the production one, then scored on the held-out
split. Writes ``data/eval_report.json``.

Two things this deliberately does NOT do:

* It does not touch the production collection, so running it never disturbs
  a live API or pollutes real data with evaluation rows.
* It does not include user-correction exemplars. Those are real labels, but
  mixing them in would make the number drift for reasons unrelated to the
  model and break comparability across runs.

The accuracy this reports is the honest measured figure. Improving it is
tracked separately -- see the appendix in the revamp plan for the diagnosis
(keyword collisions across categories, and a starved tail in the corpus).
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


async def run_eval() -> dict[str, Any]:
    df = pd.read_csv(DATA_DIR / "training_data.csv", keep_default_na=False)
    train_df, test_df = train_test_split(
        df, test_size=TEST_SIZE, stratify=df["category"], random_state=RANDOM_STATE
    )

    print(f"Train {len(train_df)} / test {len(test_df)}")
    await _index_train_split(train_df)

    y_true: list[str] = []
    y_pred: list[str] = []
    for text, true_category in zip(test_df["text"], test_df["category"], strict=True):
        predicted, _confidence, _alts = await categorizer.categorize(
            text, collection_name=EVAL_COLLECTION
        )
        y_true.append(true_category)
        # A below-threshold result is a real outcome, not a missing value --
        # scoring it as its own class keeps the accuracy honest rather than
        # quietly dropping the hard cases.
        y_pred.append(predicted or "Uncategorized")

    accuracy = accuracy_score(y_true, y_pred)
    report = classification_report(y_true, y_pred, zero_division=0, output_dict=True)
    labels = sorted(set(y_true) | set(y_pred))

    print(f"\nAccuracy: {accuracy:.4f}\n")
    print(classification_report(y_true, y_pred, zero_division=0))

    result = {
        "accuracy": accuracy,
        "train_size": len(train_df),
        "test_size": len(test_df),
        "model": categorizer.settings.embedding_model_name,
        "model_version": categorizer.settings.embedding_model_version,
        "top_k": categorizer.settings.categorize_top_k,
        "confidence_threshold": categorizer.settings.categorize_confidence_threshold,
        "report": report,
        # Kept because the interesting failures are confusions between
        # specific pairs, which per-class F1 alone doesn't show.
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        },
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
