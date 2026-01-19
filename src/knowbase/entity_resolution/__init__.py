"""
OSMOSE Phase 2.12 - Entity Resolution

Cross-document entity resolution with AUTO/DEFER/REJECT model.
No human debt - fully autonomous system.

Components:
- CandidateFinder: Blocking + candidate generation
- PairSimilarityScorer: Cross-encoder + lexical signals
- IdentityDecisionRouter: AUTO/DEFER/REJECT decisions
- IdentityResolver: Merge with provenance
- DeferredReevaluator: Batch job for DEFER resolution
- DeferredStore: Storage for deferred merge candidates
- ScoreCache: Redis cache for pairwise scores

Author: Claude Code
Date: 2025-12-26
"""

# Types
from .types import (
    ConceptType,
    DecisionType,
    MergeCandidate,
    DeferredMergeCandidate,
    MergeResult,
    SignalBreakdown,
    TypeThresholds,
    EntityResolutionStats,
)

# Config
from .config import (
    get_type_thresholds,
    THRESHOLDS_BY_TYPE,
    BLOCKING_CONFIG,
    DEFER_CONFIG,
    CACHE_CONFIG,
    CROSS_ENCODER_CONFIG,
)

# Components
from .candidate_finder import CandidateFinder, get_candidate_finder
from .pair_scorer import PairSimilarityScorer, get_pair_scorer
from .decision_router import IdentityDecisionRouter, get_decision_router, DecisionResult
from .identity_resolver import IdentityResolver, get_identity_resolver
from .deferred_store import DeferredStore, get_deferred_store
from .deferred_reevaluator import DeferredReevaluator, get_deferred_reevaluator
from .score_cache import ScoreCache, get_score_cache

# Pipeline
from .pipeline import (
    EntityResolutionPipeline,
    get_entity_resolution_pipeline,
    run_entity_resolution,
    PipelineResult,
)

# LLM Merge Gate (V1)
from .llm_merge_gate import (
    LLMMergeGate,
    LLMGateConfig,
    LLMGateResult,
    LLMMergeVerdict,
    get_llm_merge_gate,
    reset_llm_merge_gate,
)

__all__ = [
    # Types
    "ConceptType",
    "DecisionType",
    "MergeCandidate",
    "DeferredMergeCandidate",
    "MergeResult",
    "SignalBreakdown",
    "TypeThresholds",
    "EntityResolutionStats",
    # Config
    "get_type_thresholds",
    "THRESHOLDS_BY_TYPE",
    "BLOCKING_CONFIG",
    "DEFER_CONFIG",
    "CACHE_CONFIG",
    "CROSS_ENCODER_CONFIG",
    # Components
    "CandidateFinder",
    "get_candidate_finder",
    "PairSimilarityScorer",
    "get_pair_scorer",
    "IdentityDecisionRouter",
    "get_decision_router",
    "DecisionResult",
    "IdentityResolver",
    "get_identity_resolver",
    "DeferredStore",
    "get_deferred_store",
    "DeferredReevaluator",
    "get_deferred_reevaluator",
    "ScoreCache",
    "get_score_cache",
    # Pipeline
    "EntityResolutionPipeline",
    "get_entity_resolution_pipeline",
    "run_entity_resolution",
    "PipelineResult",
    # LLM Merge Gate (V1)
    "LLMMergeGate",
    "LLMGateConfig",
    "LLMGateResult",
    "LLMMergeVerdict",
    "get_llm_merge_gate",
    "reset_llm_merge_gate",
]
