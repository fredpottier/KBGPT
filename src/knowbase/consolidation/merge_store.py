"""
Merge Store for Corpus Entity Resolution

Handles storage of merge proposals and execution of merges in Neo4j.
All merges are reversible via MERGED_INTO edges.

Author: Claude Code
Date: 2026-01-01
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

from .types import MergeProposal, MergeResult, DecisionType

logger = logging.getLogger(__name__)


# Typed edge types that need rewiring on merge
TYPED_EDGE_TYPES = [
    "REQUIRES", "ENABLES", "APPLIES_TO", "PART_OF",
    "CAUSES", "PREVENTS", "CONFLICTS_WITH", "GOVERNED_BY",
    "DEFINES", "MITIGATES"
]


class MergeStore:
    """
    Handles merge operations and audit storage in Neo4j.

    Features:
    - Store MergeProposal nodes for audit
    - Execute merges with MERGED_INTO edges
    - Rewire typed edges to target
    - Rollback support
    """

    def __init__(self, tenant_id: str = "default"):
        """Initialize MergeStore."""
        self.tenant_id = tenant_id
        settings = get_settings()
        self.neo4j = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j.driver:
            raise RuntimeError("Neo4j driver not connected")

        with self.neo4j.driver.session(database="neo4j") as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _execute_write(self, query: str, params: Dict[str, Any]) -> Any:
        """Execute a write query."""
        if not self.neo4j.driver:
            raise RuntimeError("Neo4j driver not connected")

        with self.neo4j.driver.session(database="neo4j") as session:
            result = session.run(query, params)
            return result.single()

    def store_proposal(self, proposal: MergeProposal) -> bool:
        """
        Store a merge proposal in Neo4j for audit.

        Args:
            proposal: The merge proposal

        Returns:
            True if stored successfully
        """
        query = """
        MERGE (p:MergeProposal {proposal_id: $proposal_id})
        SET p.source_id = $source_id,
            p.target_id = $target_id,
            p.source_name = $source_name,
            p.target_name = $target_name,
            p.lex_score = $lex_score,
            p.sem_score = $sem_score,
            p.compat_score = $compat_score,
            p.decision = $decision,
            p.decision_reason = $decision_reason,
            p.tenant_id = $tenant_id,
            p.created_at = datetime($created_at),
            p.applied = $applied
        RETURN p.proposal_id AS id
        """

        try:
            self._execute_write(query, {
                "proposal_id": proposal.proposal_id,
                "source_id": proposal.source_id,
                "target_id": proposal.target_id,
                "source_name": proposal.source_name,
                "target_name": proposal.target_name,
                "lex_score": proposal.lex_score,
                "sem_score": proposal.sem_score,
                "compat_score": proposal.compat_score,
                "decision": proposal.decision.value,
                "decision_reason": proposal.decision_reason,
                "tenant_id": proposal.tenant_id,
                "created_at": proposal.created_at.isoformat(),
                "applied": proposal.applied,
            })
            return True
        except Exception as e:
            logger.error(f"[MergeStore] Failed to store proposal: {e}")
            return False

    def execute_merge(
        self,
        source_id: str,
        target_id: str,
        lex_score: float,
        sem_score: float,
        compat_score: float,
        merge_reason: str,
        merged_by: str = "auto"
    ) -> MergeResult:
        """
        Execute a merge from source to target.

        Steps:
        1. Create MERGED_INTO edge
        2. Update source status to MERGED
        3. Rewire outgoing typed edges
        4. Rewire incoming typed edges
        5. Rewire INSTANCE_OF edges

        Args:
            source_id: Source concept ID (will be merged into target)
            target_id: Target concept ID (will absorb source)
            lex_score: Lexical similarity score
            sem_score: Semantic similarity score
            compat_score: Type compatibility score
            merge_reason: Reason for merge
            merged_by: "auto" or "manual"

        Returns:
            MergeResult with stats
        """
        try:
            # Step 1: Create MERGED_INTO edge and update source
            merge_score = 0.4 * lex_score + 0.4 * sem_score + 0.2 * compat_score

            create_merge_query = """
            MATCH (source:CanonicalConcept {canonical_id: $source_id, tenant_id: $tenant_id})
            MATCH (target:CanonicalConcept {canonical_id: $target_id, tenant_id: $tenant_id})

            // Create MERGED_INTO edge
            CREATE (source)-[:MERGED_INTO {
                merged_at: datetime(),
                merge_score: $merge_score,
                merge_reason: $merge_reason,
                lex_score: $lex_score,
                sem_score: $sem_score,
                compat_score: $compat_score,
                merged_by: $merged_by,
                reversible: true
            }]->(target)

            // Update source
            SET source.er_status = 'MERGED',
                source.merged_into_id = $target_id,
                source.merged_at = datetime()

            // Update target (track merged sources)
            SET target.merged_from = coalesce(target.merged_from, []) + $source_id

            RETURN source.canonical_name AS source_name,
                   target.canonical_name AS target_name
            """

            result = self._execute_write(create_merge_query, {
                "source_id": source_id,
                "target_id": target_id,
                "tenant_id": self.tenant_id,
                "merge_score": merge_score,
                "merge_reason": merge_reason,
                "lex_score": lex_score,
                "sem_score": sem_score,
                "compat_score": compat_score,
                "merged_by": merged_by,
            })

            if not result:
                return MergeResult(
                    success=False,
                    source_id=source_id,
                    target_id=target_id,
                    merge_reason=merge_reason,
                    error="Source or target concept not found"
                )

            # Step 2: Rewire outgoing typed edges
            edges_out = self._rewire_outgoing_edges(source_id, target_id)

            # Step 3: Rewire incoming typed edges
            edges_in = self._rewire_incoming_edges(source_id, target_id)

            # Step 4: Rewire INSTANCE_OF edges
            instance_of_count = self._rewire_instance_of(source_id, target_id)

            logger.info(
                f"[MergeStore] Merged {source_id} -> {target_id}: "
                f"edges_out={edges_out}, edges_in={edges_in}, "
                f"instance_of={instance_of_count}"
            )

            return MergeResult(
                success=True,
                source_id=source_id,
                target_id=target_id,
                merge_reason=merge_reason,
                edges_rewired=edges_out + edges_in,
                instance_of_rewired=instance_of_count,
            )

        except Exception as e:
            logger.error(f"[MergeStore] Merge failed: {e}")
            return MergeResult(
                success=False,
                source_id=source_id,
                target_id=target_id,
                merge_reason=merge_reason,
                error=str(e)
            )

    def _rewire_outgoing_edges(self, source_id: str, target_id: str) -> int:
        """Rewire outgoing typed edges from source to target."""
        count = 0

        for edge_type in TYPED_EDGE_TYPES:
            query = f"""
            MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
                  -[r:{edge_type}]->(other:CanonicalConcept)
            WHERE other.canonical_id <> $target_id

            MATCH (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})

            // Create new edge on target
            MERGE (target)-[new_r:{edge_type}]->(other)
            ON CREATE SET new_r = properties(r),
                          new_r.rewired_from = $source_id,
                          new_r.rewired_at = datetime()

            // Delete old edge
            DELETE r

            RETURN count(*) AS count
            """

            try:
                result = self._execute_write(query, {
                    "source_id": source_id,
                    "target_id": target_id,
                    "tenant_id": self.tenant_id,
                })
                if result and result["count"]:
                    count += result["count"]
            except Exception as e:
                logger.warning(f"[MergeStore] Rewire out {edge_type} failed: {e}")

        return count

    def _rewire_incoming_edges(self, source_id: str, target_id: str) -> int:
        """Rewire incoming typed edges to source -> target."""
        count = 0

        for edge_type in TYPED_EDGE_TYPES:
            query = f"""
            MATCH (other:CanonicalConcept)-[r:{edge_type}]->
                  (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
            WHERE other.canonical_id <> $target_id

            MATCH (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})

            // Create new edge to target
            MERGE (other)-[new_r:{edge_type}]->(target)
            ON CREATE SET new_r = properties(r),
                          new_r.rewired_from = $source_id,
                          new_r.rewired_at = datetime()

            // Delete old edge
            DELETE r

            RETURN count(*) AS count
            """

            try:
                result = self._execute_write(query, {
                    "source_id": source_id,
                    "target_id": target_id,
                    "tenant_id": self.tenant_id,
                })
                if result and result["count"]:
                    count += result["count"]
            except Exception as e:
                logger.warning(f"[MergeStore] Rewire in {edge_type} failed: {e}")

        return count

    def _rewire_instance_of(self, source_id: str, target_id: str) -> int:
        """Rewire INSTANCE_OF edges from ProtoConcepts."""
        query = """
        MATCH (proto:ProtoConcept)-[r:INSTANCE_OF]->
              (source:CanonicalConcept {canonical_id: $source_id, tenant_id: $tenant_id})

        MATCH (target:CanonicalConcept {canonical_id: $target_id, tenant_id: $tenant_id})

        // Create new INSTANCE_OF to target
        MERGE (proto)-[:INSTANCE_OF]->(target)

        // Delete old INSTANCE_OF
        DELETE r

        RETURN count(*) AS count
        """

        try:
            result = self._execute_write(query, {
                "source_id": source_id,
                "target_id": target_id,
                "tenant_id": self.tenant_id,
            })
            return result["count"] if result else 0
        except Exception as e:
            logger.warning(f"[MergeStore] Rewire INSTANCE_OF failed: {e}")
            return 0

    def rollback_merge(self, source_id: str) -> bool:
        """
        Rollback a merge operation.

        Restores source concept to STANDALONE and rewires edges back.

        Args:
            source_id: Source concept ID that was merged

        Returns:
            True if rollback successful
        """
        try:
            # Get merge info
            info_query = """
            MATCH (source:CanonicalConcept {canonical_id: $source_id, tenant_id: $tenant_id})
                  -[m:MERGED_INTO]->(target:CanonicalConcept)
            RETURN target.canonical_id AS target_id
            """

            result = self._execute_write(info_query, {
                "source_id": source_id,
                "tenant_id": self.tenant_id,
            })

            if not result:
                logger.warning(f"[MergeStore] No merge found for {source_id}")
                return False

            target_id = result["target_id"]

            # Rollback outgoing edges
            self._rollback_rewired_edges_outgoing(source_id, target_id)

            # Rollback incoming edges
            self._rollback_rewired_edges_incoming(source_id, target_id)

            # Restore source status
            restore_query = """
            MATCH (source:CanonicalConcept {canonical_id: $source_id, tenant_id: $tenant_id})
                  -[m:MERGED_INTO]->(target:CanonicalConcept)

            // Remove source from target's merged_from
            SET target.merged_from = [x IN target.merged_from WHERE x <> $source_id]

            // Restore source
            SET source.er_status = 'STANDALONE'
            REMOVE source.merged_into_id
            REMOVE source.merged_at

            // Delete MERGED_INTO
            DELETE m

            RETURN true AS success
            """

            self._execute_write(restore_query, {
                "source_id": source_id,
                "tenant_id": self.tenant_id,
            })

            logger.info(f"[MergeStore] Rolled back merge: {source_id}")
            return True

        except Exception as e:
            logger.error(f"[MergeStore] Rollback failed: {e}")
            return False

    def _rollback_rewired_edges_outgoing(self, source_id: str, target_id: str) -> int:
        """Rollback outgoing edges that were rewired."""
        count = 0

        for edge_type in TYPED_EDGE_TYPES:
            query = f"""
            MATCH (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
                  -[r:{edge_type}]->(other:CanonicalConcept)
            WHERE r.rewired_from = $source_id

            MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})

            // Recreate on source
            CREATE (source)-[new_r:{edge_type}]->(other)
            SET new_r = properties(r)
            REMOVE new_r.rewired_from
            REMOVE new_r.rewired_at

            // Delete from target
            DELETE r

            RETURN count(*) AS count
            """

            try:
                result = self._execute_write(query, {
                    "source_id": source_id,
                    "target_id": target_id,
                    "tenant_id": self.tenant_id,
                })
                if result and result["count"]:
                    count += result["count"]
            except Exception:
                pass

        return count

    def _rollback_rewired_edges_incoming(self, source_id: str, target_id: str) -> int:
        """Rollback incoming edges that were rewired."""
        count = 0

        for edge_type in TYPED_EDGE_TYPES:
            query = f"""
            MATCH (other:CanonicalConcept)-[r:{edge_type}]->
                  (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
            WHERE r.rewired_from = $source_id

            MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})

            // Recreate on source
            CREATE (other)-[new_r:{edge_type}]->(source)
            SET new_r = properties(r)
            REMOVE new_r.rewired_from
            REMOVE new_r.rewired_at

            // Delete from target
            DELETE r

            RETURN count(*) AS count
            """

            try:
                result = self._execute_write(query, {
                    "source_id": source_id,
                    "target_id": target_id,
                    "tenant_id": self.tenant_id,
                })
                if result and result["count"]:
                    count += result["count"]
            except Exception:
                pass

        return count

    def get_pending_proposals(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get pending merge proposals for manual review."""
        query = """
        MATCH (p:MergeProposal {tenant_id: $tenant_id, applied: false})
        WHERE p.decision = 'propose_only'
        RETURN p.proposal_id AS proposal_id,
               p.source_id AS source_id,
               p.target_id AS target_id,
               p.source_name AS source_name,
               p.target_name AS target_name,
               p.lex_score AS lex_score,
               p.sem_score AS sem_score,
               p.compat_score AS compat_score,
               p.decision_reason AS reason,
               p.created_at AS created_at
        ORDER BY p.lex_score DESC, p.sem_score DESC
        LIMIT $limit
        """

        return self._execute_query(query, {
            "tenant_id": self.tenant_id,
            "limit": limit,
        })

    def apply_proposal(self, proposal_id: str, approved_by: str) -> MergeResult:
        """Apply a pending proposal after manual approval."""
        # Get proposal
        query = """
        MATCH (p:MergeProposal {proposal_id: $proposal_id, tenant_id: $tenant_id})
        RETURN p.source_id AS source_id,
               p.target_id AS target_id,
               p.lex_score AS lex_score,
               p.sem_score AS sem_score,
               p.compat_score AS compat_score,
               p.decision_reason AS reason
        """

        results = self._execute_query(query, {
            "proposal_id": proposal_id,
            "tenant_id": self.tenant_id,
        })

        if not results:
            return MergeResult(
                success=False,
                source_id="",
                target_id="",
                merge_reason="",
                error=f"Proposal {proposal_id} not found"
            )

        proposal = results[0]

        # Execute merge
        result = self.execute_merge(
            source_id=proposal["source_id"],
            target_id=proposal["target_id"],
            lex_score=proposal["lex_score"],
            sem_score=proposal["sem_score"],
            compat_score=proposal["compat_score"],
            merge_reason=proposal["reason"],
            merged_by=approved_by
        )

        # Mark proposal as applied
        if result.success:
            update_query = """
            MATCH (p:MergeProposal {proposal_id: $proposal_id})
            SET p.applied = true,
                p.applied_at = datetime(),
                p.applied_by = $approved_by
            """
            self._execute_write(update_query, {
                "proposal_id": proposal_id,
                "approved_by": approved_by,
            })

        return result

    def get_merge_stats(self) -> Dict[str, Any]:
        """Get statistics about merges."""
        query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WITH count(c) AS total,
             sum(CASE WHEN c.er_status = 'MERGED' THEN 1 ELSE 0 END) AS merged,
             sum(CASE WHEN c.er_status = 'STANDALONE' OR c.er_status IS NULL THEN 1 ELSE 0 END) AS standalone

        OPTIONAL MATCH (p:MergeProposal {tenant_id: $tenant_id})
        WITH total, merged, standalone, count(p) AS proposals,
             sum(CASE WHEN p.applied THEN 1 ELSE 0 END) AS applied_proposals

        RETURN total, merged, standalone, proposals, applied_proposals
        """

        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        if results:
            r = results[0]
            return {
                "total_concepts": r["total"],
                "merged_concepts": r["merged"],
                "standalone_concepts": r["standalone"],
                "total_proposals": r["proposals"],
                "applied_proposals": r["applied_proposals"],
            }

        return {}

    def close(self):
        """Close Neo4j connection."""
        self.neo4j.close()


# Singleton
_store_instance: Optional[MergeStore] = None


def get_merge_store(tenant_id: str = "default") -> MergeStore:
    """Get or create MergeStore instance."""
    global _store_instance
    if _store_instance is None or _store_instance.tenant_id != tenant_id:
        _store_instance = MergeStore(tenant_id=tenant_id)
    return _store_instance
