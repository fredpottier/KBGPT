"""
Phase 2.12 - Entity Resolution API Router

REST endpoints for Entity Resolution management.

Endpoints:
- GET /api/entity-resolution/stats - Get overall statistics
- POST /api/entity-resolution/run - Run entity resolution pipeline
- GET /api/entity-resolution/deferred - Get pending deferred candidates
- POST /api/entity-resolution/reevaluate - Trigger reevaluation of deferred
- DELETE /api/entity-resolution/cache - Clear score cache

Author: Claude Code
Date: 2025-12-26
"""

import logging
from typing import Optional, List
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks

from knowbase.entity_resolution import (
    get_entity_resolution_pipeline,
    get_deferred_store,
    get_deferred_reevaluator,
    get_score_cache,
    ConceptType,
    DecisionType,
    EntityResolutionStats,
    THRESHOLDS_BY_TYPE,
    DEFER_CONFIG,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/entity-resolution",
    tags=["entity-resolution"],
    responses={404: {"description": "Not found"}}
)


# ============================================================================
# Schemas
# ============================================================================

class StatsResponse(BaseModel):
    """Entity resolution statistics."""
    pipeline: dict = Field(description="Pipeline statistics")
    deferred_queue: dict = Field(description="Deferred queue stats")
    cache: dict = Field(description="Score cache stats")
    thresholds: dict = Field(description="Thresholds by concept type")
    config: dict = Field(description="Current configuration")


class RunRequest(BaseModel):
    """Request to run entity resolution."""
    concept_type: Optional[str] = Field(None, description="Filter by concept type")
    target_concept_id: Optional[str] = Field(None, description="Process only this concept")
    dry_run: bool = Field(False, description="Simulate without actual merges")


class RunResponse(BaseModel):
    """Response from entity resolution run."""
    success: bool
    message: str
    result: dict


class DeferredCandidateResponse(BaseModel):
    """Deferred candidate info."""
    pair_id: str
    concept_a_id: str
    concept_a_name: str
    concept_b_id: str
    concept_b_name: str
    concept_type: str
    similarity_score: float
    status: str
    created_at: str
    expires_at: str
    evaluation_count: int


class DeferredListResponse(BaseModel):
    """List of deferred candidates."""
    total: int
    candidates: List[DeferredCandidateResponse]


class ReevaluateRequest(BaseModel):
    """Request to reevaluate deferred candidates."""
    batch_size: int = Field(100, description="Max candidates to process")
    min_doc_count: int = Field(0, description="Min documents for candidate")
    dry_run: bool = Field(False, description="Simulate without merges")


class ReevaluateResponse(BaseModel):
    """Response from reevaluation."""
    success: bool
    message: str
    result: dict


class CacheClearResponse(BaseModel):
    """Response from cache clear."""
    success: bool
    keys_deleted: int


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/stats", response_model=StatsResponse)
async def get_stats(tenant_id: str = Query("default", description="Tenant ID")):
    """
    Get entity resolution statistics.

    Returns overall stats including:
    - Pipeline run statistics
    - Deferred queue size and status
    - Score cache statistics
    - Current threshold configuration
    """
    try:
        pipeline = get_entity_resolution_pipeline(tenant_id)
        deferred_store = get_deferred_store(tenant_id)
        cache = get_score_cache()

        # Get pipeline stats
        pipeline_stats = pipeline.get_stats()

        # Get deferred queue stats
        deferred_stats = deferred_store.get_stats()

        # Get cache stats
        cache_stats = cache.get_stats()

        # Format thresholds
        thresholds = {
            t.value: {
                "threshold_auto": THRESHOLDS_BY_TYPE[t].threshold_auto,
                "threshold_defer": THRESHOLDS_BY_TYPE[t].threshold_defer,
                "auto_conditions": THRESHOLDS_BY_TYPE[t].auto_safe_conditions,
            }
            for t in ConceptType
            if t in THRESHOLDS_BY_TYPE
        }

        return StatsResponse(
            pipeline={
                "auto_merges": pipeline_stats.auto_merges,
                "deferred": pipeline_stats.deferred,
                "rejected": pipeline_stats.rejected,
                "auto_rate": pipeline_stats.auto_rate,
                "last_run": pipeline_stats.last_run_at.isoformat() if pipeline_stats.last_run_at else None,
            },
            deferred_queue=deferred_stats,
            cache=cache_stats,
            thresholds=thresholds,
            config={
                "defer_ttl_days": DEFER_CONFIG["ttl_days"],
                "max_deferred_per_tenant": DEFER_CONFIG["max_deferred_per_tenant"],
                "reevaluate_after_n_docs": DEFER_CONFIG["reevaluate_after_n_docs"],
            }
        )

    except Exception as e:
        logger.error(f"[EntityResolutionAPI] Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run", response_model=RunResponse)
async def run_pipeline(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Query("default", description="Tenant ID")
):
    """
    Run entity resolution pipeline.

    Can filter by concept type or target a specific concept.
    Use dry_run=true to simulate without actual merges.
    """
    try:
        pipeline = get_entity_resolution_pipeline(tenant_id)

        # Parse concept type if provided
        concept_type = None
        if request.concept_type:
            try:
                concept_type = ConceptType(request.concept_type)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid concept_type: {request.concept_type}"
                )

        # Run pipeline
        result = pipeline.run(
            concept_type=concept_type,
            target_concept_id=request.target_concept_id,
            dry_run=request.dry_run
        )

        return RunResponse(
            success=len(result.errors) == 0,
            message=f"Processed {result.candidates_generated} candidates, "
                    f"{result.merges_successful} merges",
            result=result.to_dict()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[EntityResolutionAPI] Error running pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deferred", response_model=DeferredListResponse)
async def get_deferred(
    tenant_id: str = Query("default", description="Tenant ID"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="Min similarity score")
):
    """
    Get pending deferred merge candidates.

    Returns candidates waiting for more evidence before AUTO merge.
    """
    try:
        store = get_deferred_store(tenant_id)
        pending = store.get_pending(limit=limit, min_doc_count=0)

        # Filter by min_score
        if min_score > 0:
            pending = [p for p in pending if p.similarity_score >= min_score]

        candidates = [
            DeferredCandidateResponse(
                pair_id=p.pair_id,
                concept_a_id=p.concept_a_id,
                concept_a_name=p.concept_a_name,
                concept_b_id=p.concept_b_id,
                concept_b_name=p.concept_b_name,
                concept_type=p.concept_type.value,
                similarity_score=p.similarity_score,
                status=p.status.value,
                created_at=p.created_at.isoformat(),
                expires_at=p.expires_at.isoformat(),
                evaluation_count=p.evaluation_count,
            )
            for p in pending
        ]

        # Get total count
        stats = store.get_stats()

        return DeferredListResponse(
            total=stats.get("pending", 0),
            candidates=candidates
        )

    except Exception as e:
        logger.error(f"[EntityResolutionAPI] Error getting deferred: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reevaluate", response_model=ReevaluateResponse)
async def reevaluate_deferred(
    request: ReevaluateRequest,
    tenant_id: str = Query("default", description="Tenant ID")
):
    """
    Trigger reevaluation of deferred candidates.

    Checks if any deferred candidates now have enough evidence for AUTO merge.
    """
    try:
        reevaluator = get_deferred_reevaluator(tenant_id)

        result = reevaluator.reevaluate(
            batch_size=request.batch_size,
            min_doc_count=request.min_doc_count,
            dry_run=request.dry_run
        )

        return ReevaluateResponse(
            success=len(result.errors) == 0,
            message=f"Evaluated {result.candidates_evaluated}, "
                    f"promoted {result.promoted_to_auto} to AUTO",
            result=result.to_dict()
        )

    except Exception as e:
        logger.error(f"[EntityResolutionAPI] Error reevaluating: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache", response_model=CacheClearResponse)
async def clear_cache():
    """
    Clear score cache.

    Useful when you want to force re-computation of all scores.
    """
    try:
        cache = get_score_cache()
        deleted = cache.clear()

        return CacheClearResponse(
            success=True,
            keys_deleted=deleted
        )

    except Exception as e:
        logger.error(f"[EntityResolutionAPI] Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thresholds")
async def get_thresholds():
    """
    Get current threshold configuration by concept type.
    """
    return {
        t.value: {
            "threshold_auto": THRESHOLDS_BY_TYPE[t].threshold_auto,
            "threshold_defer": THRESHOLDS_BY_TYPE[t].threshold_defer,
            "auto_safe_conditions": THRESHOLDS_BY_TYPE[t].auto_safe_conditions,
        }
        for t in ConceptType
        if t in THRESHOLDS_BY_TYPE
    }
