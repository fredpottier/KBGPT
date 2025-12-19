from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import List

from knowbase.api.dependencies import get_current_user, get_tenant_id
from knowbase.api.schemas.search import SearchRequest
from knowbase.api.services.search import search_documents, get_available_solutions
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings

router = APIRouter()


@router.post("/search")
def search(
    request: SearchRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    🌊 **OSMOSE Graph-Guided RAG** - Recherche sémantique enrichie par Knowledge Graph.

    **Fonctionnement:**
    1. Recherche vectorielle dans Qdrant (chunks documents)
    2. Reranking pour améliorer la pertinence
    3. **Enrichissement KG** (si activé):
       - Extraction des concepts de la question
       - Récupération des concepts liés dans Neo4j
       - Relations transitives découvertes
       - Clusters thématiques (niveau deep)
    4. Synthèse LLM avec contexte enrichi

    **Niveaux d'enrichissement:**
    - `none`: RAG classique (pas d'enrichissement KG)
    - `light`: Concepts liés uniquement (~50ms)
    - `standard`: Concepts + relations transitives (~100ms)
    - `deep`: Tout (concepts, transitives, clusters, bridges) (~200ms)

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    settings = get_settings()
    qdrant_client = get_qdrant_client()
    embedding_model = get_sentence_transformer()
    return search_documents(
        question=request.question,
        qdrant_client=qdrant_client,
        embedding_model=embedding_model,
        settings=settings,
        solution=request.solution,
        tenant_id=tenant_id,
        use_graph_context=request.use_graph_context,
        graph_enrichment_level=request.graph_enrichment_level,
    )


@router.get("/solutions")
def get_solutions(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> List[str]:
    """
    Récupère la liste des solutions disponibles dans la base Qdrant.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    settings = get_settings()
    qdrant_client = get_qdrant_client()
    return get_available_solutions(
        qdrant_client=qdrant_client,
        settings=settings,
    )


__all__ = ["router"]

