from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from sentence_transformers import CrossEncoder

from knowbase.config.settings import get_settings


@lru_cache(maxsize=None)
def get_cross_encoder(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    cache_folder: Optional[str] = None,
) -> CrossEncoder:
    settings = get_settings()
    name = model_name or getattr(settings, 'reranker_model', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
    kwargs: dict[str, object] = {}
    if device is not None:
        kwargs["device"] = device
    if cache_folder is not None:
        kwargs["cache_folder"] = cache_folder
    return CrossEncoder(name, **kwargs)


def rerank_chunks(
    query: str,
    chunks: list[dict[str, Any]],
    top_k: Optional[int] = None,
    reranker: Optional[CrossEncoder] = None,
) -> list[dict[str, Any]]:
    """
    Rerank chunks using cross-encoder model based on query relevance.

    Args:
        query: The search query
        chunks: List of chunks with 'text' field
        top_k: Number of top chunks to return (default: return all)
        reranker: CrossEncoder instance (will create one if None)

    Returns:
        List of chunks reranked by relevance score
    """
    if not chunks:
        return chunks

    if reranker is None:
        reranker = get_cross_encoder()

    # Prepare query-chunk pairs for scoring
    pairs = [(query, chunk.get('text', '')) for chunk in chunks]

    # Get relevance scores
    scores = reranker.predict(pairs)

    # Combine chunks with their reranking scores
    scored_chunks = []
    for chunk, score in zip(chunks, scores):
        chunk_copy = chunk.copy()
        chunk_copy['rerank_score'] = float(score)
        scored_chunks.append(chunk_copy)

    # Sort by reranking score (descending)
    reranked = sorted(scored_chunks, key=lambda x: x['rerank_score'], reverse=True)

    # Return top_k if specified
    if top_k is not None:
        return reranked[:top_k]

    return reranked