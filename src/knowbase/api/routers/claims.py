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
    ConsolidationStatsResponse,
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

    Separation:
    - consolidate_claims: Only consolidate claims (default: true)
    - consolidate_relations: Only consolidate relations (default: true)
    """
    try:
        start_time = time.time()

        claims_count = 0
        relations_count = 0
        conflicts_count = 0
        claims_validated = 0
        claims_candidate = 0
        relations_validated = 0
        relations_candidate = 0

        # Consolidate claims if requested
        if request.consolidate_claims:
            claim_consolidator = get_claim_consolidator()
            canonical_claims = claim_consolidator.consolidate_all(
                subject_concept_id=request.subject_concept_id,
                claim_type=request.claim_type,
                doc_id=request.doc_id
            )

            # Write canonical claims
            claim_writer = get_canonical_claim_writer()
            claim_writer.write_batch(canonical_claims)

            # Get stats
            claim_stats = claim_consolidator.get_stats()
            claims_count = len(canonical_claims)
            conflicts_count = claim_stats.get("conflicts_detected", 0)
            claims_validated = claim_stats.get("validated", 0)
            claims_candidate = claims_count - claims_validated - conflicts_count

            logger.info(
                f"[ClaimsRouter] Claims consolidation: {claims_count} claims, "
                f"{claims_validated} validated, {conflicts_count} conflicts"
            )

        # Consolidate relations if requested
        if request.consolidate_relations:
            relation_consolidator = get_relation_consolidator()
            canonical_relations = relation_consolidator.consolidate_all(
                subject_concept_id=request.subject_concept_id,
                doc_id=request.doc_id
            )

            # Write canonical relations
            relation_writer = get_canonical_relation_writer()
            relation_writer.write_batch(canonical_relations)

            # Get stats
            relation_stats = relation_consolidator.get_stats()
            relations_count = len(canonical_relations)
            relations_validated = relation_stats.get("validated", 0)
            relations_candidate = relations_count - relations_validated

            logger.info(
                f"[ClaimsRouter] Relations consolidation: {relations_count} relations, "
                f"{relations_validated} validated"
            )

        execution_time = (time.time() - start_time) * 1000

        logger.info(
            f"[ClaimsRouter] Consolidation complete in {execution_time:.0f}ms: "
            f"{claims_count} claims, {relations_count} relations"
        )

        return ConsolidationResponse(
            claims_consolidated=claims_count,
            relations_consolidated=relations_count,
            conflicts_detected=conflicts_count,
            execution_time_ms=execution_time,
            claims_validated=claims_validated,
            claims_candidate=claims_candidate,
            relations_validated=relations_validated,
            relations_candidate=relations_candidate
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


@router.get("/stats", response_model=ConsolidationStatsResponse)
async def get_consolidation_stats():
    """
    Get comprehensive consolidation statistics.

    Returns counts for:
    - Raw claims and assertions (before consolidation)
    - Canonical claims and relations (after consolidation)
    - Breakdown by maturity level (VALIDATED, CANDIDATE, CONFLICTING, etc.)
    - Relation types distribution
    """
    try:
        service = get_claim_service()

        # Query all counts in parallel-ish manner
        queries = {
            "raw_claims": """
                MATCH (rc:RawClaim {tenant_id: $tenant_id})
                RETURN count(rc) AS count
            """,
            "raw_assertions": """
                MATCH (ra:RawAssertion {tenant_id: $tenant_id})
                RETURN count(ra) AS count
            """,
            "canonical_claims": """
                MATCH (cc:CanonicalClaim {tenant_id: $tenant_id})
                RETURN count(cc) AS count
            """,
            "canonical_relations": """
                MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
                RETURN count(cr) AS count
            """,
            "claims_by_maturity": """
                MATCH (cc:CanonicalClaim {tenant_id: $tenant_id})
                RETURN cc.maturity AS maturity, count(cc) AS count
            """,
            "relations_by_maturity": """
                MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
                RETURN cr.maturity AS maturity, count(cr) AS count
            """,
            "relation_types": """
                MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
                RETURN cr.relation_type AS type, count(cr) AS count
                ORDER BY count DESC
            """,
        }

        results = {}
        for key, query in queries.items():
            try:
                results[key] = service._execute_query(query, {"tenant_id": service.tenant_id})
            except Exception:
                results[key] = []

        # Parse results
        raw_claims = results["raw_claims"][0]["count"] if results["raw_claims"] else 0
        raw_assertions = results["raw_assertions"][0]["count"] if results["raw_assertions"] else 0
        canonical_claims = results["canonical_claims"][0]["count"] if results["canonical_claims"] else 0
        canonical_relations = results["canonical_relations"][0]["count"] if results["canonical_relations"] else 0

        # Claims by maturity
        claims_validated = 0
        claims_candidate = 0
        claims_conflicting = 0
        claims_context_dependent = 0
        for row in results.get("claims_by_maturity", []):
            maturity = row.get("maturity", "")
            count = row.get("count", 0)
            if maturity == "VALIDATED":
                claims_validated = count
            elif maturity == "CANDIDATE":
                claims_candidate = count
            elif maturity == "CONFLICTING":
                claims_conflicting = count
            elif maturity == "CONTEXT_DEPENDENT":
                claims_context_dependent = count

        # Relations by maturity
        relations_validated = 0
        relations_candidate = 0
        relations_ambiguous = 0
        for row in results.get("relations_by_maturity", []):
            maturity = row.get("maturity", "")
            count = row.get("count", 0)
            if maturity == "VALIDATED":
                relations_validated = count
            elif maturity == "CANDIDATE":
                relations_candidate = count
            elif maturity == "AMBIGUOUS_TYPE":
                relations_ambiguous = count

        # Relation types distribution
        relation_types = {}
        for row in results.get("relation_types", []):
            rel_type = row.get("type", "UNKNOWN")
            count = row.get("count", 0)
            relation_types[rel_type] = count

        return ConsolidationStatsResponse(
            raw_claims_count=raw_claims,
            raw_assertions_count=raw_assertions,
            canonical_claims_count=canonical_claims,
            canonical_relations_count=canonical_relations,
            claims_validated=claims_validated,
            claims_candidate=claims_candidate,
            claims_conflicting=claims_conflicting,
            claims_context_dependent=claims_context_dependent,
            relations_validated=relations_validated,
            relations_candidate=relations_candidate,
            relations_ambiguous=relations_ambiguous,
            relation_types=relation_types
        )

    except Exception as e:
        logger.error(f"[ClaimsRouter] Error getting consolidation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
