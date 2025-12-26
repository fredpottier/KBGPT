"""
Phase 2.12 - Deferred Store

Storage for deferred merge candidates using Neo4j.
Handles TTL, bounded queue, and reevaluation scheduling.

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

from .types import DeferredMergeCandidate, DecisionType, ConceptType, SignalBreakdown
from .config import DEFER_CONFIG, get_defer_ttl

logger = logging.getLogger(__name__)


class DeferredStore:
    """
    Storage for deferred merge candidates.

    Uses Neo4j node type: DeferredMerge
    Supports:
    - TTL-based expiration
    - Bounded queue per tenant
    - Reevaluation scheduling
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize DeferredStore.

        Args:
            neo4j_client: Neo4j client (uses settings if None)
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
        self._ensure_constraints()

    def _ensure_constraints(self) -> None:
        """Ensure Neo4j constraints exist."""
        constraints = [
            "CREATE CONSTRAINT deferred_merge_id IF NOT EXISTS FOR (d:DeferredMerge) REQUIRE d.pair_id IS UNIQUE",
        ]
        try:
            if self.neo4j_client.driver:
                with self.neo4j_client.driver.session() as session:
                    for constraint in constraints:
                        try:
                            session.run(constraint)
                        except Exception:
                            pass  # Constraint may already exist
        except Exception as e:
            logger.warning(f"[DeferredStore] Could not create constraints: {e}")

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def store(self, candidate: DeferredMergeCandidate) -> bool:
        """
        Store a deferred merge candidate.

        Args:
            candidate: The deferred candidate to store

        Returns:
            True if stored successfully
        """
        # Check queue size limit
        current_size = self.get_queue_size()
        if current_size >= DEFER_CONFIG["max_deferred_per_tenant"]:
            logger.warning(
                f"[DeferredStore] Queue full ({current_size}), "
                f"expiring oldest entries"
            )
            self._expire_oldest(count=10)

        query = """
        MERGE (d:DeferredMerge {pair_id: $pair_id})
        SET d.concept_a_id = $concept_a_id,
            d.concept_b_id = $concept_b_id,
            d.concept_a_name = $concept_a_name,
            d.concept_b_name = $concept_b_name,
            d.concept_type = $concept_type,
            d.tenant_id = $tenant_id,
            d.similarity_score = $similarity_score,
            d.signals_json = $signals_json,
            d.has_exact_match = $has_exact_match,
            d.has_acronym_match = $has_acronym_match,
            d.shared_surface_forms = $shared_surface_forms,
            d.doc_count_a = $doc_count_a,
            d.doc_count_b = $doc_count_b,
            d.shared_doc_count = $shared_doc_count,
            d.created_at = $created_at,
            d.last_evaluated_at = $last_evaluated_at,
            d.evaluation_count = $evaluation_count,
            d.expires_at = $expires_at,
            d.status = $status
        RETURN d.pair_id AS pair_id
        """

        params = {
            "pair_id": candidate.pair_id,
            "concept_a_id": candidate.concept_a_id,
            "concept_b_id": candidate.concept_b_id,
            "concept_a_name": candidate.concept_a_name,
            "concept_b_name": candidate.concept_b_name,
            "concept_type": candidate.concept_type.value,
            "tenant_id": candidate.tenant_id,
            "similarity_score": candidate.similarity_score,
            "signals_json": candidate.signals.model_dump_json(),
            "has_exact_match": candidate.has_exact_match,
            "has_acronym_match": candidate.has_acronym_match,
            "shared_surface_forms": candidate.shared_surface_forms,
            "doc_count_a": candidate.doc_count_a,
            "doc_count_b": candidate.doc_count_b,
            "shared_doc_count": candidate.shared_doc_count,
            "created_at": candidate.created_at.isoformat(),
            "last_evaluated_at": candidate.last_evaluated_at.isoformat(),
            "evaluation_count": candidate.evaluation_count,
            "expires_at": candidate.expires_at.isoformat(),
            "status": candidate.status.value,
        }

        try:
            result = self._execute_query(query, params)
            logger.debug(f"[DeferredStore] Stored deferred candidate: {candidate.pair_id}")
            return len(result) > 0
        except Exception as e:
            logger.error(f"[DeferredStore] Failed to store candidate: {e}")
            return False

    def get(self, pair_id: str) -> Optional[DeferredMergeCandidate]:
        """
        Get a deferred candidate by pair ID.

        Args:
            pair_id: The pair ID

        Returns:
            DeferredMergeCandidate or None
        """
        query = """
        MATCH (d:DeferredMerge {pair_id: $pair_id, tenant_id: $tenant_id})
        RETURN d
        """
        result = self._execute_query(query, {
            "pair_id": pair_id,
            "tenant_id": self.tenant_id
        })

        if not result:
            return None

        return self._node_to_candidate(result[0]["d"])

    def get_pending(
        self,
        limit: int = 100,
        min_doc_count: int = 0
    ) -> List[DeferredMergeCandidate]:
        """
        Get pending deferred candidates for reevaluation.

        Args:
            limit: Max candidates to return
            min_doc_count: Minimum combined doc count

        Returns:
            List of deferred candidates
        """
        query = """
        MATCH (d:DeferredMerge {tenant_id: $tenant_id, status: 'DEFER'})
        WHERE d.expires_at > datetime()
          AND (d.doc_count_a + d.doc_count_b) >= $min_doc_count
        RETURN d
        ORDER BY d.similarity_score DESC
        LIMIT $limit
        """
        results = self._execute_query(query, {
            "tenant_id": self.tenant_id,
            "min_doc_count": min_doc_count,
            "limit": limit
        })

        return [self._node_to_candidate(r["d"]) for r in results]

    def get_expired(self, limit: int = 100) -> List[DeferredMergeCandidate]:
        """
        Get expired deferred candidates.

        Args:
            limit: Max candidates to return

        Returns:
            List of expired candidates
        """
        query = """
        MATCH (d:DeferredMerge {tenant_id: $tenant_id})
        WHERE d.expires_at <= datetime() AND d.status = 'DEFER'
        RETURN d
        LIMIT $limit
        """
        results = self._execute_query(query, {
            "tenant_id": self.tenant_id,
            "limit": limit
        })

        return [self._node_to_candidate(r["d"]) for r in results]

    def update_status(
        self,
        pair_id: str,
        status: DecisionType,
        increment_eval: bool = True
    ) -> bool:
        """
        Update status of a deferred candidate.

        Args:
            pair_id: The pair ID
            status: New status
            increment_eval: Whether to increment evaluation count

        Returns:
            True if updated
        """
        query = """
        MATCH (d:DeferredMerge {pair_id: $pair_id, tenant_id: $tenant_id})
        SET d.status = $status,
            d.last_evaluated_at = datetime(),
            d.evaluation_count = d.evaluation_count + $increment
        RETURN d.pair_id AS pair_id
        """
        result = self._execute_query(query, {
            "pair_id": pair_id,
            "tenant_id": self.tenant_id,
            "status": status.value,
            "increment": 1 if increment_eval else 0
        })
        return len(result) > 0

    def update_doc_counts(
        self,
        pair_id: str,
        doc_count_a: int,
        doc_count_b: int,
        shared_doc_count: int
    ) -> bool:
        """
        Update document counts for a deferred candidate.

        Args:
            pair_id: The pair ID
            doc_count_a: Doc count for concept A
            doc_count_b: Doc count for concept B
            shared_doc_count: Docs where both appear

        Returns:
            True if updated
        """
        query = """
        MATCH (d:DeferredMerge {pair_id: $pair_id, tenant_id: $tenant_id})
        SET d.doc_count_a = $doc_count_a,
            d.doc_count_b = $doc_count_b,
            d.shared_doc_count = $shared_doc_count
        RETURN d.pair_id AS pair_id
        """
        result = self._execute_query(query, {
            "pair_id": pair_id,
            "tenant_id": self.tenant_id,
            "doc_count_a": doc_count_a,
            "doc_count_b": doc_count_b,
            "shared_doc_count": shared_doc_count
        })
        return len(result) > 0

    def delete(self, pair_id: str) -> bool:
        """
        Delete a deferred candidate.

        Args:
            pair_id: The pair ID

        Returns:
            True if deleted
        """
        query = """
        MATCH (d:DeferredMerge {pair_id: $pair_id, tenant_id: $tenant_id})
        DELETE d
        RETURN count(d) AS deleted
        """
        result = self._execute_query(query, {
            "pair_id": pair_id,
            "tenant_id": self.tenant_id
        })
        return result[0]["deleted"] > 0 if result else False

    def delete_expired(self) -> int:
        """
        Delete all expired candidates.

        Returns:
            Number of deleted candidates
        """
        query = """
        MATCH (d:DeferredMerge {tenant_id: $tenant_id})
        WHERE d.expires_at <= datetime()
        DELETE d
        RETURN count(d) AS deleted
        """
        result = self._execute_query(query, {"tenant_id": self.tenant_id})
        deleted = result[0]["deleted"] if result else 0
        logger.info(f"[DeferredStore] Deleted {deleted} expired candidates")
        return deleted

    def get_queue_size(self) -> int:
        """Get current queue size."""
        query = """
        MATCH (d:DeferredMerge {tenant_id: $tenant_id, status: 'DEFER'})
        RETURN count(d) AS count
        """
        result = self._execute_query(query, {"tenant_id": self.tenant_id})
        return result[0]["count"] if result else 0

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        query = """
        MATCH (d:DeferredMerge {tenant_id: $tenant_id})
        RETURN
            count(d) AS total,
            sum(CASE WHEN d.status = 'DEFER' THEN 1 ELSE 0 END) AS pending,
            sum(CASE WHEN d.status = 'AUTO' THEN 1 ELSE 0 END) AS resolved_auto,
            sum(CASE WHEN d.status = 'REJECT' THEN 1 ELSE 0 END) AS rejected,
            sum(CASE WHEN d.expires_at <= datetime() THEN 1 ELSE 0 END) AS expired
        """
        result = self._execute_query(query, {"tenant_id": self.tenant_id})
        if result:
            return {
                "total": result[0]["total"],
                "pending": result[0]["pending"],
                "resolved_auto": result[0]["resolved_auto"],
                "rejected": result[0]["rejected"],
                "expired": result[0]["expired"],
            }
        return {"total": 0, "pending": 0, "resolved_auto": 0, "rejected": 0, "expired": 0}

    def _expire_oldest(self, count: int = 10) -> int:
        """Expire oldest entries to make room."""
        query = """
        MATCH (d:DeferredMerge {tenant_id: $tenant_id, status: 'DEFER'})
        WITH d ORDER BY d.created_at ASC LIMIT $count
        SET d.status = 'REJECT'
        RETURN count(d) AS expired
        """
        result = self._execute_query(query, {
            "tenant_id": self.tenant_id,
            "count": count
        })
        return result[0]["expired"] if result else 0

    def _node_to_candidate(self, node: Dict[str, Any]) -> DeferredMergeCandidate:
        """Convert Neo4j node to DeferredMergeCandidate."""
        import json

        signals_data = json.loads(node.get("signals_json", "{}"))
        signals = SignalBreakdown(**signals_data)

        return DeferredMergeCandidate(
            pair_id=node["pair_id"],
            concept_a_id=node["concept_a_id"],
            concept_b_id=node["concept_b_id"],
            concept_a_name=node["concept_a_name"],
            concept_b_name=node["concept_b_name"],
            concept_type=ConceptType(node["concept_type"]),
            tenant_id=node["tenant_id"],
            similarity_score=node["similarity_score"],
            signals=signals,
            has_exact_match=node.get("has_exact_match", False),
            has_acronym_match=node.get("has_acronym_match", False),
            shared_surface_forms=node.get("shared_surface_forms", []),
            doc_count_a=node.get("doc_count_a", 0),
            doc_count_b=node.get("doc_count_b", 0),
            shared_doc_count=node.get("shared_doc_count", 0),
            created_at=datetime.fromisoformat(node["created_at"]),
            last_evaluated_at=datetime.fromisoformat(node["last_evaluated_at"]),
            evaluation_count=node.get("evaluation_count", 1),
            expires_at=datetime.fromisoformat(node["expires_at"]),
            status=DecisionType(node["status"]),
        )


# Singleton
_store_instance: Optional[DeferredStore] = None


def get_deferred_store(tenant_id: str = "default") -> DeferredStore:
    """Get or create DeferredStore instance."""
    global _store_instance
    if _store_instance is None or _store_instance.tenant_id != tenant_id:
        _store_instance = DeferredStore(tenant_id=tenant_id)
    return _store_instance
