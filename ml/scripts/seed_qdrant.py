"""Embed data/training_data.csv and upsert it into the production Qdrant
collection used by the running API.

Run from the repo root (after build_training_data.py has produced
data/training_data.csv), with the API server stopped -- embedded/local-mode
Qdrant can only be opened by one process at a time:
    python -m backend.scripts.seed_qdrant
"""

from pathlib import Path

import pandas as pd
from qdrant_client.http import models as qmodels

from backend.app import config
from backend.app.services import categorizer

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def seed() -> None:
    df = pd.read_csv(DATA_DIR / "training_data.csv", keep_default_na=False)

    client = categorizer.get_qdrant_client()
    # Delete-then-recreate rather than relying on row-index alignment staying
    # stable across reruns -- guarantees a clean reseed whenever
    # training_data.csv's content changes.
    if client.collection_exists(config.settings.qdrant_collection):
        client.delete_collection(config.settings.qdrant_collection)
    categorizer.ensure_collection(client, config.settings.qdrant_collection)

    vectors = categorizer.embed_batch(df["text"].tolist())
    points = [
        qmodels.PointStruct(
            id=i,
            vector=vector,
            payload={"text": text, "category": category, "source": "training_data.csv"},
        )
        for i, (vector, text, category) in enumerate(zip(vectors, df["text"], df["category"]))
    ]
    client.upsert(collection_name=config.settings.qdrant_collection, points=points)
    print(f"Seeded {len(points)} points into '{config.settings.qdrant_collection}'")


if __name__ == "__main__":
    seed()
