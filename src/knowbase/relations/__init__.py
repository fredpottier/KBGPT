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
    # ADR Relations Discursivement Déterminées
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    SemanticGrade,
    DefensibilityTier,
    SupportStrength,
    SemanticRelation,
    compute_semantic_grade,
    compute_bundle_diversity,
)
# ADR Relations Discursivement Déterminées - Règles d'attribution du tier
from .tier_attribution import (
    # Whitelists
    DISCURSIVE_ALLOWED_RELATION_TYPES,
    DISCURSIVE_FORBIDDEN_RELATION_TYPES,
    DISCURSIVE_ALLOWED_EXTRACTION_METHODS,
    # Bases
    STRONG_DETERMINISTIC_BASES,
    WEAK_DETERMINISTIC_BASES,
    STRONG_BASIS_MARKERS,
    # Classes et fonctions
    TierAttributionResult,
    is_relation_type_allowed_for_discursive,
    is_extraction_method_allowed_for_discursive,
    has_strong_deterministic_basis,
    compute_tier_for_discursive,
    compute_defensibility_tier,
    validate_discursive_assertion,
    should_abstain,
)
from .types import (
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
# Phase 2.11 - RawClaim Writer
from .raw_claim_writer import (
    RawClaimWriter,
    get_raw_claim_writer,
    compute_claim_fingerprint as compute_raw_claim_fingerprint,
)
# Phase 2.11 - Claim Consolidator
from .claim_consolidator import (
    ClaimConsolidator,
    get_claim_consolidator,
)
# Phase 2.11 - CanonicalClaim Writer
from .canonical_claim_writer import (
    CanonicalClaimWriter,
    get_canonical_claim_writer,
)
# Phase 2.8/2.10 - Relation Consolidator
from .relation_consolidator import (
    RelationConsolidator,
    get_relation_consolidator,
)
# Phase 2.8/2.10 - CanonicalRelation Writer
from .canonical_relation_writer import (
    CanonicalRelationWriter,
    get_canonical_relation_writer,
)
# ADR Relations Discursivement Déterminées - SemanticRelation Writer
from .semantic_relation_writer import (
    SemanticRelationWriter,
    get_semantic_relation_writer,
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
    # ADR Relations Discursivement Déterminées
    "AssertionKind",
    "DiscursiveBasis",
    "DiscursiveAbstainReason",
    "SemanticGrade",
    "DefensibilityTier",
    "SupportStrength",
    "SemanticRelation",
    "compute_semantic_grade",
    "compute_bundle_diversity",
    # ADR Relations Discursivement Déterminées - Tier Attribution
    "DISCURSIVE_ALLOWED_RELATION_TYPES",
    "DISCURSIVE_FORBIDDEN_RELATION_TYPES",
    "DISCURSIVE_ALLOWED_EXTRACTION_METHODS",
    "STRONG_DETERMINISTIC_BASES",
    "WEAK_DETERMINISTIC_BASES",
    "STRONG_BASIS_MARKERS",
    "TierAttributionResult",
    "is_relation_type_allowed_for_discursive",
    "is_extraction_method_allowed_for_discursive",
    "has_strong_deterministic_basis",
    "compute_tier_for_discursive",
    "compute_defensibility_tier",
    "validate_discursive_assertion",
    "should_abstain",
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
    # Phase 2.11 - RawClaim Writer
    "RawClaimWriter",
    "get_raw_claim_writer",
    "compute_raw_claim_fingerprint",
    # Phase 2.11 - Claim Consolidator
    "ClaimConsolidator",
    "get_claim_consolidator",
    # Phase 2.11 - CanonicalClaim Writer
    "CanonicalClaimWriter",
    "get_canonical_claim_writer",
    # Phase 2.8/2.10 - Relation Consolidator
    "RelationConsolidator",
    "get_relation_consolidator",
    # Phase 2.8/2.10 - CanonicalRelation Writer
    "CanonicalRelationWriter",
    "get_canonical_relation_writer",
    # ADR Relations Discursivement Déterminées - SemanticRelation Writer
    "SemanticRelationWriter",
    "get_semantic_relation_writer",
]
