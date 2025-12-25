"""
Phase 2.11 - CanonicalClaim Writer for Neo4j

Persists CanonicalClaim nodes to Neo4j with MERGE for upsert.
Links to RawClaims via SUPPORTS edges and manages conflict relationships.

Author: Claude Code
Date: 2025-12-24
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    CanonicalClaim,
    ClaimMaturity,
    ClaimValueType,
)

logger = logging.getLogger(__name__)


class CanonicalClaimWriter:
    """
    Writes CanonicalClaim nodes to Neo4j.

    Implements:
    - MERGE for upsert (create or update)
    - SUPPORTS edges linking to RawClaims
    - CONFLICTS_WITH edges for conflicting claims
    - SUPERSEDES edges for temporal supersession
    - Edges to CanonicalConcept via HAS_SUBJECT
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize writer.

        Args:
            neo4j_client: Neo4j client instance (creates one if not provided)
            tenant_id: Tenant ID for multi-tenancy
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

        self._stats = {
            "created": 0,
            "updated": 0,
            "supports_edges": 0,
            "conflict_edges": 0,
            "supersedes_edges": 0,
            "errors": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def write_claim(self, claim: CanonicalClaim) -> str:
        """
        Write a CanonicalClaim to Neo4j.

        Uses MERGE to create or update based on canonical_claim_id.

        Args:
            claim: CanonicalClaim instance

        Returns:
            canonical_claim_id
        """
        try:
            # MERGE the canonical claim
            self._merge_claim_node(claim)

            # Link to subject concept
            self._link_to_subject(claim)

            # Link to supporting RawClaims
            self._link_to_raw_claims(claim)

            # Handle conflicts
            if claim.conflicts_with:
                self._create_conflict_edges(claim)

            # Handle supersession
            if claim.supersedes:
                self._create_supersedes_edge(claim)

            logger.debug(f"[CanonicalClaimWriter] Written: {claim.canonical_claim_id}")
            return claim.canonical_claim_id

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"[CanonicalClaimWriter] Error writing claim: {e}")
            raise

    def _merge_claim_node(self, claim: CanonicalClaim) -> None:
        """Merge CanonicalClaim node (upsert)."""
        query = """
        MERGE (cc:CanonicalClaim {canonical_claim_id: $canonical_claim_id})
        ON CREATE SET
            cc.tenant_id = $tenant_id,
            cc.subject_concept_id = $subject_concept_id,
            cc.claim_type = $claim_type,
            cc.value = $value,
            cc.value_numeric = $value_numeric,
            cc.unit = $unit,
            cc.value_type = $value_type,
            cc.scope_struct = $scope_struct_json,
            cc.scope_key = $scope_key,
            cc.valid_from = $valid_from,
            cc.valid_until = $valid_until,
            cc.distinct_documents = $distinct_documents,
            cc.total_assertions = $total_assertions,
            cc.confidence_p50 = $confidence_p50,
            cc.maturity = $maturity,
            cc.status = $status,
            cc.sources_json = $sources_json,
            cc.created_at = datetime($created_at),
            cc.last_seen_utc = datetime($last_seen_utc),
            cc._created = true
        ON MATCH SET
            cc.value = $value,
            cc.value_numeric = $value_numeric,
            cc.unit = $unit,
            cc.distinct_documents = $distinct_documents,
            cc.total_assertions = $total_assertions,
            cc.confidence_p50 = $confidence_p50,
            cc.maturity = $maturity,
            cc.status = $status,
            cc.sources_json = $sources_json,
            cc.last_seen_utc = datetime($last_seen_utc),
            cc._created = false
        RETURN cc._created AS created
        """

        # Serialize sources
        sources_data = [
            {
                "document_id": s.document_id,
                "excerpt": s.excerpt,
                "page_number": s.page_number
            }
            for s in claim.sources
        ]

        # Handle value_type enum
        value_type_str = claim.value_type.value if isinstance(claim.value_type, ClaimValueType) else str(claim.value_type)
        maturity_str = claim.maturity.value if isinstance(claim.maturity, ClaimMaturity) else str(claim.maturity)

        params = {
            "canonical_claim_id": claim.canonical_claim_id,
            "tenant_id": claim.tenant_id,
            "subject_concept_id": claim.subject_concept_id,
            "claim_type": claim.claim_type,
            "value": claim.value,
            "value_numeric": claim.value_numeric,
            "unit": claim.unit,
            "value_type": value_type_str,
            "scope_struct_json": json.dumps(claim.scope_struct),
            "scope_key": claim.scope_key,
            "valid_from": claim.valid_from.isoformat() if claim.valid_from else None,
            "valid_until": claim.valid_until.isoformat() if claim.valid_until else None,
            "distinct_documents": claim.distinct_documents,
            "total_assertions": claim.total_assertions,
            "confidence_p50": claim.confidence_p50,
            "maturity": maturity_str,
            "status": claim.status,
            "sources_json": json.dumps(sources_data),
            "created_at": claim.created_at.isoformat() if claim.created_at else datetime.utcnow().isoformat(),
            "last_seen_utc": claim.last_seen_utc.isoformat() if claim.last_seen_utc else datetime.utcnow().isoformat()
        }

        results = self._execute_query(query, params)
        if results and results[0].get("created"):
            self._stats["created"] += 1
        else:
            self._stats["updated"] += 1

    def _link_to_subject(self, claim: CanonicalClaim) -> None:
        """Create HAS_SUBJECT edge to CanonicalConcept."""
        query = """
        MATCH (cc:CanonicalClaim {canonical_claim_id: $canonical_claim_id})
        MATCH (c:CanonicalConcept {canonical_id: $subject_concept_id, tenant_id: $tenant_id})
        MERGE (cc)-[:HAS_SUBJECT]->(c)
        """

        self._execute_query(query, {
            "canonical_claim_id": claim.canonical_claim_id,
            "subject_concept_id": claim.subject_concept_id,
            "tenant_id": claim.tenant_id
        })

    def _link_to_raw_claims(self, claim: CanonicalClaim) -> None:
        """Create SUPPORTS edges from RawClaims to CanonicalClaim."""
        query = """
        MATCH (cc:CanonicalClaim {canonical_claim_id: $canonical_claim_id})
        MATCH (rc:RawClaim)
        WHERE rc.tenant_id = $tenant_id
          AND rc.subject_concept_id = $subject_concept_id
          AND rc.claim_type = $claim_type
          AND rc.scope_key = $scope_key
        MERGE (rc)-[:SUPPORTS]->(cc)
        RETURN count(rc) AS count
        """

        results = self._execute_query(query, {
            "canonical_claim_id": claim.canonical_claim_id,
            "tenant_id": claim.tenant_id,
            "subject_concept_id": claim.subject_concept_id,
            "claim_type": claim.claim_type,
            "scope_key": claim.scope_key
        })

        if results:
            self._stats["supports_edges"] += results[0].get("count", 0)

    def _create_conflict_edges(self, claim: CanonicalClaim) -> None:
        """Create CONFLICTS_WITH edges between conflicting claims."""
        for conflict_id in claim.conflicts_with:
            query = """
            MATCH (cc1:CanonicalClaim {canonical_claim_id: $claim_id})
            MATCH (cc2:CanonicalClaim {canonical_claim_id: $conflict_id})
            MERGE (cc1)-[:CONFLICTS_WITH]->(cc2)
            """
            self._execute_query(query, {
                "claim_id": claim.canonical_claim_id,
                "conflict_id": conflict_id
            })
            self._stats["conflict_edges"] += 1

    def _create_supersedes_edge(self, claim: CanonicalClaim) -> None:
        """Create SUPERSEDES edge to the superseded claim."""
        query = """
        MATCH (cc1:CanonicalClaim {canonical_claim_id: $claim_id})
        MATCH (cc2:CanonicalClaim {canonical_claim_id: $superseded_id})
        MERGE (cc1)-[:SUPERSEDES]->(cc2)
        SET cc2.maturity = 'SUPERSEDED', cc2.status = 'superseded'
        """
        self._execute_query(query, {
            "claim_id": claim.canonical_claim_id,
            "superseded_id": claim.supersedes
        })
        self._stats["supersedes_edges"] += 1

    def write_batch(self, claims: List[CanonicalClaim]) -> List[str]:
        """
        Write multiple CanonicalClaims.

        Args:
            claims: List of CanonicalClaim instances

        Returns:
            List of written canonical_claim_ids
        """
        written_ids = []
        for claim in claims:
            try:
                claim_id = self.write_claim(claim)
                written_ids.append(claim_id)
            except Exception as e:
                logger.error(f"[CanonicalClaimWriter] Error writing claim {claim.canonical_claim_id}: {e}")

        logger.info(
            f"[CanonicalClaimWriter] Written {len(written_ids)}/{len(claims)} claims "
            f"(created={self._stats['created']}, updated={self._stats['updated']})"
        )

        return written_ids

    def get_stats(self) -> Dict[str, int]:
        """Get write statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "created": 0,
            "updated": 0,
            "supports_edges": 0,
            "conflict_edges": 0,
            "supersedes_edges": 0,
            "errors": 0
        }


# Singleton-like access
_writer_instance: Optional[CanonicalClaimWriter] = None


def get_canonical_claim_writer(
    tenant_id: str = "default",
    **kwargs
) -> CanonicalClaimWriter:
    """Get or create CanonicalClaimWriter instance."""
    global _writer_instance
    if _writer_instance is None or _writer_instance.tenant_id != tenant_id:
        _writer_instance = CanonicalClaimWriter(tenant_id=tenant_id, **kwargs)
    return _writer_instance
