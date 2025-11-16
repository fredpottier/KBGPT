"""
Router API pour les Concepts (Phase 2 - Intelligence Avancée).

POC "Explain this Concept" - Endpoint pour obtenir explications enrichies
sur les concepts avec sources (chunks Qdrant) et relations (Neo4j).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends

from knowbase.api.schemas.concepts import (
    ConceptExplanation,
    ConceptExplanationRequest,
)
from knowbase.api.services.concept_explainer_service import ConceptExplainerService
from knowbase.api.dependencies import get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "concepts_router.log")

router = APIRouter(prefix="/concepts", tags=["concepts"])


@router.get(
    "/{canonical_id}/explain",
    response_model=ConceptExplanation,
    summary="Expliquer un concept",
    description="""
    Explique un concept en combinant données du Knowledge Graph (Neo4j)
    et chunks sources (Qdrant).

    **POC Phase 2 - Intelligence Avancée**

    Cette endpoint démontre l'exploitation du cross-référencement
    Neo4j ↔ Qdrant pour fournir des explications enrichies sur les concepts.

    **Données retournées**:
    - **Identité** : canonical_id, nom canonique, aliases
    - **Sources** : Chunks Qdrant où le concept apparaît (avec contexte)
    - **Relations** : Concepts liés via le graph Neo4j (RELATED_TO, PART_OF, etc.)
    - **Métadonnées** : Timestamps, compteurs

    **Paramètres de filtrage**:
    - `include_chunks` : Inclure ou non les chunks sources (default: true)
    - `include_relations` : Inclure ou non les relations (default: true)
    - `max_chunks` : Nombre max de chunks à retourner (default: 10, max: 50)
    - `max_relations` : Nombre max de relations à retourner (default: 10, max: 50)

    **Use Case**: Interface "Explain this Concept" pour exploration guidée
    """,
    responses={
        200: {
            "description": "Explication enrichie du concept",
            "content": {
                "application/json": {
                    "example": {
                        "canonical_id": "concept-sap-s4hana-123",
                        "name": "SAP S/4HANA",
                        "aliases": ["S/4HANA", "S4HANA"],
                        "summary": "ERP intelligent de nouvelle génération",
                        "source_chunks": [
                            {
                                "chunk_id": "chunk-456",
                                "text": "SAP S/4HANA est la suite ERP...",
                                "document_name": "SAP Overview.pdf",
                                "slide_number": 12,
                                "score": None
                            }
                        ],
                        "related_concepts": [
                            {
                                "canonical_id": "concept-sap-fiori-789",
                                "name": "SAP Fiori",
                                "relationship_type": "USES",
                                "direction": "outgoing"
                            }
                        ],
                        "metadata": {
                            "total_chunks": 24,
                            "created_at": "2025-01-15T10:30:00Z"
                        }
                    }
                }
            }
        },
        404: {
            "description": "Concept non trouvé",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Concept with canonical_id 'concept-xyz' not found"
                    }
                }
            }
        }
    }
)
def explain_concept(
    canonical_id: str,
    include_chunks: bool = Query(
        default=True,
        description="Inclure les chunks sources depuis Qdrant"
    ),
    include_relations: bool = Query(
        default=True,
        description="Inclure les concepts liés depuis Neo4j"
    ),
    max_chunks: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Nombre max de chunks à retourner"
    ),
    max_relations: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Nombre max de relations à retourner"
    ),
    tenant_id: str = Depends(get_tenant_id)
) -> ConceptExplanation:
    """
    Explique un concept avec sources et relations.

    Args:
        canonical_id: ID canonique du concept
        include_chunks: Inclure chunks sources
        include_relations: Inclure concepts liés
        max_chunks: Nombre max de chunks
        max_relations: Nombre max de relations
        tenant_id: ID tenant (isolation multi-tenant)

    Returns:
        ConceptExplanation avec données enrichies

    Raises:
        HTTPException 404: Si concept non trouvé
    """
    logger.info(
        f"[CONCEPT:EXPLAIN] Request for concept {canonical_id} "
        f"(tenant={tenant_id}, chunks={include_chunks}, relations={include_relations})"
    )

    # Créer requête
    request = ConceptExplanationRequest(
        canonical_id=canonical_id,
        include_chunks=include_chunks,
        include_relations=include_relations,
        max_chunks=max_chunks,
        max_relations=max_relations
    )

    # Utiliser service pour récupérer données
    try:
        with ConceptExplainerService(tenant_id=tenant_id) as service:
            explanation = service.explain_concept(request)

            if not explanation:
                logger.warning(
                    f"[CONCEPT:EXPLAIN] Concept {canonical_id} not found "
                    f"(tenant={tenant_id})"
                )
                raise HTTPException(
                    status_code=404,
                    detail=f"Concept with canonical_id '{canonical_id}' not found"
                )

            logger.info(
                f"[CONCEPT:EXPLAIN] ✅ Successfully explained concept {canonical_id} "
                f"({len(explanation.source_chunks)} chunks, "
                f"{len(explanation.related_concepts)} relations)"
            )

            return explanation

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            f"[CONCEPT:EXPLAIN] Error explaining concept {canonical_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while explaining concept: {str(e)}"
        )


__all__ = ["router"]
