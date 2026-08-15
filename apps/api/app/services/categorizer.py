"""Semantic expense categorization: BERT sentence embeddings + Qdrant kNN.

An incoming description is embedded with a BERT bi-encoder
(``all-MiniLM-L6-v2``, a 6-layer distilled BERT producing 384-dim vectors) and
matched by cosine similarity against labeled exemplar phrases held in Qdrant.
The top-k neighbours vote, weighted by similarity.

Two things changed from the previous implementation:

* **Qdrant is a service, not an embedded client.** Local mode took an
  exclusive lock on a directory, so reseeding the collection meant stopping
  the API. Talking to a real Qdrant over HTTP removes that constraint.
* **Everything is async.** The embedding call is CPU-bound and releases the
  GIL inside torch, but not reliably enough to block the event loop on, so it
  runs in a worker thread.
"""

from collections import defaultdict

import anyio
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer

from ..core.config import get_settings
from ..core.logging import get_logger
from ..schemas.voice import CategoryScore

settings = get_settings()
log = get_logger(__name__)

# Loading the model costs seconds and ~80MB, so it happens once per process.
# Inference is read-only, which makes sharing one instance across concurrently
# served requests safe.
_model: SentenceTransformer | None = None
_client: AsyncQdrantClient | None = None

# Payload key marking where an exemplar came from. Corrections learned from
# real users must stay distinguishable from the seed corpus, or the next
# evaluation silently trains and tests on the same rows.
SOURCE_SEED = "seed"
SOURCE_USER_CORRECTION = "user_correction"


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        log.info("categorizer.loading_model", model=settings.embedding_model_name)
        _model = SentenceTransformer(settings.embedding_model_name)
    return _model


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=10,
        )
    return _client


async def warm_up() -> None:
    """Load the model and ensure the collection exists. Called from lifespan."""
    await anyio.to_thread.run_sync(get_model)
    await ensure_collection()


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def ping() -> bool:
    try:
        await get_client().get_collections()
        return True
    except Exception:
        return False


def vector_size() -> int:
    return get_model().get_sentence_embedding_dimension() or 384


# --------------------------------------------------------------------------
# embedding
# --------------------------------------------------------------------------


async def embed(text: str) -> list[float]:
    def _encode() -> list[float]:
        vector = get_model().encode(text, normalize_embeddings=True)
        return vector.tolist()  # type: ignore[no-any-return]

    return await anyio.to_thread.run_sync(_encode)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    def _encode() -> list[list[float]]:
        vectors = get_model().encode(
            texts, normalize_embeddings=True, show_progress_bar=False, batch_size=64
        )
        return vectors.tolist()  # type: ignore[no-any-return]

    return await anyio.to_thread.run_sync(_encode)


# --------------------------------------------------------------------------
# collection management
# --------------------------------------------------------------------------


async def ensure_collection(collection_name: str | None = None) -> None:
    client = get_client()
    name = collection_name or settings.qdrant_collection
    if not await client.collection_exists(name):
        log.info("categorizer.creating_collection", collection=name)
        await client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(
                size=vector_size(), distance=qmodels.Distance.COSINE
            ),
        )


# --------------------------------------------------------------------------
# inference
# --------------------------------------------------------------------------


async def categorize(
    text: str,
    *,
    collection_name: str | None = None,
    k: int | None = None,
) -> tuple[str | None, float, list[CategoryScore]]:
    """Return ``(category, confidence, alternatives)`` for a description.

    ``category`` is None when the nearest neighbour's cosine similarity falls
    below the configured threshold -- the caller surfaces that as
    "Uncategorized" and asks the user to pick, which is a better outcome than
    confidently guessing from a distant match.

    ``confidence`` is the winning label's share of total similarity mass
    across the k neighbours, so it reflects how *decisive* the vote was, not
    just how close the single best match happened to land.
    """
    client = get_client()
    name = collection_name or settings.qdrant_collection
    limit = k or settings.categorize_top_k

    if not text.strip():
        return None, 0.0, []

    vector = await embed(text)
    response = await client.query_points(collection_name=name, query=vector, limit=limit)
    hits = response.points
    if not hits:
        return None, 0.0, []

    top_similarity = hits[0].score
    if top_similarity < settings.categorize_confidence_threshold:
        return None, float(top_similarity), []

    scores: dict[str, float] = defaultdict(float)
    for hit in hits:
        if hit.payload and (category := hit.payload.get("category")):
            scores[str(category)] += hit.score

    if not scores:
        return None, float(top_similarity), []

    total = sum(scores.values())
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_category, best_score = ranked[0]

    # Runners-up let the UI offer one-tap corrections instead of a dropdown
    # of every category.
    alternatives = [
        CategoryScore(category=category, confidence=score / total)
        for category, score in ranked[1:4]
    ]
    return best_category, best_score / total, alternatives


# --------------------------------------------------------------------------
# active learning
# --------------------------------------------------------------------------


def exemplar_id(text: str, category: str) -> str:
    """Stable UUID-shaped point ID derived from content.

    Shared with ``tools/seed_qdrant.py`` so the seed corpus and live corrections
    use one scheme and a correction that restates a seeded pair overwrites it
    rather than adding a duplicate vote.
    """
    import hashlib

    digest = hashlib.sha1(f"{text}|{category}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


async def add_exemplar(
    text: str,
    category: str,
    *,
    source: str = SOURCE_USER_CORRECTION,
    collection_name: str | None = None,
) -> None:
    """Index a user-confirmed (text, category) pair as a new exemplar.

    Tagged with ``source`` so evaluation can exclude user data and keep
    measuring against the fixed seed corpus.

    The point ID is derived from the content, matching ``tools/seed_qdrant.py``.
    A random ID would let the same correction accumulate one point per save --
    confirm "coffee" as Food five times and it casts five votes instead of one,
    quietly biasing the kNN toward whatever the user happens to correct most
    often. Deterministic IDs make a repeat correction overwrite itself.
    """
    client = get_client()
    name = collection_name or settings.qdrant_collection
    vector = await embed(text)

    await client.upsert(
        collection_name=name,
        points=[
            qmodels.PointStruct(
                id=exemplar_id(text, category),
                vector=vector,
                payload={"text": text, "category": category, "source": source},
            )
        ],
    )
    log.info("categorizer.exemplar_added", category=category, source=source)
