"""
Phase 2.12 v1.1 - Entity Resolution Pipeline

Main orchestrator for the entity resolution workflow.

Pipeline Flow:
1. CandidateFinder -> generates candidates via blocking
2. RejectStore filter -> skip already-rejected pairs
3. PairSimilarityScorer -> scores each candidate
4. IdentityDecisionRouter -> routes to AUTO/DEFER/REJECT
5. IdentityResolver -> executes AUTO merges
6. DeferredStore -> stores DEFER candidates
7. RejectStore -> stores REJECT for future runs

v1.1 Improvements:
- RejectStore to avoid re-scoring rejected pairs (TTL 90 days)
- Incremental mode for new concepts only
- Fingerprint-based invalidation

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any, Set

from .types import (
    ConceptType, MergeCandidate, MergeResult,
    DeferredMergeCandidate, DecisionType, EntityResolutionStats
)
from .candidate_finder import CandidateFinder, get_candidate_finder
from .pair_scorer import PairSimilarityScorer, get_pair_scorer
from .decision_router import IdentityDecisionRouter, get_decision_router, DecisionResult
from .identity_resolver import IdentityResolver, get_identity_resolver
from .deferred_store import DeferredStore, get_deferred_store
from .deferred_reevaluator import DeferredReevaluator, get_deferred_reevaluator
from .reject_store import RejectStore, get_reject_store

logger = logging.getLogger(__name__)


class PipelineResult:
    """Result of an entity resolution pipeline run."""

    def __init__(self):
        self.start_time = datetime.utcnow()
        self.end_time: Optional[datetime] = None
        self.duration_ms: float = 0

        # Counts
        self.concepts_processed = 0
        self.candidates_generated = 0
        self.candidates_scored = 0

        # Decisions
        self.auto_decisions = 0
        self.defer_decisions = 0
        self.reject_decisions = 0

        # Merges
        self.merges_attempted = 0
        self.merges_successful = 0
        self.merges_failed = 0

        # Results
        self.merge_results: List[MergeResult] = []
        self.deferred_stored = 0

        # Errors
        self.errors: List[str] = []

    def finalize(self) -> None:
        """Mark pipeline as complete."""
        self.end_time = datetime.utcnow()
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "concepts_processed": self.concepts_processed,
            "candidates_generated": self.candidates_generated,
            "candidates_scored": self.candidates_scored,
            "auto_decisions": self.auto_decisions,
            "defer_decisions": self.defer_decisions,
            "reject_decisions": self.reject_decisions,
            "merges_attempted": self.merges_attempted,
            "merges_successful": self.merges_successful,
            "merges_failed": self.merges_failed,
            "deferred_stored": self.deferred_stored,
            "errors": self.errors[:10],
        }


class EntityResolutionPipeline:
    """
    Main orchestrator for entity resolution.

    Coordinates all components to find and merge duplicate concepts.

    v1.1: Added RejectStore integration and incremental mode.
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialize EntityResolutionPipeline.

        Args:
            tenant_id: Tenant ID
        """
        self.tenant_id = tenant_id

        # Initialize components
        self.candidate_finder = get_candidate_finder(tenant_id)
        self.scorer = get_pair_scorer()
        self.router = get_decision_router()
        self.resolver = get_identity_resolver(tenant_id)
        self.deferred_store = get_deferred_store(tenant_id)
        self.reevaluator = get_deferred_reevaluator(tenant_id)
        self.reject_store = get_reject_store()  # v1.1: RejectStore

    def run(
        self,
        concept_type: Optional[ConceptType] = None,
        target_concept_id: Optional[str] = None,
        dry_run: bool = False,
        skip_reject_filter: bool = False
    ) -> PipelineResult:
        """
        Run the entity resolution pipeline.

        Args:
            concept_type: Filter by concept type (None = all)
            target_concept_id: Process only candidates for this concept
            dry_run: If True, don't execute merges
            skip_reject_filter: If True, don't filter by RejectStore (for re-analysis)

        Returns:
            PipelineResult with statistics
        """
        result = PipelineResult()

        try:
            # Step 1: Find candidates
            logger.info(
                f"[ERPipeline] Starting pipeline "
                f"(type={concept_type}, target={target_concept_id}, dry_run={dry_run})"
            )

            candidates = self.candidate_finder.find_candidates(
                concept_type=concept_type,
                target_concept_id=target_concept_id
            )
            result.candidates_generated = len(candidates)

            if not candidates:
                logger.info("[ERPipeline] No candidates found")
                result.finalize()
                return result

            # Step 2: Get concept data for scoring (needed for fingerprints)
            concepts_data = self._get_concepts_data(candidates)
            result.concepts_processed = len(concepts_data)

            # Step 2.5 (v1.1): Filter out already-rejected pairs
            if not skip_reject_filter:
                candidates = self._filter_rejected_candidates(candidates, concepts_data)
                logger.info(f"[ERPipeline] After RejectStore filter: {len(candidates)} candidates")

            if not candidates:
                logger.info("[ERPipeline] All candidates already rejected")
                result.finalize()
                return result

            # Step 3: Score candidates
            scored_candidates = self.scorer.score_batch(candidates, concepts_data)
            result.candidates_scored = len(scored_candidates)

            # Step 4: Route decisions
            auto_results, defer_results, reject_results = self.router.route_batch(
                scored_candidates
            )

            result.auto_decisions = len(auto_results)
            result.defer_decisions = len(defer_results)
            result.reject_decisions = len(reject_results)

            # Step 5: Execute AUTO merges
            if auto_results and not dry_run:
                result.merges_attempted = len(auto_results)
                merge_results = self.resolver.merge_batch(auto_results)
                result.merge_results = merge_results
                result.merges_successful = sum(1 for r in merge_results if r.success)
                result.merges_failed = sum(1 for r in merge_results if not r.success)

            # Step 6: Store DEFER candidates
            for decision_result in defer_results:
                try:
                    deferred = decision_result.to_deferred(self.tenant_id)
                    if self.deferred_store.store(deferred):
                        result.deferred_stored += 1
                except Exception as e:
                    result.errors.append(f"Failed to store deferred: {e}")

            # Step 7 (v1.1): Store REJECT in RejectStore
            self._store_rejects(reject_results, concepts_data)

            logger.info(
                f"[ERPipeline] Complete: "
                f"candidates={result.candidates_generated}, "
                f"AUTO={result.auto_decisions}, "
                f"DEFER={result.defer_decisions}, "
                f"REJECT={result.reject_decisions}, "
                f"merges={result.merges_successful}/{result.merges_attempted}"
            )

        except Exception as e:
            error_msg = f"Pipeline error: {e}"
            logger.error(f"[ERPipeline] {error_msg}")
            result.errors.append(error_msg)

        result.finalize()
        return result

    def _get_concepts_data(
        self,
        candidates: List[MergeCandidate]
    ) -> Dict[str, Dict[str, Any]]:
        """Get concept metadata for all candidates."""
        concept_ids = set()
        for c in candidates:
            concept_ids.add(c.concept_a_id)
            concept_ids.add(c.concept_b_id)

        if not concept_ids:
            return {}

        # Batch query for efficiency
        query = """
        UNWIND $concept_ids AS cid
        MATCH (c:CanonicalConcept {canonical_id: cid, tenant_id: $tenant_id})
        RETURN c.canonical_id AS id,
               c.surface_forms AS surface_forms,
               c.definition AS definition
        """

        from knowbase.config.settings import get_settings
        from knowbase.common.clients.neo4j_client import Neo4jClient

        settings = get_settings()
        neo4j = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        try:
            if neo4j.driver:
                with neo4j.driver.session() as session:
                    result = session.run(query, {
                        "concept_ids": list(concept_ids),
                        "tenant_id": self.tenant_id
                    })
                    return {
                        r["id"]: {
                            "surface_forms": r["surface_forms"] or [],
                            "definition": r["definition"]
                        }
                        for r in result
                    }
        except Exception as e:
            logger.warning(f"[ERPipeline] Failed to get concept data: {e}")

        return {}

    def _compute_fingerprint(self, name: str, aliases: List[str] = None) -> str:
        """Compute fingerprint for a concept (for invalidation detection)."""
        data = name.lower().strip()
        if aliases:
            data += "|" + "|".join(sorted(a.lower().strip() for a in aliases if a))
        return hashlib.md5(data.encode()).hexdigest()[:16]

    def _filter_rejected_candidates(
        self,
        candidates: List[MergeCandidate],
        concepts_data: Dict[str, Dict[str, Any]]
    ) -> List[MergeCandidate]:
        """
        Filter out candidates that were previously rejected.

        v1.1: Uses RejectStore with fingerprint-based invalidation.
        """
        filtered = []
        skipped = 0

        for candidate in candidates:
            # Compute current fingerprints
            data_a = concepts_data.get(candidate.concept_a_id, {})
            data_b = concepts_data.get(candidate.concept_b_id, {})

            fp_a = self._compute_fingerprint(
                candidate.concept_a_name,
                data_a.get("surface_forms", [])
            )
            fp_b = self._compute_fingerprint(
                candidate.concept_b_name,
                data_b.get("surface_forms", [])
            )

            # Check if already rejected (with valid fingerprints)
            if self.reject_store.is_rejected(
                candidate.concept_a_id,
                candidate.concept_b_id,
                fingerprint_a=fp_a,
                fingerprint_b=fp_b
            ):
                skipped += 1
            else:
                filtered.append(candidate)

        if skipped > 0:
            logger.info(f"[ERPipeline] Skipped {skipped} previously rejected pairs")

        return filtered

    def _store_rejects(
        self,
        reject_results: List[DecisionResult],
        concepts_data: Dict[str, Dict[str, Any]]
    ) -> int:
        """
        Store rejected pairs in RejectStore.

        v1.1: Stores with fingerprints for invalidation.
        """
        if not reject_results:
            return 0

        rejects_to_store = []
        for result in reject_results:
            candidate = result.candidate
            data_a = concepts_data.get(candidate.concept_a_id, {})
            data_b = concepts_data.get(candidate.concept_b_id, {})

            fp_a = self._compute_fingerprint(
                candidate.concept_a_name,
                data_a.get("surface_forms", [])
            )
            fp_b = self._compute_fingerprint(
                candidate.concept_b_name,
                data_b.get("surface_forms", [])
            )

            rejects_to_store.append({
                "concept_a_id": candidate.concept_a_id,
                "concept_b_id": candidate.concept_b_id,
                "score": candidate.similarity_score,
                "fingerprint_a": fp_a,
                "fingerprint_b": fp_b,
                "reason": result.reason
            })

        stored = self.reject_store.add_rejects_batch(rejects_to_store)
        logger.info(f"[ERPipeline] Stored {stored} rejects in RejectStore")
        return stored

    def run_for_new_concept(
        self,
        concept_id: str,
        concept_name: str,
        concept_type: ConceptType,
        dry_run: bool = False
    ) -> PipelineResult:
        """
        Run pipeline for a newly created concept.

        Called after document ingestion to check for duplicates.

        Args:
            concept_id: New concept ID
            concept_name: New concept name
            concept_type: Concept type
            dry_run: If True, don't execute merges

        Returns:
            PipelineResult
        """
        logger.info(
            f"[ERPipeline] Running for new concept: {concept_name} "
            f"(id={concept_id}, type={concept_type.value})"
        )

        return self.run(
            concept_type=concept_type,
            target_concept_id=concept_id,
            dry_run=dry_run
        )

    def get_stats(self) -> EntityResolutionStats:
        """Get overall entity resolution statistics."""
        # Get component stats
        router_stats = self.router.get_stats()
        resolver_stats = self.resolver.get_stats()
        deferred_stats = self.deferred_store.get_stats()

        return EntityResolutionStats(
            total_concepts=0,  # Would need DB query
            candidates_generated=0,  # From last run
            auto_merges=resolver_stats.get("merges_performed", 0),
            deferred=deferred_stats.get("pending", 0),
            rejected=router_stats.get("reject", 0),
            deferred_queue_size=deferred_stats.get("total", 0),
            deferred_resolved_today=deferred_stats.get("resolved_auto", 0),
            deferred_expired_today=deferred_stats.get("expired", 0),
            auto_rate=router_stats.get("auto_rate", 0.0),
            defer_resolution_rate=0.0,  # Computed from historical data
        )


# Singleton
_pipeline_instance: Optional[EntityResolutionPipeline] = None


def get_entity_resolution_pipeline(tenant_id: str = "default") -> EntityResolutionPipeline:
    """Get or create EntityResolutionPipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None or _pipeline_instance.tenant_id != tenant_id:
        _pipeline_instance = EntityResolutionPipeline(tenant_id=tenant_id)
    return _pipeline_instance


async def run_entity_resolution(
    tenant_id: str = "default",
    concept_type: Optional[ConceptType] = None,
    dry_run: bool = False
) -> PipelineResult:
    """
    Run entity resolution as async task.

    Args:
        tenant_id: Tenant ID
        concept_type: Filter by type
        dry_run: If True, don't execute merges

    Returns:
        PipelineResult
    """
    pipeline = get_entity_resolution_pipeline(tenant_id)
    return pipeline.run(concept_type=concept_type, dry_run=dry_run)
