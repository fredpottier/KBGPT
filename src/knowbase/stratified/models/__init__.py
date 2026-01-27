"""OSMOSE Pipeline V2 - Modèles Pydantic et Dataclasses."""

from .schemas import (
    # Enums
    DocumentStructure,
    ConceptRole,
    AssertionType,
    AssertionStatus,
    AssertionLogReason,
    DocItemType,
    # Structures documentaires
    DocumentMeta,
    Section,
    DocItem,
    # Structures sémantiques
    Subject,
    Theme,
    Concept,
    Anchor,
    Information,
    # Journal
    AssertionLogEntry,
    # Résultat Pass 1
    Pass1Stats,
    Pass1Result,
    # Pass 3 (stubs)
    CanonicalConcept,
    CanonicalTheme,
)

# MVP V1 - Nouveaux modèles pour Usage B (Challenge de Texte)
from .information import (
    InformationMVP,
    InformationType,
    RhetoricalRole,
    PromotionStatus,
    ValueKind,
    ValueComparable,
    InheritanceMode,
    ValueInfo,
    SpanInfo,
    ContextInfo,
)

from .claimkey import (
    ClaimKey,
    ClaimKeyStatus,
)

from .contradiction import (
    Contradiction,
    ContradictionNature,
    TensionLevel,
)

# V1 Assertion Models (Spec ChatGPT 2026-01-26)
from .assertion_v1 import (
    # Enums
    AssertionTypeV1,
    SupportTier,
    PromotionStatus as PromotionStatusV1,
    RuleUsed,
    AbstainReason,
    RhetoricalRole as RhetoricalRoleV1,
    ValueKind as ValueKindV1,
    # Whitelist
    WHITELIST_TYPES_V1,
    # V0 Models
    SpanV0,
    ValueV0,
    AssertionV0,
    LLMMetadata,
    AssertionBatchV0,
    # V1 Models
    AnchorV1,
    PromotionDecision,
    PivotsV1,
    ResolvedAssertionV1,
    AssertionLogEntry as AssertionLogEntryV1,
    AssertionBatchV1,
    # Mapping
    TYPE_TO_TIER,
)

# Volet B: LLM Schemas pour vLLM Structured Outputs
# Import conditionnel pour éviter erreur si pydantic pas à jour
try:
    from knowbase.stratified.pass1.llm_schemas import (
        # Response Models
        DocumentAnalysisResponse,
        ConceptIdentificationResponse,
        AssertionExtractionResponse,
        SemanticLinkingResponse,
        # Helpers
        get_schema_for_phase,
        get_vllm_response_format,
        SCHEMA_REGISTRY,
    )
    LLM_SCHEMAS_AVAILABLE = True
except ImportError:
    LLM_SCHEMAS_AVAILABLE = False

# Pointer-Based Extraction Schemas (Anti-Reformulation)
try:
    from knowbase.stratified.pass1.pointer_schemas import (
        # Enums
        PointerConceptType,
        ValueKind as PointerValueKind,
        # Pydantic Models
        PointerConcept,
        PointerExtractionResponse,
        # Dataclasses
        ConceptCandidate,
        ConceptAnchored,
        Anchor as PointerAnchor,
        PointerExtractionResult,
        # Helpers
        get_pointer_extraction_schema,
        parse_pointer_response,
        pointer_to_anchored,
    )
    POINTER_SCHEMAS_AVAILABLE = True
except ImportError:
    POINTER_SCHEMAS_AVAILABLE = False

# Assertion Unit Indexer
try:
    from knowbase.stratified.pass1.assertion_unit_indexer import (
        AssertionUnit,
        UnitIndexResult,
        AssertionUnitIndexer,
        index_docitems_to_units,
        format_units_for_llm,
        lookup_unit_text,
    )
    UNIT_INDEXER_AVAILABLE = True
except ImportError:
    UNIT_INDEXER_AVAILABLE = False

# Pointer Validator
try:
    from knowbase.stratified.pass1.pointer_validator import (
        ValidationStatus,
        AbstainReason,
        ValidationResult,
        PointerValidationStats,
        PointerValidator,
        validate_pointer_concept,
        reconstruct_exact_quote,
    )
    POINTER_VALIDATOR_AVAILABLE = True
except ImportError:
    POINTER_VALIDATOR_AVAILABLE = False

__all__ = [
    # Existants (schemas.py)
    "DocumentStructure",
    "ConceptRole",
    "AssertionType",
    "AssertionStatus",
    "AssertionLogReason",
    "DocItemType",
    "DocumentMeta",
    "Section",
    "DocItem",
    "Subject",
    "Theme",
    "Concept",
    "Anchor",
    "Information",
    "AssertionLogEntry",
    "Pass1Stats",
    "Pass1Result",
    "CanonicalConcept",
    "CanonicalTheme",
    # MVP V1 - Nouveaux modèles
    "InformationMVP",
    "InformationType",
    "RhetoricalRole",
    "PromotionStatus",
    "ValueKind",
    "ValueComparable",
    "InheritanceMode",
    "ValueInfo",
    "SpanInfo",
    "ContextInfo",
    "ClaimKey",
    "ClaimKeyStatus",
    "Contradiction",
    "ContradictionNature",
    "TensionLevel",
    # V1 Assertion Models (Spec ChatGPT 2026-01-26)
    "AssertionTypeV1",
    "SupportTier",
    "PromotionStatusV1",
    "RuleUsed",
    "AbstainReason",
    "RhetoricalRoleV1",
    "ValueKindV1",
    "WHITELIST_TYPES_V1",
    "SpanV0",
    "ValueV0",
    "AssertionV0",
    "LLMMetadata",
    "AssertionBatchV0",
    "AnchorV1",
    "PromotionDecision",
    "PivotsV1",
    "ResolvedAssertionV1",
    "AssertionLogEntryV1",
    "AssertionBatchV1",
    "TYPE_TO_TIER",
    # Volet B: LLM Schemas (conditional)
    "LLM_SCHEMAS_AVAILABLE",
    # Pointer-Based Extraction (conditional)
    "POINTER_SCHEMAS_AVAILABLE",
    "UNIT_INDEXER_AVAILABLE",
    "POINTER_VALIDATOR_AVAILABLE",
]

# Ajouter les exports conditionnels si disponibles
if LLM_SCHEMAS_AVAILABLE:
    __all__.extend([
        "DocumentAnalysisResponse",
        "ConceptIdentificationResponse",
        "AssertionExtractionResponse",
        "SemanticLinkingResponse",
        "get_schema_for_phase",
        "get_vllm_response_format",
        "SCHEMA_REGISTRY",
    ])

if POINTER_SCHEMAS_AVAILABLE:
    __all__.extend([
        "PointerConceptType",
        "PointerValueKind",
        "PointerConcept",
        "PointerExtractionResponse",
        "ConceptCandidate",
        "ConceptAnchored",
        "PointerAnchor",
        "PointerExtractionResult",
        "get_pointer_extraction_schema",
        "parse_pointer_response",
        "pointer_to_anchored",
    ])

if UNIT_INDEXER_AVAILABLE:
    __all__.extend([
        "AssertionUnit",
        "UnitIndexResult",
        "AssertionUnitIndexer",
        "index_docitems_to_units",
        "format_units_for_llm",
        "lookup_unit_text",
    ])

if POINTER_VALIDATOR_AVAILABLE:
    __all__.extend([
        "ValidationStatus",
        "ValidationResult",
        "PointerValidationStats",
        "PointerValidator",
        "validate_pointer_concept",
        "reconstruct_exact_quote",
    ])
