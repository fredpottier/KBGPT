"""
Corpus Consolidation Types

Shared types for corpus-level Entity Resolution.

Author: Claude Code
Date: 2026-01-01
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


class DecisionType(Enum):
    """Merge decision types."""
    AUTO_MERGE = "auto_merge"       # Haute confiance - merge automatique
    PROPOSE_ONLY = "propose_only"   # Zone grise - proposition pour review
    REJECT = "reject"               # Trop différent - pas de merge


class ERStatus(Enum):
    """Entity Resolution status for CanonicalConcept."""
    STANDALONE = "STANDALONE"        # Concept non fusionné
    MERGED = "MERGED"               # Concept fusionné dans un autre
    PROPOSAL_PENDING = "PROPOSAL_PENDING"  # Proposition en attente


class RejectReason(Enum):
    """Reasons for rejecting a merge candidate."""
    COMPAT_TOO_LOW = "compat_too_low"           # compat < 0.70
    LEX_SEM_TOO_LOW = "lex_sem_too_low"         # lex < 0.88 AND sem < 0.90
    NOT_IN_PROPOSAL_ZONE = "not_in_proposal"   # Doesn't meet PROPOSE thresholds
    BUDGET_DROP = "budget_drop"                 # Dropped due to proposal cap
    NOT_MUTUAL_BEST = "not_mutual_best"         # Pruned by mutual best rule


@dataclass
class MergeScores:
    """Scores for a merge candidate."""
    lex_score: float = 0.0      # Score lexical (Jaro-Winkler)
    sem_score: float = 0.0      # Score sémantique (cosine embeddings)
    compat_score: float = 0.0   # Score compatibilité type

    @property
    def combined(self) -> float:
        """Combined score for decision (spec ChatGPT)."""
        # Poids : sem 45%, lex 35%, compat 20%
        return 0.45 * self.sem_score + 0.35 * self.lex_score + 0.20 * self.compat_score

    @property
    def ranking_score(self) -> float:
        """Ranking score for TopK pruning (spec ChatGPT)."""
        # Poids : sem 50%, lex 35%, compat 15%
        return 0.50 * self.sem_score + 0.35 * self.lex_score + 0.15 * self.compat_score


@dataclass
class MergeProposal:
    """
    Proposition de merge entre deux concepts.
    Stockée dans Neo4j pour audit et review.
    """
    proposal_id: str
    source_id: str                  # canonical_id du concept source
    target_id: str                  # canonical_id du concept cible
    source_name: str
    target_name: str

    # Scores
    lex_score: float
    sem_score: float
    compat_score: float

    # Decision
    decision: DecisionType
    decision_reason: str

    # Metadata
    tenant_id: str = "default"
    created_at: datetime = field(default_factory=datetime.utcnow)
    applied: bool = False
    applied_at: Optional[datetime] = None
    applied_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Neo4j storage."""
        return {
            "proposal_id": self.proposal_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "lex_score": self.lex_score,
            "sem_score": self.sem_score,
            "compat_score": self.compat_score,
            "decision": self.decision.value,
            "decision_reason": self.decision_reason,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat(),
            "applied": self.applied,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "applied_by": self.applied_by,
        }


@dataclass
class MergeResult:
    """Result of a merge operation."""
    success: bool
    source_id: str
    target_id: str
    merge_reason: str

    # Stats
    edges_rewired: int = 0
    instance_of_rewired: int = 0

    # Errors
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "merge_reason": self.merge_reason,
            "edges_rewired": self.edges_rewired,
            "instance_of_rewired": self.instance_of_rewired,
            "error": self.error,
        }


@dataclass
class CorpusERConfig:
    """
    Configuration for corpus-level ER.

    Spec: PATCH-ER-04/05/06 (ChatGPT calibration)
    """

    # ==========================================================================
    # PATCH-ER-04: Candidate Pruning
    # ==========================================================================
    topk_per_concept: int = 3                   # Max candidates per concept
    min_compat_for_topk: float = 0.70           # Min compat to be in topK
    min_ranking_score: float = 0.82             # Min ranking score to keep
    lex_bypass_mutual: float = 0.97             # Lex >= this bypasses mutual best

    # ==========================================================================
    # PATCH-ER-05: Decision v2 thresholds
    # ==========================================================================
    # AUTO thresholds
    auto_lex_strict: float = 0.985              # Quasi-identique lexical
    auto_lex: float = 0.94                      # Fort lex
    auto_sem: float = 0.93                      # Fort sem
    auto_combined: float = 0.92                 # Combined élevé

    # PROPOSE thresholds
    propose_lex: float = 0.90
    propose_sem: float = 0.90
    propose_combined: float = 0.86

    # REJECT thresholds (gates)
    min_compat: float = 0.70                    # Hard gate
    reject_sem_floor: float = 0.86              # Below this + lex_floor = REJECT
    reject_lex_floor: float = 0.88              # Below this + sem_floor = REJECT

    # ==========================================================================
    # PATCH-ER-06: Hard budget proposals
    # ==========================================================================
    max_proposals_total: int = 1000             # Cap proposals (production)

    # ==========================================================================
    # Legacy/Other
    # ==========================================================================
    batch_size: int = 100
    embedding_threshold: float = 0.80

    # Type compatibility matrix
    type_compat_matrix: Dict[tuple, float] = field(default_factory=lambda: {
        ("entity_organization", "entity_organization"): 1.0,
        ("entity_product", "entity_product"): 1.0,
        ("entity_standard", "entity_standard"): 1.0,
        ("abstract_general", "abstract_general"): 1.0,
        ("abstract_capability", "abstract_capability"): 1.0,
        ("regulatory_requirement", "regulatory_requirement"): 1.0,
        # Cross-type (partiel)
        ("entity_standard", "regulatory_requirement"): 0.7,
        ("abstract_general", "abstract_capability"): 0.5,
    })

    def get_type_compat(self, type1: str, type2: str) -> float:
        """Get type compatibility score."""
        if not type1 or not type2:
            return 0.3

        t1 = type1.lower()
        t2 = type2.lower()

        # Same type
        if t1 == t2:
            return 1.0

        # Check matrix
        key = (t1, t2)
        if key in self.type_compat_matrix:
            return self.type_compat_matrix[key]

        key_rev = (t2, t1)
        if key_rev in self.type_compat_matrix:
            return self.type_compat_matrix[key_rev]

        # Default
        return 0.3


@dataclass
class CorpusERStats:
    """Statistics from a corpus ER run."""
    concepts_analyzed: int = 0
    candidates_generated: int = 0           # After blocking
    candidates_after_topk: int = 0          # After TopK pruning
    candidates_after_mutual: int = 0        # After mutual best
    candidates_scored: int = 0

    auto_merges: int = 0
    proposals_created: int = 0
    proposals_dropped_by_cap: int = 0       # Dropped due to MAX_PROPOSALS
    rejections: int = 0

    # Rejection breakdown
    reject_compat_low: int = 0
    reject_lex_sem_low: int = 0
    reject_not_proposal: int = 0

    # LLM Merge Gate stats (V1)
    llm_gate_calls: int = 0                 # Nombre d'appels LLM
    llm_gate_blocked: int = 0               # Paires bloquées par LLM (DISTINCT)
    llm_gate_low_confidence: int = 0        # Paires MERGE low-confidence
    llm_gate_latency_ms: float = 0.0        # Latence totale LLM Gate

    edges_rewired: int = 0
    instance_of_rewired: int = 0

    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concepts_analyzed": self.concepts_analyzed,
            "candidates_generated": self.candidates_generated,
            "candidates_after_topk": self.candidates_after_topk,
            "candidates_after_mutual": self.candidates_after_mutual,
            "candidates_scored": self.candidates_scored,
            "auto_merges": self.auto_merges,
            "proposals_created": self.proposals_created,
            "proposals_dropped_by_cap": self.proposals_dropped_by_cap,
            "rejections": self.rejections,
            "reject_breakdown": {
                "compat_low": self.reject_compat_low,
                "lex_sem_low": self.reject_lex_sem_low,
                "not_proposal": self.reject_not_proposal,
            },
            "llm_gate": {
                "calls": self.llm_gate_calls,
                "blocked": self.llm_gate_blocked,
                "low_confidence": self.llm_gate_low_confidence,
                "latency_ms": self.llm_gate_latency_ms,
            },
            "edges_rewired": self.edges_rewired,
            "instance_of_rewired": self.instance_of_rewired,
            "duration_ms": self.duration_ms,
            "errors": self.errors[:10],
        }

    def log_summary(self) -> str:
        """Generate summary string for logging."""
        total_decisions = self.auto_merges + self.proposals_created + self.rejections
        if total_decisions == 0:
            return "No decisions made"

        auto_pct = 100 * self.auto_merges / total_decisions
        propose_pct = 100 * self.proposals_created / total_decisions
        reject_pct = 100 * self.rejections / total_decisions

        return (
            f"Distribution: AUTO={self.auto_merges} ({auto_pct:.1f}%) | "
            f"PROPOSE={self.proposals_created} ({propose_pct:.1f}%) | "
            f"REJECT={self.rejections} ({reject_pct:.1f}%)"
        )
