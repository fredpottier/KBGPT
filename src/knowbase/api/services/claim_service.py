"""
Phase 2.11 - Claims Service

Business logic for Claims API.
Implements KG/RAG Contract for intelligent response generation.

Author: Claude Code
Date: 2025-12-24
"""

import json
import logging
from typing import Any, Dict, List, Optional

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.api.schemas.claims import (
    CanonicalClaimResponse,
    ClaimSourceResponse,
    ClaimSearchResponse,
    ConflictingClaimsResponse,
    ConflictsListResponse,
    KGRAGContractResponse,
    KGFactResponse,
    RAGSuggestionResponse,
    ConflictInfo,
)

logger = logging.getLogger(__name__)


class ClaimService:
    """
    Service for Claims API operations.

    Provides:
    - Claim search and retrieval
    - Claims by concept
    - KG/RAG Contract generation
    - Conflict detection
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize service.

        Args:
            neo4j_client: Neo4j client instance
            tenant_id: Tenant ID
        """
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _claim_to_response(self, claim_data: Dict[str, Any]) -> CanonicalClaimResponse:
        """Convert Neo4j claim data to response schema."""
        # Parse sources from JSON
        sources = []
        sources_json = claim_data.get("sources_json", "[]")
        if sources_json:
            try:
                sources_data = json.loads(sources_json) if isinstance(sources_json, str) else sources_json
                for s in sources_data:
                    sources.append(ClaimSourceResponse(
                        document_id=s.get("document_id", ""),
                        excerpt=s.get("excerpt", ""),
                        page_number=s.get("page_number")
                    ))
            except json.JSONDecodeError:
                pass

        # Parse scope_struct from JSON
        scope_struct = {}
        scope_json = claim_data.get("scope_struct", "{}")
        if scope_json:
            try:
                scope_struct = json.loads(scope_json) if isinstance(scope_json, str) else scope_json
            except json.JSONDecodeError:
                pass

        return CanonicalClaimResponse(
            canonical_claim_id=claim_data.get("canonical_claim_id", ""),
            subject_concept_id=claim_data.get("subject_concept_id", ""),
            subject_name=claim_data.get("subject_name"),
            claim_type=claim_data.get("claim_type", ""),
            value=claim_data.get("value", ""),
            value_numeric=claim_data.get("value_numeric"),
            unit=claim_data.get("unit"),
            value_type=claim_data.get("value_type", "text"),
            scope_key=claim_data.get("scope_key", ""),
            scope_struct=scope_struct,
            distinct_documents=claim_data.get("distinct_documents", 0),
            total_assertions=claim_data.get("total_assertions", 0),
            confidence_p50=claim_data.get("confidence_p50", 0.0),
            maturity=claim_data.get("maturity", "CANDIDATE"),
            status=claim_data.get("status", "active"),
            conflicts_with=[],  # Would need separate query
            sources=sources
        )

    def search_claims(
        self,
        query: Optional[str] = None,
        subject_concept_id: Optional[str] = None,
        claim_type: Optional[str] = None,
        maturity: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 20,
        offset: int = 0
    ) -> ClaimSearchResponse:
        """
        Search for claims with filters.

        Args:
            query: Free text search (searches in value)
            subject_concept_id: Filter by subject
            claim_type: Filter by claim type
            maturity: Filter by maturity level
            min_confidence: Minimum confidence threshold
            limit: Max results
            offset: Pagination offset

        Returns:
            ClaimSearchResponse with matching claims
        """
        where_clauses = ["cc.tenant_id = $tenant_id"]
        params: Dict[str, Any] = {"tenant_id": self.tenant_id}

        if query:
            where_clauses.append("cc.value CONTAINS $query")
            params["query"] = query

        if subject_concept_id:
            where_clauses.append("cc.subject_concept_id = $subject_id")
            params["subject_id"] = subject_concept_id

        if claim_type:
            where_clauses.append("cc.claim_type = $claim_type")
            params["claim_type"] = claim_type

        if maturity:
            where_clauses.append("cc.maturity = $maturity")
            params["maturity"] = maturity

        if min_confidence > 0:
            where_clauses.append("cc.confidence_p50 >= $min_confidence")
            params["min_confidence"] = min_confidence

        where_str = " AND ".join(where_clauses)

        # Count query
        count_query = f"""
        MATCH (cc:CanonicalClaim)
        WHERE {where_str}
        RETURN count(cc) AS total
        """
        count_result = self._execute_query(count_query, params)
        total = count_result[0]["total"] if count_result else 0

        # Data query with pagination
        data_query = f"""
        MATCH (cc:CanonicalClaim)
        WHERE {where_str}
        OPTIONAL MATCH (cc)-[:HAS_SUBJECT]->(c:CanonicalConcept)
        RETURN cc {{
            .canonical_claim_id,
            .subject_concept_id,
            .claim_type,
            .value,
            .value_numeric,
            .unit,
            .value_type,
            .scope_key,
            .scope_struct,
            .distinct_documents,
            .total_assertions,
            .confidence_p50,
            .maturity,
            .status,
            .sources_json
        }} AS claim,
        c.canonical_name AS subject_name
        ORDER BY cc.confidence_p50 DESC
        SKIP $offset
        LIMIT $limit
        """
        params["offset"] = offset
        params["limit"] = limit

        results = self._execute_query(data_query, params)

        claims = []
        for r in results:
            claim_data = r["claim"]
            claim_data["subject_name"] = r.get("subject_name")
            claims.append(self._claim_to_response(claim_data))

        return ClaimSearchResponse(
            claims=claims,
            total=total,
            limit=limit,
            offset=offset
        )

    def get_claims_for_concept(
        self,
        concept_id: str,
        claim_types: Optional[List[str]] = None,
        include_conflicting: bool = True
    ) -> List[CanonicalClaimResponse]:
        """
        Get all claims for a concept.

        Args:
            concept_id: Concept ID
            claim_types: Filter by claim types
            include_conflicting: Include conflicting claims

        Returns:
            List of claims
        """
        where_clauses = [
            "cc.tenant_id = $tenant_id",
            "cc.subject_concept_id = $concept_id"
        ]
        params: Dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "concept_id": concept_id
        }

        if claim_types:
            where_clauses.append("cc.claim_type IN $claim_types")
            params["claim_types"] = claim_types

        if not include_conflicting:
            where_clauses.append("cc.maturity <> 'CONFLICTING'")

        where_str = " AND ".join(where_clauses)

        query = f"""
        MATCH (cc:CanonicalClaim)
        WHERE {where_str}
        OPTIONAL MATCH (cc)-[:HAS_SUBJECT]->(c:CanonicalConcept)
        RETURN cc {{
            .canonical_claim_id,
            .subject_concept_id,
            .claim_type,
            .value,
            .value_numeric,
            .unit,
            .value_type,
            .scope_key,
            .scope_struct,
            .distinct_documents,
            .total_assertions,
            .confidence_p50,
            .maturity,
            .status,
            .sources_json
        }} AS claim,
        c.canonical_name AS subject_name
        ORDER BY cc.claim_type, cc.confidence_p50 DESC
        """

        results = self._execute_query(query, params)

        claims = []
        for r in results:
            claim_data = r["claim"]
            claim_data["subject_name"] = r.get("subject_name")
            claims.append(self._claim_to_response(claim_data))

        return claims

    def get_kg_rag_contract(self, concept_id: str) -> KGRAGContractResponse:
        """
        Get KG/RAG Contract for a concept.

        Separates claims into:
        - kg_facts: VALIDATED claims (state directly)
        - rag_suggestions: CANDIDATE/CONTEXT_DEPENDENT (hedge)
        - conflicts: CONFLICTING (acknowledge)

        Args:
            concept_id: Concept ID

        Returns:
            KGRAGContractResponse
        """
        # Get concept name
        concept_query = """
        MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
        RETURN c.canonical_name AS name
        """
        concept_result = self._execute_query(concept_query, {
            "concept_id": concept_id,
            "tenant_id": self.tenant_id
        })
        concept_name = concept_result[0]["name"] if concept_result else None

        # Get all claims
        claims = self.get_claims_for_concept(concept_id, include_conflicting=True)

        # Separate by maturity
        kg_facts = []
        rag_suggestions = []
        conflicts_map: Dict[str, List[CanonicalClaimResponse]] = {}

        for claim in claims:
            if claim.maturity == "VALIDATED":
                # Extract first source for evidence
                evidence = claim.sources[0].excerpt if claim.sources else None

                kg_facts.append(KGFactResponse(
                    claim_type=claim.claim_type,
                    value=claim.value,
                    value_numeric=claim.value_numeric,
                    unit=claim.unit,
                    confidence=claim.confidence_p50,
                    source_count=claim.distinct_documents,
                    evidence=evidence
                ))

            elif claim.maturity in ("CANDIDATE", "CONTEXT_DEPENDENT"):
                sources = [
                    ClaimSourceResponse(
                        document_id=s.document_id,
                        excerpt=s.excerpt,
                        page_number=s.page_number
                    )
                    for s in claim.sources
                ]

                condition = None
                if claim.maturity == "CONTEXT_DEPENDENT":
                    # Try to extract condition from scope
                    if claim.scope_struct:
                        condition = ", ".join(f"{k}={v}" for k, v in claim.scope_struct.items())

                rag_suggestions.append(RAGSuggestionResponse(
                    claim_type=claim.claim_type,
                    value=claim.value,
                    maturity=claim.maturity,
                    confidence=claim.confidence_p50,
                    condition=condition,
                    sources=sources
                ))

            elif claim.maturity == "CONFLICTING":
                key = claim.claim_type
                if key not in conflicts_map:
                    conflicts_map[key] = []
                conflicts_map[key].append(claim)

        # Build conflict infos
        conflicts = []
        for claim_type, conflicting_claims in conflicts_map.items():
            values = list(set(c.value for c in conflicting_claims))
            conflicts.append(ConflictInfo(
                claim_type=claim_type,
                values=values,
                recommendation=f"Multiple values reported for {claim_type}. Present both and note the discrepancy."
            ))

        # Generate LLM prompt hint
        prompt_parts = []
        if kg_facts:
            facts_str = "; ".join(f"{f.claim_type}={f.value}" for f in kg_facts[:5])
            prompt_parts.append(f"VERIFIED facts about {concept_name or concept_id}: {facts_str}")
        if rag_suggestions:
            sugg_str = "; ".join(f"{s.claim_type}={s.value} (unverified)" for s in rag_suggestions[:3])
            prompt_parts.append(f"Unverified claims (use hedging): {sugg_str}")
        if conflicts:
            conf_str = "; ".join(f"{c.claim_type} has conflicting values: {', '.join(c.values)}" for c in conflicts)
            prompt_parts.append(f"Known conflicts: {conf_str}")

        llm_prompt_hint = " | ".join(prompt_parts) if prompt_parts else ""

        return KGRAGContractResponse(
            concept_id=concept_id,
            concept_name=concept_name,
            kg_facts=kg_facts,
            rag_suggestions=rag_suggestions,
            conflicts=conflicts,
            total_claims=len(claims),
            llm_prompt_hint=llm_prompt_hint
        )

    def get_all_conflicts(self) -> ConflictsListResponse:
        """
        Get all conflicting claims.

        Returns:
            ConflictsListResponse with all conflicts
        """
        query = """
        MATCH (cc:CanonicalClaim {tenant_id: $tenant_id, maturity: 'CONFLICTING'})
        OPTIONAL MATCH (cc)-[:HAS_SUBJECT]->(c:CanonicalConcept)
        RETURN cc {
            .canonical_claim_id,
            .subject_concept_id,
            .claim_type,
            .value,
            .value_numeric,
            .unit,
            .value_type,
            .scope_key,
            .distinct_documents,
            .total_assertions,
            .confidence_p50,
            .maturity,
            .status,
            .sources_json
        } AS claim,
        c.canonical_name AS subject_name
        ORDER BY cc.claim_type, cc.subject_concept_id
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        # Group by (subject, claim_type)
        conflicts_map: Dict[tuple, List[CanonicalClaimResponse]] = {}
        for r in results:
            claim_data = r["claim"]
            claim_data["subject_name"] = r.get("subject_name")
            claim = self._claim_to_response(claim_data)

            key = (claim.subject_concept_id, claim.claim_type)
            if key not in conflicts_map:
                conflicts_map[key] = []
            conflicts_map[key].append(claim)

        # Build response
        conflicts = []
        for (subject_id, claim_type), claims in conflicts_map.items():
            values = list(set(c.value for c in claims))
            subject_name = claims[0].subject_name if claims else None

            conflicts.append(ConflictingClaimsResponse(
                claim_type=claim_type,
                subject_concept_id=subject_id,
                subject_name=subject_name,
                conflicting_values=values,
                claims=claims,
                resolution_suggestion="Review source documents to determine authoritative value."
            ))

        return ConflictsListResponse(
            conflicts=conflicts,
            total_conflicts=len(conflicts)
        )


# Singleton-like access
_service_instance: Optional[ClaimService] = None


def get_claim_service(
    tenant_id: str = "default",
    **kwargs
) -> ClaimService:
    """Get or create ClaimService instance."""
    global _service_instance
    if _service_instance is None or _service_instance.tenant_id != tenant_id:
        _service_instance = ClaimService(tenant_id=tenant_id, **kwargs)
    return _service_instance
