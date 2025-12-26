"""
Phase 2.12 - Entity Resolution Configuration

Thresholds and settings per concept type.
v1 Production: Fixed thresholds (auto-calibration deferred).

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict

from .types import ConceptType, TypeThresholds


# =============================================================================
# THRESHOLDS BY TYPE (v1 Production - Fixed)
# =============================================================================

THRESHOLDS_BY_TYPE: Dict[ConceptType, TypeThresholds] = {
    ConceptType.ENTITY: TypeThresholds(
        concept_type=ConceptType.ENTITY,
        threshold_auto=0.95,  # Abaissé de 0.98 pour capturer pluriels/variantes
        threshold_defer=0.85,
    ),
    ConceptType.CONCEPT: TypeThresholds(
        concept_type=ConceptType.CONCEPT,
        threshold_auto=0.97,  # Abaissé de 0.99, reste restrictif
        threshold_defer=0.80,
        auto_safe_conditions={
            "exact_normalized_match": True,
            "definition_fingerprint_match": True,
            "stable_across_n_docs": 3,
        }
    ),
    ConceptType.ROLE: TypeThresholds(
        concept_type=ConceptType.ROLE,
        threshold_auto=0.93,  # Abaissé de 0.95
        threshold_defer=0.80,
    ),
    ConceptType.ORGANIZATION: TypeThresholds(
        concept_type=ConceptType.ORGANIZATION,
        threshold_auto=0.93,  # Abaissé de 0.95
        threshold_defer=0.85,
    ),
    ConceptType.DOCUMENT: TypeThresholds(
        concept_type=ConceptType.DOCUMENT,
        threshold_auto=0.95,  # Abaissé de 0.98
        threshold_defer=0.85,
    ),
    ConceptType.STANDARD: TypeThresholds(
        concept_type=ConceptType.STANDARD,
        threshold_auto=0.93,  # Abaissé de 0.95
        threshold_defer=0.85,
    ),
    ConceptType.PRACTICE: TypeThresholds(
        concept_type=ConceptType.PRACTICE,
        threshold_auto=0.95,  # Abaissé de 0.97
        threshold_defer=0.82,
    ),
    ConceptType.TOOL: TypeThresholds(
        concept_type=ConceptType.TOOL,
        threshold_auto=0.93,  # Abaissé de 0.95
        threshold_defer=0.85,
    ),
}


def get_type_thresholds(concept_type: ConceptType) -> TypeThresholds:
    """
    Get thresholds for a concept type.

    Args:
        concept_type: The concept type

    Returns:
        TypeThresholds for this type
    """
    return THRESHOLDS_BY_TYPE.get(
        concept_type,
        # Default fallback (conservative)
        TypeThresholds(
            concept_type=concept_type,
            threshold_auto=0.98,
            threshold_defer=0.85,
        )
    )


# =============================================================================
# BLOCKING CONFIGURATION
# =============================================================================

BLOCKING_CONFIG = {
    # Semantic blocking threshold (cheap pre-filter)
    "embedding_threshold": 0.75,

    # Max candidates per concept from Qdrant (default if type not specified)
    "qdrant_top_k": 20,

    # v1.1: Top-K caps by type to avoid explosion in dense zones
    "top_k_by_type": {
        "ENTITY": 25,      # Entities can be numerous
        "CONCEPT": 10,     # Concepts need more precision
        "ROLE": 15,        # Roles are usually distinct
        "ORGANIZATION": 15,
        "DOCUMENT": 10,
        "STANDARD": 15,
        "PRACTICE": 12,
        "TOOL": 12,
    },

    # Lexical blocking
    "enable_acronym_blocking": True,
    "enable_prefix_blocking": True,
    "prefix_min_length": 3,
}


# =============================================================================
# DEFER CONFIGURATION
# =============================================================================

DEFER_CONFIG = {
    # TTL for deferred candidates
    "ttl_days": 30,

    # Max deferred per tenant (bounded queue)
    "max_deferred_per_tenant": 1000,

    # Reevaluation settings
    "reevaluate_after_n_docs": 5,  # Reevaluate when N new docs arrive
    "reevaluate_batch_size": 100,
}


# =============================================================================
# CACHE CONFIGURATION
# =============================================================================

CACHE_CONFIG = {
    # Score cache TTL
    "score_cache_ttl_hours": 24,

    # Redis key prefix
    "redis_prefix": "er:scores:",

    # Max cached pairs
    "max_cached_pairs": 100000,
}


# =============================================================================
# REJECT STORE CONFIGURATION (v1.1)
# =============================================================================

REJECT_STORE_CONFIG = {
    # Long TTL for rejected pairs (avoid re-scoring)
    "ttl_days": 90,

    # Redis key prefix
    "redis_prefix": "er:reject:",
}


# =============================================================================
# CROSS-ENCODER CONFIGURATION
# =============================================================================

CROSS_ENCODER_CONFIG = {
    # Model name
    "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",

    # Batch size for scoring
    "batch_size": 32,

    # Cache predictions
    "cache_predictions": True,
}


def get_defer_ttl() -> timedelta:
    """Get TTL for deferred candidates."""
    return timedelta(days=DEFER_CONFIG["ttl_days"])
