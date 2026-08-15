"""Index the labeled training corpus into Qdrant.

    uv run python -m tools.seed_qdrant [--recreate]

Unlike the previous embedded-Qdrant version, this can run while the API is
serving traffic -- the collection is a service, not a locked directory.

``--recreate`` drops and rebuilds the collection. Note that this also discards
any exemplars learned from user corrections, since those live in the same
collection tagged ``source=user_correction``. Without the flag, seed rows are
upserted by deterministic ID and corrections are left untouched.
"""

import argparse
import asyncio
from pathlib import Path

import pandas as pd
from qdrant_client.http import models as qmodels

from app.core.config import DATA_DIR
from app.services import categorizer

BATCH_SIZE = 256


def _point_id(text: str, category: str) -> str:
    """Stable UUID-shaped ID derived from content.

    Re-running the seed then overwrites the same points instead of appending
    duplicates, which would quietly bias the kNN vote toward whatever was
    seeded most often. Delegates to the categorizer so the seed corpus and
    user corrections share one scheme.
    """
    return categorizer.exemplar_id(text, category)


async def seed(csv_path: Path, *, recreate: bool = False) -> int:
    df = pd.read_csv(csv_path, keep_default_na=False)
    if not {"text", "category"}.issubset(df.columns):
        raise SystemExit(f"{csv_path} must have 'text' and 'category' columns")

    df = df[(df["text"].str.strip() != "") & (df["category"].str.strip() != "")]
    df = df.drop_duplicates(subset=["text", "category"])

    client = categorizer.get_client()
    collection = categorizer.settings.qdrant_collection

    if recreate and await client.collection_exists(collection):
        print(f"Dropping existing collection {collection!r} (including user corrections)")
        await client.delete_collection(collection)

    await categorizer.ensure_collection()

    texts = df["text"].tolist()
    categories = df["category"].tolist()
    print(f"Embedding {len(texts)} exemplars with {categorizer.settings.embedding_model_name}...")

    total = 0
    for start in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[start : start + BATCH_SIZE]
        batch_categories = categories[start : start + BATCH_SIZE]
        vectors = await categorizer.embed_batch(batch_texts)

        await client.upsert(
            collection_name=collection,
            points=[
                qmodels.PointStruct(
                    id=_point_id(text, category),
                    vector=vector,
                    payload={
                        "text": text,
                        "category": category,
                        "source": categorizer.SOURCE_SEED,
                    },
                )
                for text, category, vector in zip(
                    batch_texts, batch_categories, vectors, strict=True
                )
            ],
        )
        total += len(batch_texts)
        print(f"  {total}/{len(texts)}")

    info = await client.get_collection(collection)
    print(f"Done. Collection {collection!r} now holds {info.points_count} points.")
    return total


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=DATA_DIR / "training_data.csv",
        help="Labeled corpus with text,category columns",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop the collection first (discards user corrections too)",
    )
    args = parser.parse_args()

    try:
        await seed(args.csv, recreate=args.recreate)
    finally:
        await categorizer.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
