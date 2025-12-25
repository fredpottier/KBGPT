"""Shared clients and heavy resource factories used across the project."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from sentence_transformers import SentenceTransformer


def get_project_root() -> Path:
    """Return the absolute project root (two levels above this module)."""
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()
MODELS_DIR = PROJECT_ROOT / "models"
os.environ.setdefault("HF_HOME", str(MODELS_DIR))


class CustomHTTPClient(httpx.Client):
    """HTTP client that never trusts proxy settings from the environment."""

    def __init__(self, *args, **kwargs):
        kwargs.pop("proxies", None)
        super().__init__(*args, **kwargs, trust_env=False)


@lru_cache(maxsize=1)
def get_http_client() -> httpx.Client:
    """Return a shared HTTP client instance for OpenAI and other APIs."""
    return CustomHTTPClient()


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Return a lazily instantiated OpenAI client with the shared HTTP client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=api_key, http_client=get_http_client())


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Return a lazily instantiated Qdrant client."""
    url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    api_key = os.getenv("QDRANT_API_KEY")
    if api_key:
        return QdrantClient(url=url, api_key=api_key)
    return QdrantClient(url=url)


def get_sentence_transformer(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    cache_folder: Optional[str] = None,
) -> SentenceTransformer:
    """
    DEPRECATED: Redirige vers EmbeddingModelManager pour auto-unload GPU.

    Utilisez plutôt:
        from knowbase.common.clients.embeddings import get_sentence_transformer
    """
    from knowbase.common.clients.embeddings import get_sentence_transformer as _get_st
    return _get_st(model_name=model_name, device=device, cache_folder=cache_folder)


def ensure_qdrant_collection(
    collection_name: str,
    vector_size: int,
    distance: Distance = Distance.COSINE,
) -> None:
    """Ensure the given Qdrant collection exists with the provided vector size."""
    client = get_qdrant_client()
    if client.collection_exists(collection_name):
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=distance),
    )
