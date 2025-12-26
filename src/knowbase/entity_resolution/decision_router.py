"""
Phase 2.12 - Identity Decision Router

Routes merge candidates to AUTO/DEFER/REJECT based on type-specific thresholds.

Decision Logic:
- score >= threshold_auto AND conditions met -> AUTO
- score >= threshold_defer -> DEFER
- score < threshold_defer -> REJECT

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any

from .types import (
    MergeCandidate, DeferredMergeCandidate, DecisionType,
    ConceptType, TypeThresholds
)
from .config import get_type_thresholds, get_defer_ttl

logger = logging.getLogger(__name__)


class DecisionResult:
    """Result of a routing decision."""

    def __init__(
        self,
        candidate: MergeCandidate,
        decision: DecisionType,
        reason: str,
        thresholds: TypeThresholds
    ):
        self.candidate = candidate
        self.decision = decision
        self.reason = reason
        self.thresholds = thresholds

    def to_deferred(self, tenant_id: str = "default") -> DeferredMergeCandidate:
        """Convert to DeferredMergeCandidate (for DEFER decisions)."""
        now = datetime.utcnow()
        ttl = get_defer_ttl()

        return DeferredMergeCandidate(
            pair_id=self.candidate.pair_id(),
            concept_a_id=self.candidate.concept_a_id,
            concept_b_id=self.candidate.concept_b_id,
            concept_a_name=self.candidate.concept_a_name,
            concept_b_name=self.candidate.concept_b_name,
            concept_type=self.candidate.concept_type,
            tenant_id=tenant_id,
            similarity_score=self.candidate.similarity_score,
            signals=self.candidate.signals,
            has_exact_match=self.candidate.has_exact_match,
            has_acronym_match=self.candidate.has_acronym_match,
            shared_surface_forms=self.candidate.shared_surface_forms,
            doc_count_a=self.candidate.doc_count_a,
            doc_count_b=self.candidate.doc_count_b,
            shared_doc_count=0,
            created_at=now,
            last_evaluated_at=now,
            evaluation_count=1,
            expires_at=now + ttl,
            status=DecisionType.DEFER
        )


class IdentityDecisionRouter:
    """
    Routes merge candidates to AUTO/DEFER/REJECT.

    Applies type-specific thresholds and additional conditions
    to ensure precision-first entity resolution.
    """

    def __init__(self):
        """Initialize IdentityDecisionRouter."""
        # Stats tracking
        self._stats = {
            "auto": 0,
            "defer": 0,
            "reject": 0
        }

    def route(self, candidate: MergeCandidate) -> DecisionResult:
        """
        Route a single candidate to AUTO/DEFER/REJECT.

        Args:
            candidate: Scored merge candidate

        Returns:
            DecisionResult with decision and reason
        """
        thresholds = get_type_thresholds(candidate.concept_type)
        score = candidate.similarity_score

        # Check for AUTO
        if score >= thresholds.threshold_auto:
            # Check additional conditions for certain types
            if self._check_auto_conditions(candidate, thresholds):
                self._stats["auto"] += 1
                return DecisionResult(
                    candidate=candidate,
                    decision=DecisionType.AUTO,
                    reason=f"Score {score:.3f} >= {thresholds.threshold_auto:.2f} (AUTO threshold)",
                    thresholds=thresholds
                )
            else:
                # Conditions not met, defer instead
                self._stats["defer"] += 1
                return DecisionResult(
                    candidate=candidate,
                    decision=DecisionType.DEFER,
                    reason=f"Score {score:.3f} >= AUTO but conditions not met, deferring",
                    thresholds=thresholds
                )

        # Check for DEFER
        if score >= thresholds.threshold_defer:
            self._stats["defer"] += 1
            return DecisionResult(
                candidate=candidate,
                decision=DecisionType.DEFER,
                reason=f"Score {score:.3f} in DEFER range [{thresholds.threshold_defer:.2f}, {thresholds.threshold_auto:.2f})",
                thresholds=thresholds
            )

        # REJECT
        self._stats["reject"] += 1
        return DecisionResult(
            candidate=candidate,
            decision=DecisionType.REJECT,
            reason=f"Score {score:.3f} < {thresholds.threshold_defer:.2f} (DEFER threshold)",
            thresholds=thresholds
        )

    def _check_auto_conditions(
        self,
        candidate: MergeCandidate,
        thresholds: TypeThresholds
    ) -> bool:
        """
        Check additional AUTO conditions for a candidate.

        Some concept types require more than just score threshold.

        Args:
            candidate: The merge candidate
            thresholds: Type thresholds with conditions

        Returns:
            True if all conditions are met
        """
        conditions = thresholds.auto_safe_conditions
        if not conditions:
            return True

        # Check exact_normalized_match
        if conditions.get("exact_normalized_match", False):
            if not candidate.has_exact_match:
                logger.debug(
                    f"[DecisionRouter] AUTO blocked: exact_normalized_match required "
                    f"for {candidate.concept_type.value}"
                )
                return False

        # Check definition_fingerprint_match
        if conditions.get("definition_fingerprint_match", False):
            if not candidate.has_definition_match:
                logger.debug(
                    f"[DecisionRouter] AUTO blocked: definition_fingerprint_match required "
                    f"for {candidate.concept_type.value}"
                )
                return False

        # Check stable_across_n_docs
        min_docs = conditions.get("stable_across_n_docs", 0)
        if min_docs > 0:
            total_docs = candidate.doc_count_a + candidate.doc_count_b
            if total_docs < min_docs:
                logger.debug(
                    f"[DecisionRouter] AUTO blocked: need {min_docs} docs, "
                    f"have {total_docs}"
                )
                return False

        return True

    def route_batch(
        self,
        candidates: List[MergeCandidate]
    ) -> Tuple[List[DecisionResult], List[DecisionResult], List[DecisionResult]]:
        """
        Route a batch of candidates.

        Args:
            candidates: List of scored candidates

        Returns:
            Tuple of (auto_results, defer_results, reject_results)
        """
        auto_results = []
        defer_results = []
        reject_results = []

        for candidate in candidates:
            result = self.route(candidate)

            if result.decision == DecisionType.AUTO:
                auto_results.append(result)
            elif result.decision == DecisionType.DEFER:
                defer_results.append(result)
            else:
                reject_results.append(result)

        logger.info(
            f"[DecisionRouter] Routed {len(candidates)} candidates: "
            f"AUTO={len(auto_results)}, DEFER={len(defer_results)}, REJECT={len(reject_results)}"
        )

        return auto_results, defer_results, reject_results

    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        total = sum(self._stats.values())
        return {
            "total_routed": total,
            "auto": self._stats["auto"],
            "defer": self._stats["defer"],
            "reject": self._stats["reject"],
            "auto_rate": self._stats["auto"] / total if total > 0 else 0.0,
            "defer_rate": self._stats["defer"] / total if total > 0 else 0.0,
            "reject_rate": self._stats["reject"] / total if total > 0 else 0.0,
        }

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {"auto": 0, "defer": 0, "reject": 0}


def should_auto_merge(
    candidate: MergeCandidate,
    thresholds: Optional[TypeThresholds] = None
) -> bool:
    """
    Quick check if a candidate should be auto-merged.

    Convenience function for inline checks.

    Args:
        candidate: Scored merge candidate
        thresholds: Optional thresholds (fetched if None)

    Returns:
        True if candidate qualifies for AUTO
    """
    router = IdentityDecisionRouter()
    result = router.route(candidate)
    return result.decision == DecisionType.AUTO


# Singleton
_router_instance: Optional[IdentityDecisionRouter] = None


def get_decision_router() -> IdentityDecisionRouter:
    """Get or create IdentityDecisionRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = IdentityDecisionRouter()
    return _router_instance
