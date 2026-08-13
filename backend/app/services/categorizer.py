from collections import defaultdict

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer

from ..config import settings

# Module-level singletons: the BERT model (~80MB) and the Qdrant client are
# each created once per process and reused across every request, instead of
# being re-instantiated per call. `warm_up()` is invoked from the FastAPI
# lifespan handler so the first real request isn't the one paying the load
# cost; both are read-only at inference time so sharing them across
# concurrently-served requests is safe.
_model: SentenceTransformer | None = None
_client: QdrantClient | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model_name)
    return _model


def get_qdrant_client(path: str | None = None) -> QdrantClient:
    global _client
    if path is not None:
        return QdrantClient(path=path)
    if _client is None:
        _client = QdrantClient(path=settings.qdrant_path)
    return _client


def warm_up() -> None:
    get_model()
    get_qdrant_client()


def embed(text: str) -> list[float]:
    vector = get_model().encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    vectors = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def vector_size() -> int:
    return get_model().get_embedding_dimension()


def ensure_collection(client: QdrantClient, collection_name: str) -> None:
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size(), distance=qmodels.Distance.COSINE),
        )


def categorize(
    text: str,
    client: QdrantClient | None = None,
    collection_name: str | None = None,
    k: int | None = None,
) -> tuple[str | None, float]:
    """Embed `text` and semantically match it against labeled training
    phrases stored in Qdrant via k-NN, similarity-weighted majority vote.

    Returns (category, confidence). category is None (Uncategorized) when the
    single closest match's similarity is below the confidence threshold, so
    the UI's existing "couldn't detect a category, select manually" fallback
    still triggers.
    """
    client = client or get_qdrant_client()
    collection_name = collection_name or settings.qdrant_collection
    k = k or settings.categorize_top_k

    vector = embed(text)
    hits = client.query_points(collection_name=collection_name, query=vector, limit=k).points
    if not hits:
        return None, 0.0

    top_similarity = hits[0].score
    if top_similarity < settings.categorize_confidence_threshold:
        return None, top_similarity

    scores: dict[str, float] = defaultdict(float)
    for hit in hits:
        scores[hit.payload["category"]] += hit.score

    best_category = max(scores, key=scores.get)
    confidence = scores[best_category] / sum(scores.values())
    return best_category, confidence
