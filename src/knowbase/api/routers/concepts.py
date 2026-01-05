"""
Router API pour les Concepts (Phase 2 - Intelligence Avancée).

Endpoints:
- /concepts/{id}/explain: Explication enrichie d'un concept
- /concepts/diff: Diff entre deux markers (PR3 - ADR_ASSERTION_AWARE_KG)
- /concepts/{id}/assertions: Assertions pour un concept
- /concepts/by-polarity: Concepts par polarity
- /concepts/by-scope: Concepts par scope
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from knowbase.api.schemas.concepts import (
    ConceptExplanation,
    ConceptExplanationRequest,
    Polarity,
    AssertionScope,
)
from knowbase.api.services.concept_explainer_service import ConceptExplainerService
from knowbase.api.services.concept_diff_service import (
    ConceptDiffService,
    DiffMode,
    get_concept_diff_service,
)
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


# =============================================================================
# PR3: Diff Queries (ADR_ASSERTION_AWARE_KG)
# =============================================================================


class DiffRequest(BaseModel):
    """Requete de diff entre deux markers."""
    marker_a: str = Field(..., description="Premier marker (ex: '1809')")
    marker_b: str = Field(..., description="Deuxieme marker (ex: '2020')")
    mode: str = Field(
        default="concepts",
        description="Mode de diff: concepts, assertions, relations"
    )
    min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confiance minimale"
    )
    include_details: bool = Field(
        default=True,
        description="Inclure les details des concepts"
    )


class DiffResponse(BaseModel):
    """Reponse de diff."""
    marker_a: str
    marker_b: str
    mode: str
    only_in_a: List[dict] = Field(default_factory=list)
    only_in_b: List[dict] = Field(default_factory=list)
    in_both: List[dict] = Field(default_factory=list)
    changed: List[dict] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


class AssertionsResponse(BaseModel):
    """Reponse des assertions pour un concept."""
    concept_id: str
    canonical_id: Optional[str] = None
    label: str
    assertions: List[dict] = Field(default_factory=list)
    aggregated_polarity: str = "unknown"
    aggregated_scope: str = "unknown"
    has_conflict: bool = False
    conflict_flags: List[str] = Field(default_factory=list)


class ConceptListResponse(BaseModel):
    """Liste de concepts avec metadata."""
    concepts: List[dict] = Field(default_factory=list)
    total: int = 0
    filter_applied: str = ""


@router.post(
    "/diff",
    response_model=DiffResponse,
    summary="Diff entre deux markers",
    description="""
    Compare les concepts entre deux markers (versions, editions, etc.).

    **PR3 - ADR_ASSERTION_AWARE_KG**

    Permet de repondre aux questions:
    - "Qu'est-ce qui est dans 1809 mais pas dans 2020?"
    - "Qu'est-ce qui a change entre A et B?"

    **Modes disponibles**:
    - `concepts`: Diff simple sur presence/absence
    - `assertions`: Diff avec prise en compte de polarity (detecte changements)
    - `relations`: Diff sur les relations (future)

    **Resultats**:
    - `only_in_a`: Concepts uniquement dans le marker A
    - `only_in_b`: Concepts uniquement dans le marker B
    - `in_both`: Concepts presents dans les deux
    - `changed`: Concepts avec changement de polarity (mode assertions)
    """,
)
async def diff_concepts(
    request: DiffRequest,
    tenant_id: str = Depends(get_tenant_id)
) -> DiffResponse:
    """
    Calcule le diff entre deux markers.

    Args:
        request: Parametres du diff
        tenant_id: ID tenant

    Returns:
        DiffResponse avec les ensembles de concepts
    """
    logger.info(
        f"[CONCEPT:DIFF] Request: {request.marker_a} vs {request.marker_b} "
        f"(mode={request.mode}, tenant={tenant_id})"
    )

    try:
        service = get_concept_diff_service(tenant_id)

        mode = DiffMode(request.mode) if request.mode in [m.value for m in DiffMode] else DiffMode.CONCEPTS

        result = await service.diff_by_markers(
            marker_a=request.marker_a,
            marker_b=request.marker_b,
            mode=mode,
            min_confidence=request.min_confidence,
            include_details=request.include_details,
        )

        logger.info(
            f"[CONCEPT:DIFF] ✅ Diff complete: "
            f"{len(result.only_in_a)} in A only, "
            f"{len(result.only_in_b)} in B only, "
            f"{len(result.in_both)} in both"
        )

        return DiffResponse(**result.to_dict())

    except Exception as e:
        logger.error(f"[CONCEPT:DIFF] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Diff query failed: {str(e)}"
        )


@router.get(
    "/diff",
    response_model=DiffResponse,
    summary="Diff entre deux markers (GET)",
    description="Version GET du diff pour faciliter les tests.",
)
async def diff_concepts_get(
    marker_a: str = Query(..., description="Premier marker"),
    marker_b: str = Query(..., description="Deuxieme marker"),
    mode: str = Query(default="concepts", description="Mode de diff"),
    min_confidence: float = Query(default=0.5, ge=0.0, le=1.0),
    tenant_id: str = Depends(get_tenant_id)
) -> DiffResponse:
    """Version GET du diff."""
    request = DiffRequest(
        marker_a=marker_a,
        marker_b=marker_b,
        mode=mode,
        min_confidence=min_confidence,
    )
    return await diff_concepts(request, tenant_id)


@router.get(
    "/{concept_id}/assertions",
    response_model=AssertionsResponse,
    summary="Assertions pour un concept",
    description="""
    Recupere toutes les assertions pour un concept.

    **PR3 - ADR_ASSERTION_AWARE_KG**

    Une assertion = une occurrence du concept dans un document avec:
    - polarity (positive, negative, future, deprecated, conditional)
    - scope (general, constrained)
    - markers associes
    - confidence

    Detecte aussi les conflits (meme concept avec polarities differentes).
    """,
)
async def get_concept_assertions(
    concept_id: str,
    tenant_id: str = Depends(get_tenant_id)
) -> AssertionsResponse:
    """
    Recupere les assertions pour un concept.

    Args:
        concept_id: ID du concept (proto ou canonical)
        tenant_id: ID tenant

    Returns:
        AssertionsResponse avec toutes les assertions
    """
    logger.info(f"[CONCEPT:ASSERTIONS] Request for {concept_id} (tenant={tenant_id})")

    try:
        service = get_concept_diff_service(tenant_id)
        result = await service.get_assertions_for_concept(concept_id)

        if not result.assertions and not result.label:
            raise HTTPException(
                status_code=404,
                detail=f"Concept '{concept_id}' not found"
            )

        logger.info(
            f"[CONCEPT:ASSERTIONS] ✅ Found {len(result.assertions)} assertions "
            f"(conflict={result.has_conflict})"
        )

        return AssertionsResponse(**result.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CONCEPT:ASSERTIONS] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Assertion query failed: {str(e)}"
        )


@router.get(
    "/by-polarity/{polarity}",
    response_model=ConceptListResponse,
    summary="Concepts par polarity",
    description="""
    Recupere les concepts par polarity.

    **Polarities disponibles**:
    - `positive`: Concepts presents/affirmes
    - `negative`: Concepts absents/nies
    - `future`: Concepts futurs (roadmap)
    - `deprecated`: Concepts deprecies/obsoletes
    - `conditional`: Concepts conditionnels

    Utile pour:
    - Trouver tous les concepts deprecies
    - Lister les features futures
    - Identifier les limitations (negative)
    """,
)
async def get_concepts_by_polarity(
    polarity: str,
    marker: Optional[str] = Query(None, description="Filtrer par marker"),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id)
) -> ConceptListResponse:
    """
    Recupere les concepts par polarity.

    Args:
        polarity: Polarity a filtrer
        marker: Optionnel, filtrer par marker
        limit: Nombre max de resultats
        tenant_id: ID tenant

    Returns:
        ConceptListResponse avec les concepts
    """
    logger.info(
        f"[CONCEPT:BY-POLARITY] Request: polarity={polarity}, "
        f"marker={marker}, limit={limit}"
    )

    try:
        pol = Polarity(polarity)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid polarity '{polarity}'. Valid values: {[p.value for p in Polarity]}"
        )

    try:
        service = get_concept_diff_service(tenant_id)
        concepts = await service.get_concepts_by_polarity(
            polarity=pol,
            marker_filter=marker,
            limit=limit,
        )

        return ConceptListResponse(
            concepts=[c.to_dict() for c in concepts],
            total=len(concepts),
            filter_applied=f"polarity={polarity}" + (f", marker={marker}" if marker else ""),
        )

    except Exception as e:
        logger.error(f"[CONCEPT:BY-POLARITY] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Query failed: {str(e)}"
        )


@router.get(
    "/by-scope/{scope}",
    response_model=ConceptListResponse,
    summary="Concepts par scope",
    description="""
    Recupere les concepts par scope.

    **Scopes disponibles**:
    - `general`: Concepts valides pour toutes les variantes
    - `constrained`: Concepts specifiques a un/des markers
    - `unknown`: Concepts sans scope determine

    Utile pour:
    - Trouver les concepts universels (general)
    - Identifier les concepts specifiques a une version (constrained + marker)
    """,
)
async def get_concepts_by_scope(
    scope: str,
    marker: Optional[str] = Query(None, description="Filtrer par marker"),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id)
) -> ConceptListResponse:
    """
    Recupere les concepts par scope.

    Args:
        scope: Scope a filtrer
        marker: Optionnel, filtrer par marker
        limit: Nombre max de resultats
        tenant_id: ID tenant

    Returns:
        ConceptListResponse avec les concepts
    """
    logger.info(
        f"[CONCEPT:BY-SCOPE] Request: scope={scope}, "
        f"marker={marker}, limit={limit}"
    )

    try:
        sc = AssertionScope(scope)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{scope}'. Valid values: {[s.value for s in AssertionScope]}"
        )

    try:
        service = get_concept_diff_service(tenant_id)
        concepts = await service.get_concepts_by_scope(
            scope=sc,
            marker_filter=marker,
            limit=limit,
        )

        return ConceptListResponse(
            concepts=[c.to_dict() for c in concepts],
            total=len(concepts),
            filter_applied=f"scope={scope}" + (f", marker={marker}" if marker else ""),
        )

    except Exception as e:
        logger.error(f"[CONCEPT:BY-SCOPE] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Query failed: {str(e)}"
        )


__all__ = ["router"]
