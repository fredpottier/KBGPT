"""
🌊 OSMOSE Phase 2.3 - Living Ontology API

Endpoints pour la gestion de l'ontologie dynamique.

Différence avec /ontology:
- /ontology: Gestion manuelle des catalogues (CRUD entités)
- /api/living-ontology: Découverte automatique et évolution dynamique des types

Endpoints:
- GET /api/living-ontology/stats - Statistiques ontologie
- GET /api/living-ontology/types - Liste types existants
- POST /api/living-ontology/discover - Lancer découverte de patterns
- GET /api/living-ontology/proposals - Liste propositions pending
- POST /api/living-ontology/proposals/{id}/approve - Approuver proposition
- POST /api/living-ontology/proposals/{id}/reject - Rejeter proposition
- GET /api/living-ontology/history - Historique changements
- GET /api/living-ontology/patterns - Découvrir patterns (preview)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from knowbase.api.dependencies import get_current_user, get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "living_ontology_api.log")

router = APIRouter(prefix="/api/living-ontology", tags=["living-ontology"])


# ===================================
# SCHEMAS
# ===================================

class DiscoveryRequest(BaseModel):
    """Requête de découverte de patterns."""
    auto_promote: bool = Field(
        default=True,
        description="Auto-promouvoir les types à haute confidence (>=85%)"
    )
    min_occurrences: Optional[int] = Field(
        default=None,
        description="Seuil minimum d'occurrences (défaut: 20)"
    )


class ApproveRequest(BaseModel):
    """Requête d'approbation."""
    pass  # Pas de champs supplémentaires


class RejectRequest(BaseModel):
    """Requête de rejet."""
    reason: Optional[str] = Field(
        default=None,
        description="Raison du rejet"
    )


class TypeInfo(BaseModel):
    """Information sur un type."""
    type_name: str
    count: int
    status: str = "active"
    parent_type: Optional[str] = None


class ProposalResponse(BaseModel):
    """Réponse proposition."""
    proposal_id: str
    type_name: str
    description: str
    confidence: float
    occurrences: int
    support_concepts: List[str]
    status: str
    parent_type: Optional[str] = None


class OntologyStatsResponse(BaseModel):
    """Statistiques ontologie."""
    tenant_id: str
    total_concepts: int
    unique_types: int
    type_distribution: Dict[str, int]
    pending_proposals: int
    total_changes: int
    auto_promote_threshold: float


# ===================================
# ENDPOINTS
# ===================================

@router.get("/stats", response_model=OntologyStatsResponse)
async def get_ontology_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    📊 **Statistiques de l'ontologie vivante**

    Retourne:
    - Nombre total de concepts
    - Distribution par type
    - Propositions en attente
    - Historique des changements

    **Sécurité**: Requiert authentification JWT.
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    manager = get_living_ontology_manager()
    stats = await manager.get_ontology_stats(tenant_id)

    return OntologyStatsResponse(**stats)


@router.get("/types")
async def list_types(
    status: Optional[str] = Query(None, description="Filtrer par status (approved, pending, rejected)"),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    📋 **Liste les types de l'ontologie**

    Retourne tous les types existants avec leur distribution.

    Args:
        status: Filtrer par status
        limit: Nombre max de résultats

    **Sécurité**: Requiert authentification JWT.
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    manager = get_living_ontology_manager()

    # Récupérer distribution depuis Neo4j
    cypher = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WITH
        COALESCE(c.type, c.concept_type, 'entity') AS type_name,
        count(c) AS count
    RETURN type_name, count
    ORDER BY count DESC
    LIMIT $limit
    """

    try:
        results = manager.neo4j_client.execute_query(cypher, {
            "tenant_id": tenant_id,
            "limit": limit
        })

        types = [
            TypeInfo(
                type_name=r["type_name"],
                count=r["count"],
                status="active"
            ).dict()
            for r in results
        ]

        return {
            "status": "success",
            "types": types,
            "total": len(types),
        }

    except Exception as e:
        logger.error(f"[OSMOSE] Erreur list types: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/discover")
async def run_discovery(
    request: DiscoveryRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    🔍 **Lancer la découverte de patterns**

    Analyse le Knowledge Graph pour identifier:
    - Nouveaux types d'entités potentiels
    - Patterns de nommage
    - Raffinements de types existants

    Les patterns à haute confidence (>=85%) sont auto-promus si `auto_promote=true`.
    Les autres sont placés en attente de review.

    **Sécurité**: Requiert authentification JWT (rôle admin recommandé).
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    logger.info(f"[OSMOSE] Discovery requested by {current_user.get('email', 'unknown')}")

    manager = get_living_ontology_manager()

    try:
        results = await manager.run_discovery_cycle(
            tenant_id=tenant_id,
            auto_promote=request.auto_promote
        )

        return {
            "status": "success",
            "message": f"Discovery complete: {results['patterns_discovered']} patterns found",
            **results
        }

    except Exception as e:
        logger.error(f"[OSMOSE] Discovery error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals")
async def list_proposals(
    status: str = Query("pending", description="Status: pending, approved, rejected, auto_promoted"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    📝 **Liste les propositions de types**

    Retourne les propositions de nouveaux types en attente de review.

    Args:
        status: Filtrer par status
        limit: Nombre max de résultats

    **Sécurité**: Requiert authentification JWT.
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    manager = get_living_ontology_manager()

    if status == "pending":
        proposals = manager.list_pending_proposals(tenant_id)
    else:
        # Filtrer par status
        proposals = [
            p for p in manager._proposals.values()
            if p.status == status and p.tenant_id == tenant_id
        ]

    proposals = proposals[:limit]

    return {
        "status": "success",
        "proposals": [p.to_dict() for p in proposals],
        "total": len(proposals),
    }


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    request: ApproveRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    ✅ **Approuver une proposition**

    Approuve une proposition de nouveau type et l'ajoute à l'ontologie.

    Args:
        proposal_id: ID de la proposition

    **Sécurité**: Requiert authentification JWT (rôle admin).
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    admin_email = current_user.get("email", "unknown@admin.com")

    manager = get_living_ontology_manager()

    change = await manager.approve_proposal(proposal_id, admin_email)

    if not change:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal not found or not pending: {proposal_id}"
        )

    logger.info(f"[OSMOSE] Proposal {proposal_id} approved by {admin_email}")

    return {
        "status": "success",
        "message": f"Type '{change.type_name}' approved and added to ontology",
        "change": change.to_dict(),
    }


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    request: RejectRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    ❌ **Rejeter une proposition**

    Rejette une proposition de nouveau type.

    Args:
        proposal_id: ID de la proposition
        reason: Raison du rejet (optionnel)

    **Sécurité**: Requiert authentification JWT (rôle admin).
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    admin_email = current_user.get("email", "unknown@admin.com")

    manager = get_living_ontology_manager()

    success = await manager.reject_proposal(
        proposal_id,
        admin_email,
        request.reason
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal not found or not pending: {proposal_id}"
        )

    logger.info(f"[OSMOSE] Proposal {proposal_id} rejected by {admin_email}")

    return {
        "status": "success",
        "message": f"Proposal rejected",
        "proposal_id": proposal_id,
        "reason": request.reason,
    }


@router.get("/history")
async def get_change_history(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    📜 **Historique des changements**

    Retourne l'historique des modifications de l'ontologie.

    Args:
        limit: Nombre max de résultats

    **Sécurité**: Requiert authentification JWT.
    """
    from knowbase.semantic.ontology import get_living_ontology_manager

    manager = get_living_ontology_manager()

    changes = manager.list_change_history(tenant_id, limit)

    return {
        "status": "success",
        "changes": [c.to_dict() for c in changes],
        "total": len(changes),
    }


@router.get("/patterns")
async def discover_patterns_only(
    pattern_type: Optional[str] = Query(
        None,
        description="Type: new_entity_type, relation_pattern, type_refinement, naming_pattern"
    ),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """
    🔎 **Découvrir patterns sans promotion**

    Analyse le KG et retourne les patterns découverts sans les promouvoir.
    Utile pour preview avant lancement d'un cycle complet.

    **Sécurité**: Requiert authentification JWT.
    """
    from knowbase.semantic.ontology import get_pattern_discovery_service

    service = get_pattern_discovery_service()

    try:
        all_patterns = []

        if pattern_type in (None, "new_entity_type"):
            patterns = await service.discover_new_entity_types(
                tenant_id=tenant_id,
                max_results=limit
            )
            all_patterns.extend(patterns)

        if pattern_type in (None, "relation_pattern"):
            patterns = await service.discover_relation_patterns(tenant_id=tenant_id)
            all_patterns.extend(patterns)

        if pattern_type in (None, "type_refinement"):
            patterns = await service.discover_type_refinements(tenant_id=tenant_id)
            all_patterns.extend(patterns)

        # Filtrer par confidence
        all_patterns = [p for p in all_patterns if p.confidence >= min_confidence]

        # Trier et limiter
        all_patterns.sort(key=lambda p: p.confidence, reverse=True)
        all_patterns = all_patterns[:limit]

        return {
            "status": "success",
            "patterns": [p.to_dict() for p in all_patterns],
            "total": len(all_patterns),
            "filters": {
                "pattern_type": pattern_type,
                "min_confidence": min_confidence,
            }
        }

    except Exception as e:
        logger.error(f"[OSMOSE] Pattern discovery error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
