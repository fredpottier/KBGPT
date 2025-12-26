"""
Phase 2.12 - Entity Resolution Types

Core data structures for entity resolution pipeline.

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field


class ConceptType(str, Enum):
    """Generic concept types (domain-agnostic)."""
    ENTITY = "ENTITY"
    CONCEPT = "CONCEPT"
    ROLE = "ROLE"
    ORGANIZATION = "ORGANIZATION"
    DOCUMENT = "DOCUMENT"
    STANDARD = "STANDARD"
    PRACTICE = "PRACTICE"  # Added for OSMOSE extracted types
    TOOL = "TOOL"  # Added for OSMOSE extracted types

    @classmethod
    def from_string(cls, value: str) -> "ConceptType":
        """Convert string to ConceptType (case-insensitive, with fallback)."""
        if not value:
            return cls.ENTITY
        upper_value = value.upper()
        try:
            return cls(upper_value)
        except ValueError:
            # Fallback to ENTITY for unknown types
            return cls.ENTITY


class DecisionType(str, Enum):
    """Entity resolution decision types."""
    AUTO = "AUTO"        # Merge immediately (high confidence)
    DEFER = "DEFER"      # Wait for more evidence
    REJECT = "REJECT"    # Do not merge


class SignalBreakdown(BaseModel):
    """Breakdown of similarity signals."""
    exact_match: float = Field(default=0.0, description="Exact normalized name match")
    acronym_expansion: float = Field(default=0.0, description="Acronym <-> expansion match")
    alias_overlap: float = Field(default=0.0, description="Shared surface forms")
    embedding_similarity: float = Field(default=0.0, description="Embedding cosine similarity")
    cross_encoder_score: float = Field(default=0.0, description="Cross-encoder pairwise score")
    same_document: float = Field(default=0.0, description="Appeared in same document")

    def weighted_score(self) -> float:
        """Compute weighted aggregate score."""
        weights = {
            "exact_match": 1.0,
            "acronym_expansion": 0.9,
            "alias_overlap": 0.85,
            "embedding_similarity": 0.7,
            "cross_encoder_score": 0.8,
            "same_document": 0.3,
        }
        total = 0.0
        weight_sum = 0.0
        for signal, weight in weights.items():
            value = getattr(self, signal, 0.0)
            if value > 0:
                total += value * weight
                weight_sum += weight
        return total / weight_sum if weight_sum > 0 else 0.0


class TypeThresholds(BaseModel):
    """Thresholds for a concept type."""
    concept_type: ConceptType
    threshold_auto: float = Field(description="Threshold for AUTO decision")
    threshold_defer: float = Field(description="Threshold for DEFER decision")
    auto_safe_conditions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional conditions for AUTO (e.g., CONCEPT requires exact + definition match)"
    )


class MergeCandidate(BaseModel):
    """A pair of concepts that are candidates for merging."""
    concept_a_id: str
    concept_b_id: str
    concept_a_name: str
    concept_b_name: str
    concept_type: ConceptType

    # Similarity
    similarity_score: float
    signals: SignalBreakdown

    # Evidence
    has_exact_match: bool = False
    has_acronym_match: bool = False
    has_definition_match: bool = False
    shared_surface_forms: List[str] = Field(default_factory=list)

    # Metadata
    doc_count_a: int = 0
    doc_count_b: int = 0

    def pair_id(self) -> str:
        """Generate stable pair ID (sorted to be order-independent)."""
        ids = sorted([self.concept_a_id, self.concept_b_id])
        return f"{ids[0]}|{ids[1]}"


class DeferredMergeCandidate(BaseModel):
    """A merge candidate that was deferred for later evaluation."""
    pair_id: str = Field(description="Unique pair identifier")
    concept_a_id: str
    concept_b_id: str
    concept_a_name: str
    concept_b_name: str
    concept_type: ConceptType
    tenant_id: str = "default"

    # Scores
    similarity_score: float
    signals: SignalBreakdown

    # Evidence
    has_exact_match: bool = False
    has_acronym_match: bool = False
    shared_surface_forms: List[str] = Field(default_factory=list)

    # Metadata
    doc_count_a: int = 0
    doc_count_b: int = 0
    shared_doc_count: int = 0  # Docs where both appear

    # Lifecycle
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    evaluation_count: int = 1
    expires_at: datetime

    # Status
    status: DecisionType = DecisionType.DEFER


class MergeResult(BaseModel):
    """Result of a merge operation."""
    success: bool
    survivor_id: str = Field(description="ID of the surviving concept")
    merged_id: str = Field(description="ID of the merged (removed) concept")
    merge_reason: str
    merge_method: str = "entity_resolution"
    similarity_score: float
    signals: SignalBreakdown
    merged_at: datetime = Field(default_factory=datetime.utcnow)

    # What was migrated
    aliases_migrated: List[str] = Field(default_factory=list)
    relations_migrated: int = 0
    claims_migrated: int = 0


class EntityResolutionStats(BaseModel):
    """Statistics for entity resolution pipeline."""
    total_concepts: int = 0
    candidates_generated: int = 0
    auto_merges: int = 0
    deferred: int = 0
    rejected: int = 0

    # Queue stats
    deferred_queue_size: int = 0
    deferred_resolved_today: int = 0
    deferred_expired_today: int = 0

    # Quality metrics
    auto_rate: float = 0.0  # % of decisions that are AUTO
    defer_resolution_rate: float = 0.0  # % of DEFER that become AUTO

    # Timing
    last_run_at: Optional[datetime] = None
    last_run_duration_ms: Optional[float] = None
