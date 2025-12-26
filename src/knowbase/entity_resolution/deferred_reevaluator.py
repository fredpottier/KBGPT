"""
Phase 2.12 - Deferred Reevaluator

Batch job to reevaluate DEFER candidates.

Triggers:
- After N new documents ingested
- Scheduled periodic job
- Manual admin trigger

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

from .types import (
    MergeCandidate, DeferredMergeCandidate, MergeResult,
    DecisionType, EntityResolutionStats
)
from .deferred_store import DeferredStore, get_deferred_store
from .pair_scorer import PairSimilarityScorer, get_pair_scorer
from .decision_router import IdentityDecisionRouter, get_decision_router, DecisionResult
from .identity_resolver import IdentityResolver, get_identity_resolver
from .config import DEFER_CONFIG

logger = logging.getLogger(__name__)


class ReevaluationResult:
    """Result of a reevaluation run."""

    def __init__(self):
        self.candidates_evaluated = 0
        self.promoted_to_auto = 0
        self.still_deferred = 0
        self.rejected = 0
        self.expired = 0
        self.merge_results: List[MergeResult] = []
        self.errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "candidates_evaluated": self.candidates_evaluated,
            "promoted_to_auto": self.promoted_to_auto,
            "still_deferred": self.still_deferred,
            "rejected": self.rejected,
            "expired": self.expired,
            "merges_successful": sum(1 for r in self.merge_results if r.success),
            "merges_failed": sum(1 for r in self.merge_results if not r.success),
            "errors": self.errors[:10],  # Limit error output
        }


class DeferredReevaluator:
    """
    Reevaluates DEFER candidates to check if they should now be AUTO merged.

    Runs as a batch job, triggered by:
    - Document ingestion threshold
    - Scheduled cron
    - Admin action
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize DeferredReevaluator.

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

        # Components
        self.deferred_store = get_deferred_store(tenant_id)
        self.scorer = get_pair_scorer()
        self.router = get_decision_router()
        self.resolver = get_identity_resolver(tenant_id)

        # Track ingested docs for trigger
        self._docs_since_last_run = 0

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def notify_document_ingested(self) -> bool:
        """
        Notify that a document was ingested.

        Returns:
            True if reevaluation threshold reached
        """
        self._docs_since_last_run += 1
        threshold = DEFER_CONFIG["reevaluate_after_n_docs"]

        if self._docs_since_last_run >= threshold:
            logger.info(
                f"[DeferredReevaluator] Document threshold reached "
                f"({self._docs_since_last_run}/{threshold}), triggering reevaluation"
            )
            return True

        return False

    def _deferred_to_candidate(
        self,
        deferred: DeferredMergeCandidate
    ) -> MergeCandidate:
        """Convert DeferredMergeCandidate to MergeCandidate for scoring."""
        return MergeCandidate(
            concept_a_id=deferred.concept_a_id,
            concept_b_id=deferred.concept_b_id,
            concept_a_name=deferred.concept_a_name,
            concept_b_name=deferred.concept_b_name,
            concept_type=deferred.concept_type,
            similarity_score=deferred.similarity_score,
            signals=deferred.signals,
            has_exact_match=deferred.has_exact_match,
            has_acronym_match=deferred.has_acronym_match,
            shared_surface_forms=deferred.shared_surface_forms,
            doc_count_a=deferred.doc_count_a,
            doc_count_b=deferred.doc_count_b,
        )

    def _get_updated_doc_counts(
        self,
        concept_a_id: str,
        concept_b_id: str
    ) -> Tuple[int, int, int]:
        """Get fresh document counts for concepts."""
        query = """
        MATCH (a:CanonicalConcept {canonical_id: $concept_a_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (a)<-[:MENTIONS]-(da:Document)
        WITH a, count(DISTINCT da) AS doc_count_a
        MATCH (b:CanonicalConcept {canonical_id: $concept_b_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (b)<-[:MENTIONS]-(db:Document)
        WITH doc_count_a, count(DISTINCT db) AS doc_count_b
        OPTIONAL MATCH (a)<-[:MENTIONS]-(d:Document)-[:MENTIONS]->(b)
        RETURN doc_count_a, doc_count_b, count(DISTINCT d) AS shared_doc_count
        """
        result = self._execute_query(query, {
            "concept_a_id": concept_a_id,
            "concept_b_id": concept_b_id,
            "tenant_id": self.tenant_id
        })

        if result:
            return (
                result[0].get("doc_count_a", 0),
                result[0].get("doc_count_b", 0),
                result[0].get("shared_doc_count", 0)
            )
        return (0, 0, 0)

    def _get_concept_data(self, concept_id: str) -> Dict[str, Any]:
        """Get concept metadata for scoring."""
        query = """
        MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
        RETURN c.surface_forms AS surface_forms,
               c.definition AS definition
        """
        result = self._execute_query(query, {
            "concept_id": concept_id,
            "tenant_id": self.tenant_id
        })
        if result:
            return {
                "surface_forms": result[0].get("surface_forms", []),
                "definition": result[0].get("definition")
            }
        return {}

    def reevaluate(
        self,
        batch_size: Optional[int] = None,
        min_doc_count: int = 0,
        dry_run: bool = False
    ) -> ReevaluationResult:
        """
        Reevaluate pending DEFER candidates.

        Args:
            batch_size: Max candidates to process (default from config)
            min_doc_count: Only process candidates with at least this many docs
            dry_run: If True, don't execute merges

        Returns:
            ReevaluationResult with statistics
        """
        if batch_size is None:
            batch_size = DEFER_CONFIG["reevaluate_batch_size"]

        result = ReevaluationResult()

        # Step 1: Cleanup expired
        expired_count = self.deferred_store.delete_expired()
        result.expired = expired_count

        # Step 2: Get pending candidates
        pending = self.deferred_store.get_pending(
            limit=batch_size,
            min_doc_count=min_doc_count
        )

        logger.info(
            f"[DeferredReevaluator] Processing {len(pending)} pending candidates "
            f"(expired {expired_count})"
        )

        for deferred in pending:
            try:
                reevaluation = self._reevaluate_candidate(deferred, dry_run)
                result.candidates_evaluated += 1

                if reevaluation["decision"] == DecisionType.AUTO:
                    result.promoted_to_auto += 1
                    if reevaluation.get("merge_result"):
                        result.merge_results.append(reevaluation["merge_result"])
                elif reevaluation["decision"] == DecisionType.DEFER:
                    result.still_deferred += 1
                else:
                    result.rejected += 1

            except Exception as e:
                error_msg = f"Error reevaluating {deferred.pair_id}: {e}"
                logger.error(f"[DeferredReevaluator] {error_msg}")
                result.errors.append(error_msg)

        # Reset doc counter
        self._docs_since_last_run = 0

        logger.info(
            f"[DeferredReevaluator] Complete: "
            f"evaluated={result.candidates_evaluated}, "
            f"promoted={result.promoted_to_auto}, "
            f"still_deferred={result.still_deferred}, "
            f"rejected={result.rejected}"
        )

        return result

    def _reevaluate_candidate(
        self,
        deferred: DeferredMergeCandidate,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Reevaluate a single deferred candidate.

        Args:
            deferred: The deferred candidate
            dry_run: If True, don't execute merge

        Returns:
            Dict with decision and optional merge result
        """
        # Update doc counts
        doc_a, doc_b, shared = self._get_updated_doc_counts(
            deferred.concept_a_id,
            deferred.concept_b_id
        )

        self.deferred_store.update_doc_counts(
            deferred.pair_id,
            doc_a, doc_b, shared
        )

        # Get fresh concept data
        data_a = self._get_concept_data(deferred.concept_a_id)
        data_b = self._get_concept_data(deferred.concept_b_id)

        # Convert to MergeCandidate
        candidate = self._deferred_to_candidate(deferred)
        candidate.doc_count_a = doc_a
        candidate.doc_count_b = doc_b

        # Re-score with fresh data (bypass cache)
        scored = self.scorer.score_candidate(
            candidate,
            surface_forms_a=data_a.get("surface_forms", []),
            surface_forms_b=data_b.get("surface_forms", []),
            definition_a=data_a.get("definition"),
            definition_b=data_b.get("definition"),
            use_cache=False  # Always compute fresh
        )

        # Re-route
        decision_result = self.router.route(scored)

        # Handle decision
        if decision_result.decision == DecisionType.AUTO:
            # Promoted! Execute merge
            if not dry_run:
                merge_result = self.resolver.merge(decision_result)
                # Remove from deferred store
                self.deferred_store.delete(deferred.pair_id)
                return {
                    "decision": DecisionType.AUTO,
                    "merge_result": merge_result
                }
            else:
                return {"decision": DecisionType.AUTO, "merge_result": None}

        elif decision_result.decision == DecisionType.REJECT:
            # Now rejected, remove from store
            self.deferred_store.update_status(deferred.pair_id, DecisionType.REJECT)
            return {"decision": DecisionType.REJECT}

        else:
            # Still DEFER, update evaluation count
            self.deferred_store.update_status(
                deferred.pair_id,
                DecisionType.DEFER,
                increment_eval=True
            )
            return {"decision": DecisionType.DEFER}

    def get_stats(self) -> Dict[str, Any]:
        """Get reevaluator statistics."""
        store_stats = self.deferred_store.get_stats()
        return {
            "docs_since_last_run": self._docs_since_last_run,
            "trigger_threshold": DEFER_CONFIG["reevaluate_after_n_docs"],
            "deferred_queue": store_stats,
        }


# Singleton
_reevaluator_instance: Optional[DeferredReevaluator] = None


def get_deferred_reevaluator(tenant_id: str = "default") -> DeferredReevaluator:
    """Get or create DeferredReevaluator instance."""
    global _reevaluator_instance
    if _reevaluator_instance is None or _reevaluator_instance.tenant_id != tenant_id:
        _reevaluator_instance = DeferredReevaluator(tenant_id=tenant_id)
    return _reevaluator_instance


async def run_reevaluation_job(
    tenant_id: str = "default",
    dry_run: bool = False
) -> ReevaluationResult:
    """
    Run reevaluation as async job.

    Can be called from background task or scheduled job.

    Args:
        tenant_id: Tenant ID
        dry_run: If True, don't execute merges

    Returns:
        ReevaluationResult
    """
    reevaluator = get_deferred_reevaluator(tenant_id)
    return reevaluator.reevaluate(dry_run=dry_run)
