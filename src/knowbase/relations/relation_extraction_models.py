# Phase 2 OSMOSE - Relation Extraction Models
# Dataclasses et constantes pour l'extraction LLM de relations
#
# Extrait de llm_relation_extractor.py pour améliorer la modularité.
# Phase 2.11 - Ajout SupportSpan et CorefResolutionPath pour intégration Pass 0.5

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

from knowbase.relations.types import RelationType, RawAssertionFlags


# =============================================================================
# Phase 2.11 - SupportSpan et CorefResolution (Intégration Pass 0.5)
# =============================================================================

class AnchorType(str, Enum):
    """Type d'ancrage d'un concept dans une assertion.

    Distingue l'ancrage lexical (direct) de l'ancrage référentiel (via coréférence).
    """
    LEXICAL = "LEXICAL"        # Le texte nomme explicitement le concept ("TLS")
    REFERENTIAL = "REFERENTIAL"  # Le texte réfère au concept via pronom/anaphore ("Il" → TLS)


@dataclass
class SupportSpan:
    """
    Span de support référentiel pour un sujet/objet pronominal.

    Quand une assertion a un sujet/objet pronominal (ex: "Il sécurise..."),
    le SupportSpan capture:
    - Le span exact du pronom dans le texte (evidence intacte)
    - L'ID du MentionSpan correspondant dans le CorefGraph
    - Le type d'ancrage (toujours REFERENTIAL pour un SupportSpan)

    Invariants respectés:
    - L1: Evidence-preserving (span exact, pas de réécriture)
    - L5: Chemin de résolution auditable

    Ref: ADR Linguistic Coreference Layer (Pass 0.5)
    """
    # Span exact du pronom/anaphore dans le texte
    span_start: int
    span_end: int
    surface_form: str  # "Il", "elle", "it", etc.

    # Référence au MentionSpan dans le CorefGraph
    mention_span_id: str

    # Type d'ancrage (toujours REFERENTIAL pour SupportSpan)
    anchor_type: AnchorType = AnchorType.REFERENTIAL

    # Métadonnées optionnelles
    mention_type: Optional[str] = None  # PRONOUN, NP, etc.
    sentence_index: Optional[int] = None


@dataclass
class CorefResolutionStep:
    """
    Étape dans le chemin de résolution de coréférence.

    Trace un pas dans la chaîne: MentionSpan(Il) → CorefLink → MentionSpan(TLS)
    """
    step_type: str  # "COREF_LINK" | "COREF_DECISION" | "CHAIN_MEMBERSHIP"
    source_id: str  # ID du noeud source
    target_id: str  # ID du noeud cible
    confidence: float = 0.0
    method: str = ""  # "spacy_coref" | "coreferee" | "rule_based" | "llm_arbiter"


@dataclass
class CorefResolutionPath:
    """
    Chemin complet de résolution de coréférence.

    Trace comment un pronom a été résolu vers un concept:
    MentionSpan("Il") → CorefLink → MentionSpan("TLS") → ProtoConcept(TLS)

    Ce chemin est la preuve auditable que la résolution est légitime
    et non une inférence sémantique inventée.

    Exemple:
        - source_mention_id: "mention_il_001"
        - target_mention_id: "mention_tls_001"
        - resolved_concept_id: "proto_tls_001"
        - steps: [CorefResolutionStep(COREF_LINK, ...)]
        - resolution_confidence: 0.92
    """
    # Point de départ (pronom/anaphore)
    source_mention_id: str
    source_surface: str  # "Il"

    # Point d'arrivée (mention lexicale)
    target_mention_id: str
    target_surface: str  # "TLS"

    # Concept résolu
    resolved_concept_id: str
    resolved_concept_name: str

    # Chemin de résolution (audit trail)
    steps: List[CorefResolutionStep] = field(default_factory=list)

    # Confiance globale de la résolution
    resolution_confidence: float = 0.0

    # Méthode utilisée
    resolution_method: str = ""  # "spacy_coref" | "coreferee" | "rule_based" | "hybrid"

    # Flags d'audit
    is_ambiguous: bool = False  # True si plusieurs candidats possibles
    abstained: bool = False  # True si résolution impossible (abstention)


# =============================================================================
# Phase 2.8+ - Dataclasses pour résultats ID-First
# =============================================================================

@dataclass
class UnresolvedMention:
    """Mention d'entité non trouvée dans le catalogue."""
    mention: str
    context: str
    suggested_type: Optional[str] = None


@dataclass
class ExtractedRelationV3:
    """Relation extraite avec IDs résolus (post index→concept_id mapping)."""
    subject_concept_id: str
    object_concept_id: str
    predicate_raw: str
    evidence: str
    confidence: float
    flags: RawAssertionFlags
    subject_surface_form: str
    object_surface_form: str


@dataclass
class IDFirstExtractionResult:
    """Résultat complet de l'extraction ID-First (Phase 2.8+)."""
    relations: List[ExtractedRelationV3] = field(default_factory=list)
    unresolved_mentions: List[UnresolvedMention] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


# =============================================================================
# Phase 2.10 - Type-First Extraction (Closed Set + Multi-Sourcing)
# =============================================================================

# Les 12 types Core domain-agnostic pour V4
CORE_RELATION_TYPES_V4 = {
    "PART_OF", "SUBTYPE_OF",  # Structurel
    "REQUIRES", "ENABLES", "USES", "INTEGRATES_WITH", "APPLIES_TO",  # Dépendance
    "CAUSES", "PREVENTS",  # Causalité
    "VERSION_OF", "REPLACES",  # Temporel
    "ASSOCIATED_WITH",  # Fallback
}


@dataclass
class ExtractedRelationV4:
    """
    Relation extraite Phase 2.10 - Type-First avec set fermé.

    Nouveaux champs vs V3:
    - relation_type: Type forcé parmi les 12 Core
    - type_confidence: Confiance LLM sur le type
    - alt_type: Type alternatif si ambiguïté
    - alt_type_confidence: Confiance sur l'alternatif
    - relation_subtype_raw: Nuance sémantique fine (audit only)
    - context_hint: Scope/contexte local

    Phase 2.11 - Intégration Pass 0.5 (Coreference):
    - subject_support_span: Si sujet pronominal, span du pronom
    - object_support_span: Si objet pronominal, span du pronom
    - subject_resolution_path: Chemin de résolution coréf pour sujet
    - object_resolution_path: Chemin de résolution coréf pour objet
    - subject_anchor_type: LEXICAL ou REFERENTIAL
    - object_anchor_type: LEXICAL ou REFERENTIAL
    """
    # Identité relation
    subject_concept_id: str
    object_concept_id: str

    # Type forcé (Phase 2.10)
    relation_type: RelationType
    type_confidence: float
    alt_type: Optional[RelationType] = None
    alt_type_confidence: Optional[float] = None

    # Prédicat brut (pour audit)
    predicate_raw: str = ""
    relation_subtype_raw: Optional[str] = None

    # Evidence
    evidence: str = ""
    evidence_start_char: Optional[int] = None
    evidence_end_char: Optional[int] = None
    context_hint: Optional[str] = None

    # Scores
    confidence: float = 0.7  # Confidence extraction globale

    # Flags sémantiques
    flags: RawAssertionFlags = field(default_factory=RawAssertionFlags)

    # Surface forms
    subject_surface_form: str = ""
    object_surface_form: str = ""

    # ==========================================================================
    # Phase 2.11 - Support Spans pour sujets/objets pronominaux (Pass 0.5)
    # ==========================================================================

    # Type d'ancrage pour le sujet et l'objet
    subject_anchor_type: AnchorType = AnchorType.LEXICAL
    object_anchor_type: AnchorType = AnchorType.LEXICAL

    # Support spans (si sujet/objet pronominal)
    # Contient le span exact du pronom dans le texte
    subject_support_span: Optional[SupportSpan] = None
    object_support_span: Optional[SupportSpan] = None

    # Chemins de résolution coréférence (audit trail)
    # Trace comment le pronom a été résolu vers le concept
    subject_resolution_path: Optional[CorefResolutionPath] = None
    object_resolution_path: Optional[CorefResolutionPath] = None

    @property
    def has_pronominal_subject(self) -> bool:
        """True si le sujet est résolu via coréférence."""
        return self.subject_anchor_type == AnchorType.REFERENTIAL

    @property
    def has_pronominal_object(self) -> bool:
        """True si l'objet est résolu via coréférence."""
        return self.object_anchor_type == AnchorType.REFERENTIAL

    @property
    def is_coref_derived(self) -> bool:
        """True si au moins un argument est résolu via coréférence."""
        return self.has_pronominal_subject or self.has_pronominal_object


@dataclass
class TypeFirstExtractionResult:
    """Résultat complet de l'extraction Type-First (Phase 2.10)."""
    relations: List[ExtractedRelationV4] = field(default_factory=list)
    unresolved_mentions: List[UnresolvedMention] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    # Phase 2.11 - SupportSpan et CorefResolution
    "AnchorType",
    "SupportSpan",
    "CorefResolutionStep",
    "CorefResolutionPath",
    # Phase 2.8+
    "UnresolvedMention",
    "ExtractedRelationV3",
    "IDFirstExtractionResult",
    # Phase 2.10
    "CORE_RELATION_TYPES_V4",
    "ExtractedRelationV4",
    "TypeFirstExtractionResult",
]
