"""
Phase 2.11 - Claims API Router

REST endpoints for Claims management and KG/RAG Contract.

Endpoints:
- POST /api/claims/search - Search claims
- GET /api/claims/concept/{id} - Get claims for a concept
- GET /api/claims/concept/{id}/kg-rag - Get KG/RAG Contract
- GET /api/claims/conflicts - Get all conflicts
- POST /api/claims/consolidate - Trigger consolidation

Author: Claude Code
Date: 2025-12-24
"""

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from knowbase.api.schemas.claims import (
    ClaimSearchRequest,
    ClaimSearchResponse,
    CanonicalClaimResponse,
    KGRAGContractResponse,
    ConflictsListResponse,
    ConsolidationRequest,
    ConsolidationResponse,
)
from knowbase.api.services.claim_service import get_claim_service
from knowbase.relations.claim_consolidator import get_claim_consolidator
from knowbase.relations.relation_consolidator import get_relation_consolidator
from knowbase.relations.canonical_claim_writer import get_canonical_claim_writer
from knowbase.relations.canonical_relation_writer import get_canonical_relation_writer

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/claims",
    tags=["claims"],
    responses={404: {"description": "Not found"}}
)


@router.post("/search", response_model=ClaimSearchResponse)
async def search_claims(request: ClaimSearchRequest):
    """
    Search for claims with filters.

    Supports filtering by:
    - Free text query (searches in value)
    - Subject concept ID
    - Claim type
    - Maturity level (VALIDATED, CANDIDATE, CONFLICTING, etc.)
    - Minimum confidence threshold
    """
    try:
        service = get_claim_service()
        return service.search_claims(
            query=request.query,
            subject_concept_id=request.subject_concept_id,
            claim_type=request.claim_type,
            maturity=request.maturity,
            min_confidence=request.min_confidence,
            limit=request.limit,
            offset=request.offset
        )
    except Exception as e:
        logger.error(f"[ClaimsRouter] Error searching claims: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/concept/{concept_id}", response_model=List[CanonicalClaimResponse])
async def get_claims_for_concept(
    concept_id: str,
    claim_types: Optional[str] = Query(
        default=None,
        description="Comma-separated claim types to filter"
    ),
    include_conflicting: bool = Query(
        default=True,
        description="Include conflicting claims"
    )
):
    """
    Get all claims for a specific concept.

    Returns claims sorted by type and confidence.
    """
    try:
        service = get_claim_service()

        # Parse comma-separated claim types
        types_list = None
        if claim_types:
            types_list = [t.strip() for t in claim_types.split(",")]

        return service.get_claims_for_concept(
            concept_id=concept_id,
            claim_types=types_list,
            include_conflicting=include_conflicting
        )
    except Exception as e:
        logger.error(f"[ClaimsRouter] Error getting claims for concept {concept_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/concept/{concept_id}/kg-rag", response_model=KGRAGContractResponse)
async def get_kg_rag_contract(concept_id: str):
    """
    Get KG/RAG Contract for a concept.

    The KG/RAG Contract separates knowledge into:
    - **kg_facts**: VALIDATED claims (high confidence, multi-source)
      → State these directly without hedging
    - **rag_suggestions**: CANDIDATE/CONTEXT_DEPENDENT claims
      → Present with appropriate uncertainty language
    - **conflicts**: CONFLICTING claims
      → Acknowledge explicitly when relevant

    This enables intelligent LLM response generation where the model can:
    1. Assert verified facts confidently
    2. Hedge appropriately for unverified claims
    3. Surface known conflicts transparently

    Example usage in LLM prompt:
    ```
    For concept X:
    - You MAY state: [kg_facts] as facts
    - You SHOULD hedge: [rag_suggestions]
    - Known conflicts: [conflicts]
    ```
    """
    try:
        service = get_claim_service()
        return service.get_kg_rag_contract(concept_id)
    except Exception as e:
        logger.error(f"[ClaimsRouter] Error getting KG/RAG contract for {concept_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conflicts", response_model=ConflictsListResponse)
async def get_all_conflicts():
    """
    Get all conflicting claims.

    Returns claims grouped by (subject, claim_type) where
    multiple contradictory values have been detected.

    Use this to:
    - Review data quality issues
    - Identify claims needing manual resolution
    - Surface known conflicts in responses
    """
    try:
        service = get_claim_service()
        return service.get_all_conflicts()
    except Exception as e:
        logger.error(f"[ClaimsRouter] Error getting conflicts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/consolidate", response_model=ConsolidationResponse)
async def trigger_consolidation(request: ConsolidationRequest):
    """
    Trigger consolidation of RawClaims/RawAssertions.

    Consolidation:
    1. Groups raw claims by (subject, claim_type, scope_key)
    2. Computes maturity (VALIDATED, CANDIDATE, CONFLICTING, etc.)
    3. Creates/updates CanonicalClaim nodes
    4. Similarly consolidates RawAssertions into CanonicalRelations

    Filters:
    - subject_concept_id: Only consolidate for this concept
    - claim_type: Only consolidate this claim type
    - doc_id: Only consolidate from this document
    - force: Reconsolidate even if already done
    """
    try:
        start_time = time.time()

        # Consolidate claims
        claim_consolidator = get_claim_consolidator()
        canonical_claims = claim_consolidator.consolidate_all(
            subject_concept_id=request.subject_concept_id,
            claim_type=request.claim_type,
            doc_id=request.doc_id
        )

        # Write canonical claims
        claim_writer = get_canonical_claim_writer()
        claim_writer.write_batch(canonical_claims)

        # Consolidate relations
        relation_consolidator = get_relation_consolidator()
        canonical_relations = relation_consolidator.consolidate_all(
            subject_concept_id=request.subject_concept_id,
            doc_id=request.doc_id
        )

        # Write canonical relations
        relation_writer = get_canonical_relation_writer()
        relation_writer.write_batch(canonical_relations)

        # Get stats
        claim_stats = claim_consolidator.get_stats()
        execution_time = (time.time() - start_time) * 1000

        logger.info(
            f"[ClaimsRouter] Consolidation complete: "
            f"{len(canonical_claims)} claims, {len(canonical_relations)} relations, "
            f"{claim_stats['conflicts_detected']} conflicts"
        )

        return ConsolidationResponse(
            claims_consolidated=len(canonical_claims),
            relations_consolidated=len(canonical_relations),
            conflicts_detected=claim_stats.get("conflicts_detected", 0),
            execution_time_ms=execution_time
        )

    except Exception as e:
        logger.error(f"[ClaimsRouter] Error during consolidation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/claim-types", response_model=List[str])
async def get_claim_types():
    """
    Get list of all claim types in the system.

    Useful for:
    - Populating filter dropdowns
    - Understanding what types of claims exist
    """
    try:
        service = get_claim_service()
        query = """
        MATCH (cc:CanonicalClaim {tenant_id: $tenant_id})
        RETURN DISTINCT cc.claim_type AS claim_type
        ORDER BY claim_type
        """
        results = service._execute_query(query, {"tenant_id": service.tenant_id})
        return [r["claim_type"] for r in results if r.get("claim_type")]
    except Exception as e:
        logger.error(f"[ClaimsRouter] Error getting claim types: {e}")
        raise HTTPException(status_code=500, detail=str(e))
