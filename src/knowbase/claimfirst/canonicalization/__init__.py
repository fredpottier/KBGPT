"""Canonicalization utilities shared between cross-doc and embedding-cluster scripts."""

from knowbase.claimfirst.canonicalization.merge_validator import (
    LLMMergeValidator,
    MergeCandidate,
    MergeDecision,
    is_obvious_variant,
)

__all__ = [
    "LLMMergeValidator",
    "MergeCandidate",
    "MergeDecision",
    "is_obvious_variant",
]
