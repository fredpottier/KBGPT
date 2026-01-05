# Phase 2 OSMOSE - Relation Extraction Models
# Dataclasses et constantes pour l'extraction LLM de relations
#
# Extrait de llm_relation_extractor.py pour améliorer la modularité.

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from knowbase.relations.types import RelationType, RawAssertionFlags


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


@dataclass
class TypeFirstExtractionResult:
    """Résultat complet de l'extraction Type-First (Phase 2.10)."""
    relations: List[ExtractedRelationV4] = field(default_factory=list)
    unresolved_mentions: List[UnresolvedMention] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "UnresolvedMention",
    "ExtractedRelationV3",
    "IDFirstExtractionResult",
    "CORE_RELATION_TYPES_V4",
    "ExtractedRelationV4",
    "TypeFirstExtractionResult",
]
