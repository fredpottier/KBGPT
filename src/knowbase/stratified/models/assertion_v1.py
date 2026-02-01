"""
OSMOSE Pipeline V2 - Assertion Models V0/V1
============================================
Spec: ChatGPT "Two-pass Vision Evidence Contract" (2026-01-26)

V0 = Output brut extraction (chunk-level, pré-ancrage)
V1 = Persistable (DocItem-anchored, décision promotion, journalisation)

Règle d'ancrage : ANCHORED_IN = DocItem (jamais chunk)
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# ENUMS - Figés par spec
# ============================================================================

class AssertionTypeV1(str, Enum):
    """Types d'assertions (aligné avec AssertionType existant)."""
    DEFINITIONAL = "DEFINITIONAL"
    PRESCRIPTIVE = "PRESCRIPTIVE"
    CAUSAL = "CAUSAL"
    FACTUAL = "FACTUAL"
    CONDITIONAL = "CONDITIONAL"
    PERMISSIVE = "PERMISSIVE"
    COMPARATIVE = "COMPARATIVE"
    PROCEDURAL = "PROCEDURAL"


class SupportTier(str, Enum):
    """
    Tier de support pour la Promotion Policy.

    ALWAYS = Toujours promouvoir si lié à un concept
    CONDITIONAL = Promouvoir si confiance >= 0.7
    RARELY = Promouvoir seulement si confiance >= 0.9
    NEVER = Ne jamais promouvoir en Information
    """
    ALWAYS = "ALWAYS"
    CONDITIONAL = "CONDITIONAL"
    RARELY = "RARELY"
    NEVER = "NEVER"


class PromotionStatus(str, Enum):
    """Statut de promotion d'une assertion."""
    PROMOTED_LINKED = "PROMOTED_LINKED"      # Promue ET liée à un concept
    PROMOTED_UNLINKED = "PROMOTED_UNLINKED"  # Promue mais pas de concept match
    REJECTED = "REJECTED"                     # Rejetée (rule hard)
    ABSTAINED = "ABSTAINED"                   # Abstention (incertitude)


class RuleUsed(str, Enum):
    """
    Règle utilisée pour la décision (auditable).

    Permet de tracer exactement pourquoi une assertion a été
    PROMOTED, REJECTED ou ABSTAINED.
    """
    # Meta / qualité
    META_PATTERN_REJECT = "META_PATTERN_REJECT"
    FRAGMENT_REJECT = "FRAGMENT_REJECT"  # ChatGPT Priority 2: assertion minimale
    QUESTION_REJECT = "QUESTION_REJECT"  # ChatGPT Priority 2: questions filtrées
    TEXT_TOO_SHORT = "TEXT_TOO_SHORT"

    # Fix 2026-01-26: Language and extractive evidence
    LANG_MISMATCH_REJECT = "LANG_MISMATCH_REJECT"  # Assertion lang != doc lang
    NO_EXTRACTIVE_EVIDENCE = "NO_EXTRACTIVE_EVIDENCE"  # No exact_quote available
    VISION_SYNTHETIC_REJECT = "VISION_SYNTHETIC_REJECT"  # Vision description, not extraction

    # Ancrage
    ANCHOR_OK = "ANCHOR_OK"
    ANCHOR_NO_DOCITEM_MATCH = "ANCHOR_NO_DOCITEM_MATCH"
    ANCHOR_AMBIGUOUS_SPAN = "ANCHOR_AMBIGUOUS_SPAN"
    ANCHOR_CROSS_DOCITEM = "ANCHOR_CROSS_DOCITEM"

    # Promotion par type (tier)
    TYPE_ALWAYS = "TYPE_ALWAYS"
    TYPE_CONDITIONAL_PASS = "TYPE_CONDITIONAL_PASS"
    TYPE_CONDITIONAL_FAIL = "TYPE_CONDITIONAL_FAIL"
    TYPE_RARELY_PASS = "TYPE_RARELY_PASS"
    TYPE_RARELY_FAIL = "TYPE_RARELY_FAIL"
    TYPE_NEVER_REJECT = "TYPE_NEVER_REJECT"

    # Promotion par rôle / valeur (MVP V1)
    ROLE_ALWAYS = "ROLE_ALWAYS"
    ROLE_NO_CLAIMKEY = "ROLE_NO_CLAIMKEY"
    HAS_VALUE = "HAS_VALUE"

    # Addressability
    PIVOT_OK = "PIVOT_OK"
    PIVOT_VIOLATION = "PIVOT_VIOLATION"


class AbstainReason(str, Enum):
    """
    Raison d'abstention (uniquement si status=ABSTAINED).

    Raisons standardisées et auditables.
    """
    # Anchor resolution
    NO_DOCITEM_ANCHOR = "NO_DOCITEM_ANCHOR"
    AMBIGUOUS_SPAN = "AMBIGUOUS_SPAN"
    CROSS_DOCITEM = "CROSS_DOCITEM"

    # Linking / pivots
    NO_CONCEPT_MATCH = "NO_CONCEPT_MATCH"
    AMBIGUOUS_LINKING = "AMBIGUOUS_LINKING"
    NO_CLAIMKEY_MATCH = "NO_CLAIMKEY_MATCH"

    # Quality / routing
    GENERIC_TERM = "GENERIC_TERM"
    SINGLE_MENTION = "SINGLE_MENTION"
    HOSTILE_DOC = "HOSTILE_DOC"

    # Fix 2026-01-26: Language and extractive evidence
    LANG_MISMATCH = "LANG_MISMATCH"  # Assertion lang != document lang
    NO_EXTRACTIVE_QUOTE = "NO_EXTRACTIVE_QUOTE"  # Vision synthetic, no verbatim text
    VISION_ONLY_CONTENT = "VISION_ONLY_CONTENT"  # Content only visible in image, no text anchor


class RhetoricalRole(str, Enum):
    """Rôle rhétorique de l'assertion dans le texte."""
    FACT = "fact"
    EXAMPLE = "example"
    DEFINITION = "definition"
    INSTRUCTION = "instruction"
    CLAIM = "claim"
    CAUTION = "caution"


class ValueKind(str, Enum):
    """Type de valeur extraite."""
    NUMBER = "number"
    PERCENT = "percent"
    VERSION = "version"
    ENUM = "enum"
    BOOLEAN = "boolean"
    STRING = "string"


# ============================================================================
# WHITELIST - Types autorisés par défaut (tier ALWAYS)
# ============================================================================

WHITELIST_TYPES_V1 = {
    AssertionTypeV1.DEFINITIONAL,
    AssertionTypeV1.PRESCRIPTIVE,
    AssertionTypeV1.CAUSAL,
}


# ============================================================================
# V0 MODELS - Output brut extraction (chunk-level)
# ============================================================================

class SpanV0(BaseModel):
    """Position dans le chunk."""
    start: int = 0
    end: int = 0


class ValueV0(BaseModel):
    """Valeur extraite (nombre, pourcentage, version, etc.)."""
    kind: ValueKind
    raw: str
    normalized: Optional[Any] = None


class AssertionV0(BaseModel):
    """
    Assertion brute extraite du texte (V0 - pré-ancrage).

    Output du LLM au niveau chunk, avant résolution DocItem.
    """
    assertion_id: str
    text: str
    type: AssertionTypeV1
    confidence: float = Field(ge=0.0, le=1.0)
    exact_quote: Optional[str] = None
    span: SpanV0 = Field(default_factory=SpanV0)
    rhetorical_role: Optional[RhetoricalRole] = None
    value: Optional[ValueV0] = None


class LLMMetadata(BaseModel):
    """Métadonnées de l'appel LLM."""
    model: str
    latency_ms: int = 0


class AssertionBatchV0(BaseModel):
    """
    Batch d'assertions V0 pour un chunk.

    Output brut de l'extraction LLM.
    """
    version: str = "0"
    document_id: str
    chunk_id: str
    page_number: Optional[int] = None
    assertions: List[AssertionV0] = Field(default_factory=list)
    llm_metadata: Optional[LLMMetadata] = None


# ============================================================================
# V1 MODELS - Persistable (DocItem-anchored, décision)
# ============================================================================

class AnchorV1(BaseModel):
    """Ancrage DocItem (résolu depuis chunk)."""
    docitem_id: str
    span_start: int = 0
    span_end: int = 0


class PromotionDecision(BaseModel):
    """Décision de promotion avec règle utilisée."""
    status: PromotionStatus
    support_tier: SupportTier
    rule_used: RuleUsed
    abstain_reason: Optional[AbstainReason] = None


class PivotsV1(BaseModel):
    """
    Pivots de l'assertion (liens sémantiques).

    Au moins un pivot doit être non-null pour éviter PIVOT_VIOLATION.
    """
    theme_id: Optional[str] = None
    concept_id: Optional[str] = None
    claimkey_id: Optional[str] = None
    facets: List[str] = Field(default_factory=list)

    def is_addressable(self) -> bool:
        """Vérifie si l'assertion a au moins un pivot (addressability)."""
        return bool(
            self.theme_id or
            self.concept_id or
            self.claimkey_id or
            self.facets
        )


class ResolvedAssertionV1(BaseModel):
    """
    Assertion résolue (V1 - DocItem-anchored).

    Prête pour persistance avec décision de promotion.
    """
    assertion_id: str
    text: str
    type: AssertionTypeV1
    confidence: float = Field(ge=0.0, le=1.0)

    anchor: AnchorV1
    promotion: PromotionDecision
    pivots: PivotsV1 = Field(default_factory=PivotsV1)

    # Métadonnées optionnelles
    exact_quote: Optional[str] = None
    rhetorical_role: Optional[RhetoricalRole] = None
    value: Optional[ValueV0] = None


class AssertionLogEntry(BaseModel):
    """
    Entrée du journal d'assertions (audit trail).

    Chaque assertion traitée génère une entrée de log.
    """
    log_id: str
    assertion_id: str
    status: PromotionStatus
    rule_used: RuleUsed
    abstain_reason: Optional[AbstainReason] = None

    # Contexte
    docitem_id: str
    concept_id: Optional[str] = None
    theme_id: Optional[str] = None
    claimkey_id: Optional[str] = None

    # Détails pour debug
    reason_detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AssertionBatchV1(BaseModel):
    """
    Batch d'assertions V1 pour un document.

    Output final avec assertions résolues et log d'audit.
    """
    version: str = "1"
    document_id: str
    resolved_assertions: List[ResolvedAssertionV1] = Field(default_factory=list)
    assertion_log: List[AssertionLogEntry] = Field(default_factory=list)

    # Stats
    stats: Dict[str, int] = Field(default_factory=dict)


# ============================================================================
# MAPPING TYPE -> TIER (Promotion Policy)
# ============================================================================

TYPE_TO_TIER: Dict[AssertionTypeV1, SupportTier] = {
    AssertionTypeV1.DEFINITIONAL: SupportTier.ALWAYS,
    AssertionTypeV1.PRESCRIPTIVE: SupportTier.ALWAYS,
    AssertionTypeV1.CAUSAL: SupportTier.ALWAYS,
    AssertionTypeV1.FACTUAL: SupportTier.CONDITIONAL,
    AssertionTypeV1.CONDITIONAL: SupportTier.CONDITIONAL,
    AssertionTypeV1.PERMISSIVE: SupportTier.CONDITIONAL,
    AssertionTypeV1.COMPARATIVE: SupportTier.RARELY,
    AssertionTypeV1.PROCEDURAL: SupportTier.CONDITIONAL,  # ADR 2026-01-30: opérationnel, valeur métier
}


__all__ = [
    # Enums
    "AssertionTypeV1",
    "SupportTier",
    "PromotionStatus",
    "RuleUsed",
    "AbstainReason",
    "RhetoricalRole",
    "ValueKind",
    # Whitelist
    "WHITELIST_TYPES_V1",
    # V0 Models
    "SpanV0",
    "ValueV0",
    "AssertionV0",
    "LLMMetadata",
    "AssertionBatchV0",
    # V1 Models
    "AnchorV1",
    "PromotionDecision",
    "PivotsV1",
    "ResolvedAssertionV1",
    "AssertionLogEntry",
    "AssertionBatchV1",
    # Mapping
    "TYPE_TO_TIER",
]
