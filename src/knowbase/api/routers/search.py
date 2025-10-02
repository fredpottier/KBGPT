from __future__ import annotations

from fastapi import APIRouter
from typing import List, Optional
from pydantic import BaseModel, Field

from knowbase.api.schemas.search import SearchRequest
from knowbase.api.services.search import search_documents, get_available_solutions
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings

# Import hybrid search (Phase 1 Critère 1.4)
from knowbase.search.hybrid_search import hybrid_search, search_with_entity_filter

router = APIRouter()


# Schéma requête hybrid search
class HybridSearchRequest(BaseModel):
    """Requête search hybride Qdrant + Graphiti"""
    question: str = Field(..., description="Question/requête utilisateur")
    tenant_id: str = Field(..., description="ID tenant pour isolation multi-tenant")
    limit: int = Field(10, description="Nombre résultats max", ge=1, le=50)
    weights: Optional[dict] = Field(
        None,
        description="Pondération scores (ex: {'qdrant': 0.7, 'graphiti': 0.3})"
    )
    entity_filter: Optional[List[str]] = Field(
        None,
        description="Filtrer par types entities (ex: ['PRODUCT', 'TECHNOLOGY'])"
    )


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


@router.post("/search/hybrid")
async def search_hybrid(request: HybridSearchRequest):
    """
    Search hybride Qdrant + Graphiti (Phase 1 Critère 1.4)

    Combine recherche vectorielle (Qdrant) et knowledge graph (Graphiti)
    pour résultats enrichis avec entities/relations.

    Args:
        request: HybridSearchRequest avec question, tenant_id, etc.

    Returns:
        Liste résultats hybrides avec scores combinés et metadata KG

    Example:
        POST /search/hybrid
        {
            "question": "SAP S/4HANA consolidation process",
            "tenant_id": "acme_corp",
            "limit": 10,
            "weights": {"qdrant": 0.7, "graphiti": 0.3}
        }
    """
    # Search avec ou sans filtre entities
    if request.entity_filter:
        results = await search_with_entity_filter(
            query=request.question,
            tenant_id=request.tenant_id,
            entity_types=request.entity_filter,
            limit=request.limit
        )
    else:
        results = await hybrid_search(
            query=request.question,
            tenant_id=request.tenant_id,
            limit=request.limit,
            weights=request.weights
        )

    # Convertir en dict pour réponse API
    return {
        "results": [r.to_dict() for r in results],
        "total": len(results),
        "query": request.question,
        "tenant_id": request.tenant_id,
        "weights": request.weights or {"qdrant": 0.7, "graphiti": 0.3}
    }


__all__ = ["router"]

