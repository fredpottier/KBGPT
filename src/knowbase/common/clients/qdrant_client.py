from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from knowbase.config.settings import get_settings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    if settings.qdrant_api_key:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return QdrantClient(url=settings.qdrant_url)


def ensure_qdrant_collection(
    collection_name: str,
    vector_size: int,
    distance: Distance = Distance.COSINE,
) -> None:
    client = get_qdrant_client()
    if client.collection_exists(collection_name):
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=distance),
    )


def ensure_qa_collection(vector_size: int) -> None:
    """Initialise la collection dédiée aux Q/A RFP."""
    settings = get_settings()
    ensure_qdrant_collection(
        collection_name=settings.qdrant_qa_collection,
        vector_size=vector_size,
        distance=Distance.COSINE,
    )
