"""
Router API pour les Markers (PR3 - ADR_ASSERTION_AWARE_KG).

Endpoints:
- GET /markers: Liste tous les markers disponibles
- GET /markers/{value}: Détails d'un marker spécifique
- GET /markers/{value}/concepts: Concepts associés à un marker
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from knowbase.consolidation.marker_store import (
    MarkerStore,
    MarkerKind,
    get_marker_store,
)
from knowbase.api.dependencies import get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "markers_router.log")

router = APIRouter(prefix="/markers", tags=["markers"])


class MarkerInfo(BaseModel):
    """Information sur un marker."""
    value: str
    kind: str
    concept_count: int = 0
    avg_confidence: Optional[float] = None


class MarkerListResponse(BaseModel):
    """Liste de markers."""
    markers: List[MarkerInfo] = Field(default_factory=list)
    total: int = 0


class ConceptInMarker(BaseModel):
    """Concept associé à un marker."""
    concept_id: str
    label: str
    confidence: float
    is_inherited: bool = False
    canonical_id: Optional[str] = None
    canonical_name: Optional[str] = None


class MarkerConceptsResponse(BaseModel):
    """Concepts associés à un marker."""
    marker_value: str
    concepts: List[ConceptInMarker] = Field(default_factory=list)
    total: int = 0


@router.get(
    "",
    response_model=MarkerListResponse,
    summary="Liste des markers",
    description="""
    Récupère tous les markers disponibles dans le Knowledge Graph.

    Les markers sont des identifiants de contexte (versions, éditions, etc.)
    extraits des documents. Ils permettent de filtrer et comparer les concepts.

    **Types de markers**:
    - `numeric_code`: Codes SAP (1809, 2020, 2508)
    - `version`: Versions (v1.0.0, 3.2.1)
    - `fps`: Feature Pack Stacks (FPS03, FPS05)
    - `sp`: Support Packages (SP02, SP100)
    - `year`: Années (2024, 2025)
    - `edition`: Éditions (Cloud, Private, Public)
    """,
)
async def list_markers(
    kind: Optional[str] = Query(None, description="Filtrer par type de marker"),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
) -> MarkerListResponse:
    """
    Liste tous les markers disponibles.

    Args:
        kind: Type de marker à filtrer (optionnel)
        limit: Nombre max de résultats
        tenant_id: ID tenant

    Returns:
        MarkerListResponse avec la liste des markers
    """
    logger.info(f"[MARKERS:LIST] Request (kind={kind}, limit={limit}, tenant={tenant_id})")

    try:
        store = get_marker_store(tenant_id)

        # Filtrer par kind si spécifié
        kind_filter = None
        if kind:
            try:
                kind_filter = MarkerKind(kind)
            except ValueError:
                pass  # Ignorer kind invalide

        markers_data = await store.get_all_markers(kind_filter=kind_filter)

        # Limiter les résultats
        markers_data = markers_data[:limit]

        markers = [
            MarkerInfo(
                value=m.get("value", ""),
                kind=m.get("kind", "unknown"),
                concept_count=m.get("concept_count", 0),
                avg_confidence=m.get("avg_confidence"),
            )
            for m in markers_data
        ]

        logger.info(f"[MARKERS:LIST] Found {len(markers)} markers")

        return MarkerListResponse(
            markers=markers,
            total=len(markers),
        )

    except Exception as e:
        logger.error(f"[MARKERS:LIST] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list markers: {str(e)}"
        )


@router.get(
    "/{marker_value}",
    response_model=MarkerInfo,
    summary="Détails d'un marker",
    description="Récupère les informations détaillées d'un marker spécifique.",
)
async def get_marker(
    marker_value: str,
    tenant_id: str = Depends(get_tenant_id),
) -> MarkerInfo:
    """
    Récupère les détails d'un marker.

    Args:
        marker_value: Valeur du marker
        tenant_id: ID tenant

    Returns:
        MarkerInfo avec les détails
    """
    logger.info(f"[MARKERS:GET] Request for {marker_value}")

    try:
        store = get_marker_store(tenant_id)
        markers_data = await store.get_all_markers()

        # Chercher le marker
        for m in markers_data:
            if m.get("value") == marker_value:
                return MarkerInfo(
                    value=m.get("value", ""),
                    kind=m.get("kind", "unknown"),
                    concept_count=m.get("concept_count", 0),
                    avg_confidence=m.get("avg_confidence"),
                )

        raise HTTPException(
            status_code=404,
            detail=f"Marker '{marker_value}' not found"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MARKERS:GET] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get marker: {str(e)}"
        )


@router.get(
    "/{marker_value}/concepts",
    response_model=MarkerConceptsResponse,
    summary="Concepts d'un marker",
    description="""
    Récupère tous les concepts associés à un marker.

    Utile pour voir quels concepts sont valides pour une version/édition spécifique.
    """,
)
async def get_marker_concepts(
    marker_value: str,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: str = Depends(get_tenant_id),
) -> MarkerConceptsResponse:
    """
    Récupère les concepts associés à un marker.

    Args:
        marker_value: Valeur du marker
        min_confidence: Confiance minimale
        limit: Nombre max de résultats
        tenant_id: ID tenant

    Returns:
        MarkerConceptsResponse avec les concepts
    """
    logger.info(f"[MARKERS:CONCEPTS] Request for {marker_value} (min_conf={min_confidence})")

    try:
        store = get_marker_store(tenant_id)
        concepts_data = await store.get_concepts_with_marker(
            marker_value=marker_value,
            min_confidence=min_confidence,
        )

        # Limiter
        concepts_data = concepts_data[:limit]

        concepts = [
            ConceptInMarker(
                concept_id=c.get("concept_id", ""),
                label=c.get("label", ""),
                confidence=c.get("confidence", 0.0),
                is_inherited=c.get("is_inherited", False),
                canonical_id=c.get("canonical_id"),
                canonical_name=c.get("canonical_name"),
            )
            for c in concepts_data
        ]

        return MarkerConceptsResponse(
            marker_value=marker_value,
            concepts=concepts,
            total=len(concepts),
        )

    except Exception as e:
        logger.error(f"[MARKERS:CONCEPTS] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get marker concepts: {str(e)}"
        )


__all__ = ["router"]
