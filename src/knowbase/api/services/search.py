from __future__ import annotations

import os
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sentence_transformers import SentenceTransformer

from knowbase.config.settings import Settings

TOP_K = 10
SCORE_THRESHOLD = 0.5
PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")


def build_response_payload(result, public_url: str) -> dict[str, Any]:
    payload = result.payload or {}
    slide_image_url = payload.get("slide_image_url", "") if payload else ""
    if slide_image_url:
        slide_image_url = f"https://{public_url}/static/thumbnails/{os.path.basename(slide_image_url)}"
    return {
        "text": payload.get("text", ""),
        "source_file": payload.get("source_file_url", ""),
        "slide_index": payload.get("slide_index", ""),
        "score": result.score,
        "slide_image_url": slide_image_url,
    }


def search_documents(
    *,
    question: str,
    qdrant_client: QdrantClient,
    embedding_model: SentenceTransformer,
    settings: Settings,
) -> dict[str, Any]:
    query = question.strip()
    query_vector = embedding_model.encode(query)
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()
    elif hasattr(query_vector, "numpy"):
        query_vector = query_vector.numpy().tolist()
    query_vector = [float(x) for x in query_vector]

    query_filter = Filter(
        must_not=[FieldCondition(key="type", match=MatchValue(value="rfp_qa"))]
    )
    results = qdrant_client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        limit=TOP_K,
        with_payload=True,
        query_filter=query_filter,
    )
    filtered = [r for r in results if r.score >= SCORE_THRESHOLD]
    if not filtered:
        return {
            "status": "no_results",
            "results": [],
            "message": "Aucune information pertinente n’a été trouvée dans la base de connaissance.",
        }

    public_url = PUBLIC_URL
    response_chunks = [build_response_payload(r, public_url) for r in filtered]
    return {"status": "success", "results": response_chunks}


__all__ = ["search_documents", "TOP_K", "SCORE_THRESHOLD"]
