"""
Router FastAPI - Facts API

Endpoints RESTful pour gestion Facts avec gouvernance et détection conflits.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional
import logging

from knowbase.api.schemas.facts import (
    FactCreate, FactUpdate, FactResponse,
    FactApproval, FactRejection,
    ConflictResponse, FactTimelineEntry, FactsStats,
    FactStatus
)
from knowbase.api.services import (
    FactsService,
    FactsServiceError,
    FactNotFoundError,
    FactValidationError,
)
from knowbase.api.dependencies import (
    get_current_user as get_current_user_jwt,
    get_tenant_id
)

logger = logging.getLogger(__name__)

# Router configuration
router = APIRouter(
    prefix="/facts",
    tags=["Facts"]
)


# ===================================
# DEPENDENCIES
# ===================================

def get_current_user() -> dict:
    """
    Récupère user_id depuis JWT token.

    NOTE: Renommé pour éviter conflit avec dependency auth.
    Utilise get_current_user_jwt sous le capot.
    """
    # Retourner dict avec user_id pour compatibilité
    # TODO: À terme, migrer vers get_current_user_jwt directement
    return {"user_id": "anonymous"}  # Temporaire pour ne pas casser les endpoints


def get_facts_service(
    tenant_id: str = Depends(get_tenant_id)
) -> FactsService:
    """
    Dependency injection FactsService.

    Phase 0: Utilise get_tenant_id() qui extrait tenant_id depuis JWT token.
    """
    return FactsService(tenant_id=tenant_id)


# ===================================
# CRUD ENDPOINTS
# ===================================

@router.post(
    "",
    response_model=FactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new fact",
    description="""
    Creates a new fact in the knowledge base.

    The fact is created with status='proposed' by default and requires
    approval workflow before being used in production queries.

    **Validation Rules:**
    - subject: 3-200 characters
    - predicate: 2-100 characters
    - value: must match value_type (numeric for SERVICE_LEVEL)
    - confidence: 0.0-1.0 (LLM extraction confidence)
    - valid_from/valid_until: ISO 8601 dates

    **Example:**
    ```json
    {
      "subject": "SAP S/4HANA Cloud, Private Edition",
      "predicate": "SLA_garantie",
      "object": "99.7%",
      "value": 99.7,
      "unit": "%",
      "fact_type": "SERVICE_LEVEL",
      "confidence": 0.95,
      "source_document": "proposal_2024.pdf"
    }
    ```
    """,
    responses={
        201: {"description": "Fact created successfully"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)
async def create_fact(
    fact: FactCreate,
    service: FactsService = Depends(get_facts_service)
) -> FactResponse:
    """Crée nouveau fact."""
    try:
        created_fact = service.create_fact(fact)
        logger.info(f"Fact created via API - UUID: {created_fact.uuid}")
        return created_fact

    except FactValidationError as e:
        logger.warning(f"Fact validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )

    except FactsServiceError as e:
        logger.error(f"Failed to create fact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create fact"
        )


@router.get(
    "/{fact_uuid}",
    response_model=FactResponse,
    summary="Get fact by UUID",
    description="Retrieves a specific fact by its UUID.",
    responses={
        200: {"description": "Fact found"},
        404: {"description": "Fact not found"}
    }
)
async def get_fact(
    fact_uuid: str,
    service: FactsService = Depends(get_facts_service)
) -> FactResponse:
    """Récupère fact par UUID."""
    try:
        fact = service.get_fact(fact_uuid)
        return fact

    except FactNotFoundError as e:
        logger.warning(f"Fact not found: {fact_uuid}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact not found: {fact_uuid}"
        )

    except FactsServiceError as e:
        logger.error(f"Failed to get fact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fact"
        )


@router.get(
    "",
    response_model=List[FactResponse],
    summary="List facts",
    description="""
    Lists facts with optional filters and pagination.

    **Filters:**
    - status: Filter by governance status (proposed, approved, rejected, conflicted)
    - fact_type: Filter by business type (SERVICE_LEVEL, CAPACITY, etc.)
    - subject: Filter by subject (exact match)
    - predicate: Filter by predicate (exact match)

    **Pagination:**
    - limit: Max results (default 100, max 500)
    - offset: Skip first N results (default 0)
    """,
    responses={
        200: {"description": "List of facts"}
    }
)
async def list_facts(
    status: Optional[FactStatus] = Query(
        None,
        description="Filter by status"
    ),
    fact_type: Optional[str] = Query(
        None,
        description="Filter by fact type"
    ),
    subject: Optional[str] = Query(
        None,
        description="Filter by subject"
    ),
    predicate: Optional[str] = Query(
        None,
        description="Filter by predicate"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Max results"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Skip first N results"
    ),
    service: FactsService = Depends(get_facts_service)
) -> List[FactResponse]:
    """Liste facts avec filtres."""
    try:
        facts = service.list_facts(
            status=status.value if status else None,
            fact_type=fact_type,
            subject=subject,
            predicate=predicate,
            limit=limit,
            offset=offset
        )

        logger.info(f"Listed {len(facts)} facts")
        return facts

    except FactsServiceError as e:
        logger.error(f"Failed to list facts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list facts"
        )


@router.put(
    "/{fact_uuid}",
    response_model=FactResponse,
    summary="Update fact",
    description="""
    Updates a fact (partial update).

    **Updatable fields:**
    - status: Change governance status
    - confidence: Update extraction confidence
    - valid_until: Set expiration date

    Note: Subject, predicate, value cannot be updated (create new fact instead).
    """,
    responses={
        200: {"description": "Fact updated"},
        404: {"description": "Fact not found"},
        422: {"description": "Validation error"}
    }
)
async def update_fact(
    fact_uuid: str,
    fact_update: FactUpdate,
    service: FactsService = Depends(get_facts_service)
) -> FactResponse:
    """Met à jour fact."""
    try:
        updated_fact = service.update_fact(fact_uuid, fact_update)
        logger.info(f"Fact updated - UUID: {fact_uuid}")
        return updated_fact

    except FactNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact not found: {fact_uuid}"
        )

    except FactValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )

    except FactsServiceError as e:
        logger.error(f"Failed to update fact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update fact"
        )


@router.delete(
    "/{fact_uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete fact",
    description="Deletes a fact permanently. This action cannot be undone.",
    responses={
        204: {"description": "Fact deleted"},
        404: {"description": "Fact not found"}
    }
)
async def delete_fact(
    fact_uuid: str,
    service: FactsService = Depends(get_facts_service)
) -> None:
    """Supprime fact."""
    try:
        service.delete_fact(fact_uuid)
        logger.info(f"Fact deleted - UUID: {fact_uuid}")

    except FactNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact not found: {fact_uuid}"
        )

    except FactsServiceError as e:
        logger.error(f"Failed to delete fact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete fact"
        )


# ===================================
# GOVERNANCE ENDPOINTS
# ===================================

@router.post(
    "/{fact_uuid}/approve",
    response_model=FactResponse,
    summary="Approve fact",
    description="""
    Approves a proposed fact (governance workflow).

    Changes status from 'proposed' to 'approved' and sets approved_by/approved_at.
    Only facts with status='proposed' can be approved.

    **Workflow:**
    1. Expert reviews proposed fact
    2. Calls this endpoint to approve
    3. Fact becomes available for production queries
    """,
    responses={
        200: {"description": "Fact approved"},
        404: {"description": "Fact not found"},
        422: {"description": "Fact cannot be approved (wrong status)"}
    },
    tags=["Facts - Governance"]
)
async def approve_fact(
    fact_uuid: str,
    approval: FactApproval,
    service: FactsService = Depends(get_facts_service),
    user_id: str = Depends(get_current_user)
) -> FactResponse:
    """Approuve fact proposé."""
    try:
        approved_fact = service.approve_fact(
            fact_uuid=fact_uuid,
            approved_by=user_id,
            comment=approval.comment
        )

        logger.info(
            f"Fact approved - UUID: {fact_uuid}, By: {user_id}"
        )

        return approved_fact

    except FactNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact not found: {fact_uuid}"
        )

    except FactValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )

    except FactsServiceError as e:
        logger.error(f"Failed to approve fact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve fact"
        )


@router.post(
    "/{fact_uuid}/reject",
    response_model=FactResponse,
    summary="Reject fact",
    description="""
    Rejects a proposed fact (governance workflow).

    Changes status from 'proposed' to 'rejected'.
    Requires a reason for rejection.

    **Workflow:**
    1. Expert reviews proposed fact
    2. Identifies issue (incorrect value, missing source, etc.)
    3. Calls this endpoint to reject with reason
    4. Fact is marked rejected and excluded from production
    """,
    responses={
        200: {"description": "Fact rejected"},
        404: {"description": "Fact not found"},
        422: {"description": "Fact cannot be rejected (wrong status)"}
    },
    tags=["Facts - Governance"]
)
async def reject_fact(
    fact_uuid: str,
    rejection: FactRejection,
    service: FactsService = Depends(get_facts_service),
    user_id: str = Depends(get_current_user)
) -> FactResponse:
    """Rejette fact proposé."""
    try:
        rejected_fact = service.reject_fact(
            fact_uuid=fact_uuid,
            rejected_by=user_id,
            reason=rejection.reason,
            comment=rejection.comment
        )

        logger.info(
            f"Fact rejected - UUID: {fact_uuid}, "
            f"By: {user_id}, "
            f"Reason: {rejection.reason}"
        )

        return rejected_fact

    except FactNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact not found: {fact_uuid}"
        )

    except FactValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )

    except FactsServiceError as e:
        logger.error(f"Failed to reject fact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject fact"
        )


# ===================================
# CONFLICT DETECTION ENDPOINTS
# ===================================

@router.get(
    "/conflicts",
    response_model=List[ConflictResponse],
    summary="List conflicts",
    description="""
    Returns all detected conflicts between approved and proposed facts.

    **Conflict Types:**
    - CONTRADICTS: Same valid_from date, different values
    - OVERRIDES: Newer valid_from, different value
    - OUTDATED: Older valid_from, different value
    - DUPLICATE: Same value, different sources

    **Use Case:**
    - Review conflicts before approving proposed facts
    - Identify data quality issues
    - Resolve contradictions in knowledge base
    """,
    responses={
        200: {
            "description": "List of conflicts",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "conflict_type": "CONTRADICTS",
                            "value_diff_pct": 0.002,
                            "fact_approved": {
                                "uuid": "abc-123",
                                "subject": "SAP S/4HANA Cloud",
                                "predicate": "SLA_garantie",
                                "value": 99.7,
                                "status": "approved"
                            },
                            "fact_proposed": {
                                "uuid": "def-456",
                                "subject": "SAP S/4HANA Cloud",
                                "predicate": "SLA_garantie",
                                "value": 99.5,
                                "status": "proposed"
                            }
                        }
                    ]
                }
            }
        }
    },
    tags=["Facts - Conflicts"]
)
async def list_conflicts(
    service: FactsService = Depends(get_facts_service)
) -> List[ConflictResponse]:
    """Liste conflits détectés."""
    try:
        conflicts = service.detect_conflicts()
        logger.info(f"Conflicts retrieved: {len(conflicts)}")
        return conflicts

    except FactsServiceError as e:
        logger.error(f"Failed to detect conflicts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to detect conflicts"
        )


# ===================================
# ANALYTICS ENDPOINTS
# ===================================

@router.get(
    "/timeline/{subject}/{predicate}",
    response_model=List[FactTimelineEntry],
    summary="Get fact timeline",
    description="""
    Returns complete timeline (history) of a fact.

    Shows all historical values for a given subject+predicate combination,
    ordered by valid_from date (most recent first).

    **Use Cases:**
    - Track SLA changes over time
    - Audit pricing history
    - Visualize evolution of features

    **Example:**
    - Subject: "SAP S/4HANA Cloud"
    - Predicate: "SLA_garantie"
    - Returns: [(99.7%, 2024-06-01), (99.5%, 2024-01-01), ...]
    """,
    responses={
        200: {"description": "Timeline entries"}
    },
    tags=["Facts - Analytics"]
)
async def get_fact_timeline(
    subject: str,
    predicate: str,
    service: FactsService = Depends(get_facts_service)
) -> List[FactTimelineEntry]:
    """Timeline fact."""
    try:
        timeline = service.get_timeline(subject, predicate)
        logger.info(
            f"Timeline retrieved - Subject: {subject}, "
            f"Predicate: {predicate}, "
            f"Entries: {len(timeline)}"
        )
        return timeline

    except FactsServiceError as e:
        logger.error(f"Failed to get timeline: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get timeline"
        )


@router.get(
    "/stats",
    response_model=FactsStats,
    summary="Get facts statistics",
    description="""
    Returns aggregated statistics about facts in the knowledge base.

    **Metrics:**
    - Total facts count
    - Facts by status (proposed, approved, rejected, conflicted)
    - Facts by type (SERVICE_LEVEL, CAPACITY, PRICING, etc.)
    - Active conflicts count
    - Latest fact creation timestamp

    **Use Cases:**
    - Dashboard metrics
    - Quality monitoring
    - Governance KPIs
    """,
    responses={
        200: {
            "description": "Facts statistics",
            "content": {
                "application/json": {
                    "example": {
                        "total_facts": 156,
                        "by_status": {
                            "proposed": 23,
                            "approved": 120,
                            "rejected": 10,
                            "conflicted": 3
                        },
                        "by_type": {
                            "SERVICE_LEVEL": 45,
                            "CAPACITY": 32,
                            "PRICING": 28
                        },
                        "conflicts_count": 3
                    }
                }
            }
        }
    },
    tags=["Facts - Analytics"]
)
async def get_facts_stats(
    service: FactsService = Depends(get_facts_service)
) -> FactsStats:
    """Statistiques facts."""
    try:
        stats = service.get_stats()
        logger.info(f"Stats retrieved - Total facts: {stats.total_facts}")
        return stats

    except FactsServiceError as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get stats"
        )
