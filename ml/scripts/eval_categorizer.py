"""Real train/test evaluation of the BERT+Qdrant categorizer: stratified
80/20 split of data/training_data.csv, index the train split into a
throwaway Qdrant collection (kept separate from the production collection
seed_qdrant.py fills), run categorize() over the held-out test split, and
report accuracy + per-category precision/recall/F1.

This produces the genuine measured number that replaces the resume's
placeholder "92%" -- whatever it actually comes out to.

Run from the repo root:
    python -m backend.scripts.eval_categorizer
"""

import json
from pathlib import Path

import pandas as pd
from qdrant_client.http import models as qmodels
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from backend.app.services import categorizer

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
EVAL_QDRANT_PATH = str(DATA_DIR / "qdrant_eval_tmp")
EVAL_COLLECTION = "expense_categories_eval"


def run_eval() -> dict:
    df = pd.read_csv(DATA_DIR / "training_data.csv", keep_default_na=False)
    train_df, test_df = train_test_split(
        df, test_size=0.2, stratify=df["category"], random_state=42
    )

    eval_client = categorizer.get_qdrant_client(path=EVAL_QDRANT_PATH)
    if eval_client.collection_exists(EVAL_COLLECTION):
        eval_client.delete_collection(EVAL_COLLECTION)
    categorizer.ensure_collection(eval_client, EVAL_COLLECTION)

    vectors = categorizer.embed_batch(train_df["text"].tolist())
    points = [
        qmodels.PointStruct(id=i, vector=vector, payload={"text": text, "category": category})
        for i, (vector, text, category) in enumerate(
            zip(vectors, train_df["text"], train_df["category"])
        )
    ]
    eval_client.upsert(collection_name=EVAL_COLLECTION, points=points)

    y_true, y_pred = [], []
    for text, true_category in zip(test_df["text"], test_df["category"]):
        predicted, _ = categorizer.categorize(
            text, client=eval_client, collection_name=EVAL_COLLECTION
        )
        y_true.append(true_category)
        y_pred.append(predicted or "Uncategorized")

    accuracy = accuracy_score(y_true, y_pred)
    report_text = classification_report(y_true, y_pred, zero_division=0)
    report_dict = classification_report(y_true, y_pred, zero_division=0, output_dict=True)

    print(f"Train size: {len(train_df)}, Test size: {len(test_df)}")
    print(f"Accuracy: {accuracy:.4f}")
    print(report_text)

    result = {
        "accuracy": accuracy,
        "train_size": len(train_df),
        "test_size": len(test_df),
        "report": report_dict,
    }
    out_path = DATA_DIR / "eval_report.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote eval report to {out_path}")
    return result


if __name__ == "__main__":
    run_eval()
