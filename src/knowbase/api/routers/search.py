from __future__ import annotations

from fastapi import APIRouter
from typing import List

from knowbase.api.schemas.search import SearchRequest
from knowbase.api.services.search import search_documents, get_available_solutions
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings

router = APIRouter()


@router.post("/search")
def search(request: SearchRequest):
    settings = get_settings()
    qdrant_client = get_qdrant_client()
    embedding_model = get_sentence_transformer()
    return search_documents(
        question=request.question,
        qdrant_client=qdrant_client,
        embedding_model=embedding_model,
        settings=settings,
        solution=request.solution,
    )


@router.get("/solutions")
def get_solutions() -> List[str]:
    """Récupère la liste des solutions disponibles dans la base Qdrant."""
    settings = get_settings()
    qdrant_client = get_qdrant_client()
    return get_available_solutions(
        qdrant_client=qdrant_client,
        settings=settings,
    )


__all__ = ["router"]

