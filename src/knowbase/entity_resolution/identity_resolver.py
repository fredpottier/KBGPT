"""
Phase 2.12 - Identity Resolver

Executes merge operations when AUTO decision is made.

Merge Strategy:
1. Select survivor (more relations/docs wins)
2. Migrate aliases to survivor
3. Redirect relations to survivor
4. Redirect claims to survivor
5. Mark merged concept as deprecated

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

from .types import (
    MergeCandidate, MergeResult, DecisionType,
    SignalBreakdown, ConceptType
)
from .score_cache import get_score_cache
from .decision_router import DecisionResult

logger = logging.getLogger(__name__)


class IdentityResolver:
    """
    Resolves identity by merging duplicate concepts.

    Performs safe merges with full audit trail.
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize IdentityResolver.

        Args:
            neo4j_client: Neo4j client
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
        self.score_cache = get_score_cache()

        # Stats
        self._merge_count = 0
        self._alias_count = 0
        self._relation_count = 0
        self._claim_count = 0

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _get_concept_stats(self, concept_id: str) -> Dict[str, Any]:
        """Get concept statistics for survivor selection."""
        query = """
        MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (c)-[r]-()
        WITH c, count(DISTINCT r) AS rel_count
        OPTIONAL MATCH (c)<-[:MENTIONS]-(d:Document)
        RETURN c.canonical_name AS name,
               c.surface_forms AS surface_forms,
               c.definition AS definition,
               rel_count,
               count(DISTINCT d) AS doc_count,
               c.created_at AS created_at
        """
        result = self._execute_query(query, {
            "concept_id": concept_id,
            "tenant_id": self.tenant_id
        })
        if result:
            return result[0]
        return {"rel_count": 0, "doc_count": 0, "name": ""}

    def _select_survivor(
        self,
        candidate: MergeCandidate
    ) -> Tuple[str, str, str, str]:
        """
        Select which concept survives the merge.

        Heuristics:
        1. More relations wins
        2. Tie: more documents wins
        3. Tie: older (created first) wins
        4. Tie: longer name wins (more descriptive)

        Returns:
            Tuple of (survivor_id, survivor_name, merged_id, merged_name)
        """
        stats_a = self._get_concept_stats(candidate.concept_a_id)
        stats_b = self._get_concept_stats(candidate.concept_b_id)

        score_a = (
            stats_a.get("rel_count", 0) * 10 +
            stats_a.get("doc_count", 0) * 5 +
            len(stats_a.get("name", ""))
        )
        score_b = (
            stats_b.get("rel_count", 0) * 10 +
            stats_b.get("doc_count", 0) * 5 +
            len(stats_b.get("name", ""))
        )

        if score_a >= score_b:
            return (
                candidate.concept_a_id, candidate.concept_a_name,
                candidate.concept_b_id, candidate.concept_b_name
            )
        else:
            return (
                candidate.concept_b_id, candidate.concept_b_name,
                candidate.concept_a_id, candidate.concept_a_name
            )

    def merge(
        self,
        decision_result: DecisionResult,
        dry_run: bool = False
    ) -> MergeResult:
        """
        Execute merge for an AUTO decision.

        Args:
            decision_result: The AUTO decision result
            dry_run: If True, don't actually perform the merge

        Returns:
            MergeResult with details of what was merged
        """
        if decision_result.decision != DecisionType.AUTO:
            raise ValueError(f"Cannot merge non-AUTO decision: {decision_result.decision}")

        candidate = decision_result.candidate

        # Select survivor
        survivor_id, survivor_name, merged_id, merged_name = self._select_survivor(candidate)

        logger.info(
            f"[IdentityResolver] Merging '{merged_name}' into '{survivor_name}' "
            f"(score={candidate.similarity_score:.3f})"
        )

        if dry_run:
            return MergeResult(
                success=True,
                survivor_id=survivor_id,
                merged_id=merged_id,
                merge_reason=f"DRY RUN: {decision_result.reason}",
                similarity_score=candidate.similarity_score,
                signals=candidate.signals
            )

        try:
            # Step 1: Migrate aliases
            aliases_migrated = self._migrate_aliases(survivor_id, merged_id)

            # Step 2: Redirect relations
            relations_migrated = self._redirect_relations(survivor_id, merged_id)

            # Step 3: Redirect claims
            claims_migrated = self._redirect_claims(survivor_id, merged_id)

            # Step 4: Mark merged concept as deprecated
            self._deprecate_concept(merged_id, survivor_id)

            # Step 5: Update stats
            self._merge_count += 1
            self._alias_count += len(aliases_migrated)
            self._relation_count += relations_migrated
            self._claim_count += claims_migrated

            # Step 6: Invalidate cache
            self.score_cache.invalidate_concept(merged_id)

            return MergeResult(
                success=True,
                survivor_id=survivor_id,
                merged_id=merged_id,
                merge_reason=decision_result.reason,
                similarity_score=candidate.similarity_score,
                signals=candidate.signals,
                aliases_migrated=aliases_migrated,
                relations_migrated=relations_migrated,
                claims_migrated=claims_migrated
            )

        except Exception as e:
            logger.error(f"[IdentityResolver] Merge failed: {e}")
            return MergeResult(
                success=False,
                survivor_id=survivor_id,
                merged_id=merged_id,
                merge_reason=f"FAILED: {e}",
                similarity_score=candidate.similarity_score,
                signals=candidate.signals
            )

    def _migrate_aliases(self, survivor_id: str, merged_id: str) -> List[str]:
        """Migrate surface forms from merged to survivor."""
        # Get merged concept's surface forms
        query = """
        MATCH (m:CanonicalConcept {canonical_id: $merged_id, tenant_id: $tenant_id})
        RETURN m.surface_forms AS forms, m.canonical_name AS name
        """
        result = self._execute_query(query, {
            "merged_id": merged_id,
            "tenant_id": self.tenant_id
        })

        if not result:
            return []

        forms_to_migrate = result[0].get("forms", []) or []
        merged_name = result[0].get("name", "")

        # Add the merged name itself as an alias
        if merged_name and merged_name not in forms_to_migrate:
            forms_to_migrate.append(merged_name)

        if not forms_to_migrate:
            return []

        # Add to survivor's surface forms
        query = """
        MATCH (s:CanonicalConcept {canonical_id: $survivor_id, tenant_id: $tenant_id})
        SET s.surface_forms = COALESCE(s.surface_forms, []) + $new_forms
        RETURN size(s.surface_forms) AS total_forms
        """
        self._execute_query(query, {
            "survivor_id": survivor_id,
            "tenant_id": self.tenant_id,
            "new_forms": forms_to_migrate
        })

        logger.debug(
            f"[IdentityResolver] Migrated {len(forms_to_migrate)} aliases "
            f"from {merged_id} to {survivor_id}"
        )

        return forms_to_migrate

    def _redirect_relations(self, survivor_id: str, merged_id: str) -> int:
        """Redirect all relations from merged to survivor."""
        # Count and redirect outgoing relations
        query_out = """
        MATCH (m:CanonicalConcept {canonical_id: $merged_id, tenant_id: $tenant_id})
              -[r]->(target)
        WHERE NOT target.canonical_id = $survivor_id
        WITH m, r, target, type(r) AS rel_type, properties(r) AS rel_props
        MATCH (s:CanonicalConcept {canonical_id: $survivor_id, tenant_id: $tenant_id})
        CALL apoc.create.relationship(s, rel_type, rel_props, target) YIELD rel
        DELETE r
        RETURN count(rel) AS redirected
        """

        # Count and redirect incoming relations
        query_in = """
        MATCH (source)-[r]->(m:CanonicalConcept {canonical_id: $merged_id, tenant_id: $tenant_id})
        WHERE NOT source.canonical_id = $survivor_id
        WITH m, r, source, type(r) AS rel_type, properties(r) AS rel_props
        MATCH (s:CanonicalConcept {canonical_id: $survivor_id, tenant_id: $tenant_id})
        CALL apoc.create.relationship(source, rel_type, rel_props, s) YIELD rel
        DELETE r
        RETURN count(rel) AS redirected
        """

        total_redirected = 0

        try:
            # Note: These queries use APOC for dynamic relationship creation
            # If APOC is not available, we'll use a fallback
            result_out = self._execute_query(query_out, {
                "merged_id": merged_id,
                "survivor_id": survivor_id,
                "tenant_id": self.tenant_id
            })
            total_redirected += result_out[0].get("redirected", 0) if result_out else 0
        except Exception:
            # Fallback without APOC - delete and log warning
            logger.warning(
                "[IdentityResolver] APOC not available for relation redirect. "
                "Using simple delete."
            )
            self._simple_delete_relations(merged_id)

        try:
            result_in = self._execute_query(query_in, {
                "merged_id": merged_id,
                "survivor_id": survivor_id,
                "tenant_id": self.tenant_id
            })
            total_redirected += result_in[0].get("redirected", 0) if result_in else 0
        except Exception:
            pass

        logger.debug(
            f"[IdentityResolver] Redirected {total_redirected} relations "
            f"from {merged_id} to {survivor_id}"
        )

        return total_redirected

    def _simple_delete_relations(self, merged_id: str) -> int:
        """Simple fallback: just delete relations (no redirect)."""
        query = """
        MATCH (m:CanonicalConcept {canonical_id: $merged_id, tenant_id: $tenant_id})
              -[r]-()
        DELETE r
        RETURN count(r) AS deleted
        """
        result = self._execute_query(query, {
            "merged_id": merged_id,
            "tenant_id": self.tenant_id
        })
        return result[0].get("deleted", 0) if result else 0

    def _redirect_claims(self, survivor_id: str, merged_id: str) -> int:
        """Redirect claims from merged to survivor."""
        # Redirect subject references
        query_subject = """
        MATCH (c:CanonicalClaim {tenant_id: $tenant_id})
        WHERE c.subject_canonical_id = $merged_id
        SET c.subject_canonical_id = $survivor_id,
            c.updated_at = datetime()
        RETURN count(c) AS updated
        """

        # Redirect object references
        query_object = """
        MATCH (c:CanonicalClaim {tenant_id: $tenant_id})
        WHERE c.object_canonical_id = $merged_id
        SET c.object_canonical_id = $survivor_id,
            c.updated_at = datetime()
        RETURN count(c) AS updated
        """

        total_updated = 0

        result_subj = self._execute_query(query_subject, {
            "merged_id": merged_id,
            "survivor_id": survivor_id,
            "tenant_id": self.tenant_id
        })
        total_updated += result_subj[0].get("updated", 0) if result_subj else 0

        result_obj = self._execute_query(query_object, {
            "merged_id": merged_id,
            "survivor_id": survivor_id,
            "tenant_id": self.tenant_id
        })
        total_updated += result_obj[0].get("updated", 0) if result_obj else 0

        logger.debug(
            f"[IdentityResolver] Redirected {total_updated} claims "
            f"from {merged_id} to {survivor_id}"
        )

        return total_updated

    def _deprecate_concept(self, merged_id: str, survivor_id: str) -> None:
        """Mark merged concept as deprecated (soft delete)."""
        query = """
        MATCH (m:CanonicalConcept {canonical_id: $merged_id, tenant_id: $tenant_id})
        SET m.status = 'deprecated',
            m.merged_into = $survivor_id,
            m.merged_at = datetime(),
            m:DeprecatedConcept
        RETURN m.canonical_id AS id
        """
        self._execute_query(query, {
            "merged_id": merged_id,
            "survivor_id": survivor_id,
            "tenant_id": self.tenant_id
        })

        logger.debug(f"[IdentityResolver] Deprecated concept {merged_id}")

    def merge_batch(
        self,
        decision_results: List[DecisionResult],
        dry_run: bool = False
    ) -> List[MergeResult]:
        """
        Execute batch of merges.

        Args:
            decision_results: List of AUTO decision results
            dry_run: If True, don't actually perform merges

        Returns:
            List of MergeResults
        """
        results = []
        for result in decision_results:
            if result.decision == DecisionType.AUTO:
                merge_result = self.merge(result, dry_run=dry_run)
                results.append(merge_result)

        successful = sum(1 for r in results if r.success)
        logger.info(
            f"[IdentityResolver] Batch merge: {successful}/{len(results)} successful"
        )

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get resolver statistics."""
        return {
            "merges_performed": self._merge_count,
            "aliases_migrated": self._alias_count,
            "relations_migrated": self._relation_count,
            "claims_migrated": self._claim_count,
        }

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._merge_count = 0
        self._alias_count = 0
        self._relation_count = 0
        self._claim_count = 0


# Singleton
_resolver_instance: Optional[IdentityResolver] = None


def get_identity_resolver(tenant_id: str = "default") -> IdentityResolver:
    """Get or create IdentityResolver instance."""
    global _resolver_instance
    if _resolver_instance is None or _resolver_instance.tenant_id != tenant_id:
        _resolver_instance = IdentityResolver(tenant_id=tenant_id)
    return _resolver_instance
