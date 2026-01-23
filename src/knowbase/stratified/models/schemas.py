"""
OSMOSE Pipeline V2 - Schémas Pydantic
=====================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md
Date: 2026-01-23

Contrat JSON canonique pour Pass 1 et structures associées.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================================
# ENUMS
# ============================================================================

class DocumentStructure(str, Enum):
    """Structure dominante du document."""
    CENTRAL = "CENTRAL"
    TRANSVERSAL = "TRANSVERSAL"
    CONTEXTUAL = "CONTEXTUAL"


class ConceptRole(str, Enum):
    """Rôle d'un concept dans le document."""
    CENTRAL = "CENTRAL"
    STANDARD = "STANDARD"
    CONTEXTUAL = "CONTEXTUAL"


class AssertionType(str, Enum):
    """Type d'assertion sémantique."""
    DEFINITIONAL = "DEFINITIONAL"
    PRESCRIPTIVE = "PRESCRIPTIVE"
    CAUSAL = "CAUSAL"
    FACTUAL = "FACTUAL"
    CONDITIONAL = "CONDITIONAL"
    PERMISSIVE = "PERMISSIVE"
    COMPARATIVE = "COMPARATIVE"
    PROCEDURAL = "PROCEDURAL"


class AssertionStatus(str, Enum):
    """Statut de l'assertion dans le journal."""
    PROMOTED = "PROMOTED"
    ABSTAINED = "ABSTAINED"
    REJECTED = "REJECTED"


class AssertionLogReason(str, Enum):
    """Raison standardisée pour le journal d'assertions."""
    # Promotion réussie
    PROMOTED = "promoted"

    # Promotion Policy
    LOW_CONFIDENCE = "low_confidence"
    POLICY_REJECTED = "policy_rejected"

    # Concept Linking
    NO_CONCEPT_MATCH = "no_concept_match"
    AMBIGUOUS_LINKING = "ambiguous_linking"

    # Anchor Resolution
    NO_DOCITEM_ANCHOR = "no_docitem_anchor"
    AMBIGUOUS_SPAN = "ambiguous_span"
    CROSS_DOCITEM = "cross_docitem"

    # Qualité
    GENERIC_TERM = "generic_term"
    SINGLE_MENTION = "single_mention"

    # Cross-doc (Pass 3)
    CONTRADICTS_EXISTING = "contradicts_existing"


class DocItemType(str, Enum):
    """Type d'item documentaire (Docling natif)."""
    PARAGRAPH = "paragraph"
    TABLE_ROW = "table_row"
    LIST_ITEM = "list_item"
    HEADING = "heading"
    FIGURE_CAPTION = "figure_caption"
    CODE_BLOCK = "code_block"
    FOOTNOTE = "footnote"


# ============================================================================
# STRUCTURES DOCUMENTAIRES (Pass 0)
# ============================================================================

class DocumentMeta(BaseModel):
    """Métadonnées du document."""
    doc_id: str
    title: Optional[str] = None
    language: str = "fr"
    content_hash: str
    source_url: Optional[str] = None
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class Section(BaseModel):
    """Section documentaire (structure)."""
    section_id: str
    title: str
    level: int = 1
    path: str  # Ex: "1 > 1.2 > 1.2.3"
    order: int


class DocItem(BaseModel):
    """Item documentaire atomique (surface de preuve)."""
    docitem_id: str
    type: DocItemType
    text: str
    page: Optional[int] = None
    char_start: int
    char_end: int
    order: int
    section_id: str


# ============================================================================
# STRUCTURES SÉMANTIQUES (Pass 1)
# ============================================================================

class Subject(BaseModel):
    """Sujet sémantique du document (1 par doc)."""
    subject_id: str
    text: str  # Résumé 1 phrase
    structure: DocumentStructure
    language: str
    justification: Optional[str] = None


class Theme(BaseModel):
    """Axe thématique du document."""
    theme_id: str
    name: str
    scoped_to_sections: list[str] = Field(default_factory=list)  # section_ids


class Concept(BaseModel):
    """Concept clé du document (frugal: 5-15 max)."""
    concept_id: str
    theme_id: str
    name: str
    role: ConceptRole = ConceptRole.STANDARD
    variants: list[str] = Field(default_factory=list)
    lex_key: Optional[str] = None  # Clé lexicale normalisée


class Anchor(BaseModel):
    """Ancrage sur DocItem (surface de preuve)."""
    docitem_id: str
    span_start: int  # Relatif au DocItem
    span_end: int


class Information(BaseModel):
    """Assertion promue et ancrée."""
    info_id: str
    concept_id: str
    text: str
    type: AssertionType
    confidence: float = Field(ge=0.0, le=1.0)
    anchor: Anchor
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# JOURNAL D'AUDIT
# ============================================================================

class AssertionLogEntry(BaseModel):
    """Entrée du journal d'assertions (audit)."""
    assertion_id: str
    text: str
    type: AssertionType
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: AssertionStatus
    reason: AssertionLogReason
    concept_id: Optional[str] = None
    anchor: Optional[Anchor] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# RÉSULTAT PASS 1 (CONTRAT JSON CANONIQUE)
# ============================================================================

class Pass1Stats(BaseModel):
    """Statistiques Pass 1."""
    themes_count: int = 0
    concepts_count: int = 0
    assertions_total: int = 0
    assertions_promoted: int = 0
    assertions_abstained: int = 0
    assertions_rejected: int = 0


class Pass1Result(BaseModel):
    """
    Résultat complet de Pass 1 (Lecture Stratifiée).

    Contrat JSON canonique pour persistance.
    Ref: ARCH_STRATIFIED_PIPELINE_V2.md
    """
    schema_version: str = "v2.pass1.1"
    tenant_id: str

    # Métadonnées document
    doc: DocumentMeta

    # Structure sémantique
    subject: Subject
    themes: list[Theme] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list, max_length=15)
    informations: list[Information] = Field(default_factory=list)

    # Journal d'audit
    assertion_log: list[AssertionLogEntry] = Field(default_factory=list)

    # Statistiques
    stats: Pass1Stats = Field(default_factory=Pass1Stats)

    def model_post_init(self, __context) -> None:
        """Calcule les stats si non fournies."""
        if self.stats.assertions_total == 0 and self.assertion_log:
            self.stats.assertions_total = len(self.assertion_log)
            self.stats.assertions_promoted = sum(
                1 for a in self.assertion_log if a.status == AssertionStatus.PROMOTED
            )
            self.stats.assertions_abstained = sum(
                1 for a in self.assertion_log if a.status == AssertionStatus.ABSTAINED
            )
            self.stats.assertions_rejected = sum(
                1 for a in self.assertion_log if a.status == AssertionStatus.REJECTED
            )
        if self.stats.themes_count == 0:
            self.stats.themes_count = len(self.themes)
        if self.stats.concepts_count == 0:
            self.stats.concepts_count = len(self.concepts)


# ============================================================================
# STRUCTURES PASS 3 (Cross-doc, stubs)
# ============================================================================

class CanonicalConcept(BaseModel):
    """Concept canonique (fusion cross-doc)."""
    canonical_id: str
    name: str
    merged_from: list[str] = Field(default_factory=list)  # concept_ids


class CanonicalTheme(BaseModel):
    """Thème canonique (fusion cross-doc)."""
    canonical_id: str
    name: str
    aligned_from: list[str] = Field(default_factory=list)  # theme_ids
