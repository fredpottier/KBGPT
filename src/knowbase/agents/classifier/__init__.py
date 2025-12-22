"""
OSMOSE Concept Kind Classifier Module

Phase 2.9.2: Classification domain-agnostic des concepts.
"""

from .types import (
    ConceptKind,
    ConceptClassification,
    ClassificationBatchResult,
    ConceptForClassification,
    KEEPABLE_KINDS,
    NON_KEEPABLE_KINDS,
)

from .concept_kind_classifier import (
    ConceptKindClassifier,
    enrich_concepts_with_kind,
)

__all__ = [
    # Types
    "ConceptKind",
    "ConceptClassification",
    "ClassificationBatchResult",
    "ConceptForClassification",
    "KEEPABLE_KINDS",
    "NON_KEEPABLE_KINDS",
    # Classifier
    "ConceptKindClassifier",
    "enrich_concepts_with_kind",
]
