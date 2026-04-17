"""
Router KG Health — endpoint /api/kg-health/*

Expose le diagnostic de qualite intrinseque du Knowledge Graph :
- GET /score : score global + breakdown par famille + actionables
- GET /drilldown/{key} : top N mauvais acteurs pour une metrique
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from knowbase.api.dependencies import get_tenant_id
from knowbase.api.schemas.kg_health import (
    KGHealthDrilldownResponse,
    KGHealthScoreResponse,
)
from knowbase.api.services.kg_health_service import get_kg_health_service

logger = logging.getLogger("[OSMOSE] kg_health_router")

router = APIRouter(prefix="/kg-health", tags=["KG Health"])


@router.get("/score", response_model=KGHealthScoreResponse)
async def get_health_score(
    tenant_id: str = Depends(get_tenant_id),
) -> KGHealthScoreResponse:
    """
    Score global de sante du Knowledge Graph.

    Retourne :
    - score global 0-100 pondere
    - 4 familles (Provenance, Structure, Distribution, Coherence)
    - panneau actionables (top docs mal extraits, hubs anormaux, singletons, perspective)
    - resume corpus (claims, entities, facets, documents)
    """
    try:
        service = get_kg_health_service()
        return service.compute_score(tenant_id)
    except Exception as e:
        logger.exception(f"[kg_health] compute_score failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=f"KG Health calcul echoue : {e}")


@router.get("/drilldown/{key}", response_model=KGHealthDrilldownResponse)
async def get_drilldown(
    key: str,
    limit: int = Query(default=30, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
) -> KGHealthDrilldownResponse:
    """
    Drill-down detaille pour une metrique donnee.

    Cles supportees :
    - `worst_docs` : top N documents avec linkage Claim->Facet le plus faible
    - `top_hubs` : entites dominantes (candidate a fusion ou filtrage)
    - `orphan_entities` : entites non referencees par aucun Claim
    """
    try:
        service = get_kg_health_service()
        return service.drilldown(key, tenant_id, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"[kg_health] drilldown '{key}' failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Drilldown echoue : {e}")
