# Phase 2 OSMOSE - Intelligence Relationnelle Avancée

from .types import (
    # Types de base
    RelationType,
    RelationMetadata,
    TypedRelation,
    RelationExtractionResult,
    ExtractionMethod,
    RelationStrength,
    RelationStatus,
    # Phase 2.8 - Architecture 2-Layer
    RelationMaturity,
    RawAssertionFlags,
    RawAssertion,
    PredicateProfile,
    CanonicalRelation,
    # Phase 2.11 - Claims (Assertions Unaires)
    ClaimValueType,
    ClaimMaturity,
    RawClaimFlags,
    RawClaim,
    ClaimSource,
    CanonicalClaim,
)
from .extraction_engine import RelationExtractionEngine
from .pattern_matcher import PatternMatcher
from .llm_relation_extractor import (
    LLMRelationExtractor,
    # Phase 2.8+ - ID-First Extraction
    UnresolvedMention,
    ExtractedRelationV3,
    IDFirstExtractionResult,
    # Phase 2.10 - Type-First Extraction
    CORE_RELATION_TYPES_V4,
    ExtractedRelationV4,
    TypeFirstExtractionResult,
)
from .neo4j_writer import Neo4jRelationshipWriter
# Phase 2.8 - RawAssertion Writer
from .raw_assertion_writer import (
    RawAssertionWriter,
    get_raw_assertion_writer,
    normalize_predicate,
    compute_fingerprint,
    compute_quality_penalty,
)
# Phase 2.8+ - UnresolvedMention Writer
from .unresolved_mention_writer import (
    UnresolvedMentionWriter,
    get_unresolved_mention_writer,
)
# Phase 2.9 - Segment-Level Catalogue Builder
from .catalogue_builder import (
    build_hybrid_catalogue,
    build_catalogue_for_segment_batch,
    CatalogueConfig,
    HybridCatalogue,
)
# Phase 2.9.4 - Doc-Level Extractor (Bucket 3)
from .doc_level_extractor import (
    DocLevelRelationExtractor,
    DocLevelRelation,
    DocLevelExtractionResult,
)
# Phase 2.11 - Claim Extractor
from .llm_claim_extractor import (
    LLMClaimExtractor,
    ClaimExtractionResult,
    ExtractedClaimV1,
    get_claim_extractor,
    compute_scope_key,
    compute_claim_fingerprint,
)

__all__ = [
    # Types de base
    "RelationType",
    "RelationMetadata",
    "TypedRelation",
    "RelationExtractionResult",
    "ExtractionMethod",
    "RelationStrength",
    "RelationStatus",
    # Phase 2.8 - Architecture 2-Layer
    "RelationMaturity",
    "RawAssertionFlags",
    "RawAssertion",
    "PredicateProfile",
    "CanonicalRelation",
    # Engines
    "RelationExtractionEngine",
    "PatternMatcher",
    "LLMRelationExtractor",
    "Neo4jRelationshipWriter",
    # Phase 2.8 - RawAssertion Writer
    "RawAssertionWriter",
    "get_raw_assertion_writer",
    "normalize_predicate",
    "compute_fingerprint",
    "compute_quality_penalty",
    # Phase 2.8+ - ID-First Extraction
    "UnresolvedMention",
    "ExtractedRelationV3",
    "IDFirstExtractionResult",
    "UnresolvedMentionWriter",
    "get_unresolved_mention_writer",
    # Phase 2.10 - Type-First Extraction
    "CORE_RELATION_TYPES_V4",
    "ExtractedRelationV4",
    "TypeFirstExtractionResult",
    # Phase 2.9 - Segment-Level Catalogue Builder
    "build_hybrid_catalogue",
    "build_catalogue_for_segment_batch",
    "CatalogueConfig",
    "HybridCatalogue",
    # Phase 2.9.4 - Doc-Level Extractor (Bucket 3)
    "DocLevelRelationExtractor",
    "DocLevelRelation",
    "DocLevelExtractionResult",
    # Phase 2.11 - Claims (Assertions Unaires)
    "ClaimValueType",
    "ClaimMaturity",
    "RawClaimFlags",
    "RawClaim",
    "ClaimSource",
    "CanonicalClaim",
    # Phase 2.11 - Claim Extractor
    "LLMClaimExtractor",
    "ClaimExtractionResult",
    "ExtractedClaimV1",
    "get_claim_extractor",
    "compute_scope_key",
    "compute_claim_fingerprint",
]
