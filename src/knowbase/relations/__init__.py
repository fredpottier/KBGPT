# Phase 2 OSMOSE - Intelligence Relationnelle Avancée

from .types import (
    RelationType,
    RelationMetadata,
    TypedRelation,
    RelationExtractionResult,
    ExtractionMethod,
    RelationStrength,
    RelationStatus
)
from .extraction_engine import RelationExtractionEngine
from .pattern_matcher import PatternMatcher

__all__ = [
    # Types
    "RelationType",
    "RelationMetadata",
    "TypedRelation",
    "RelationExtractionResult",
    "ExtractionMethod",
    "RelationStrength",
    "RelationStatus",
    # Engines
    "RelationExtractionEngine",
    "PatternMatcher",
]
