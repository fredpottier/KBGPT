"""
Schémas Pydantic pour les Concepts (Phase 2 - Intelligence Avancée).

POC "Explain this Concept" - Exploitation du cross-référencement Neo4j ↔ Qdrant
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SourceChunk(BaseModel):
    """Chunk source d'un concept avec métadonnées."""

    chunk_id: str = Field(..., description="ID du chunk dans Qdrant")
    text: str = Field(..., description="Texte extrait du chunk")
    document_name: Optional[str] = Field(None, description="Nom du document source")
    slide_number: Optional[int] = Field(None, description="Numéro de slide (si PPTX)")
    page_number: Optional[int] = Field(None, description="Numéro de page (si PDF)")
    score: Optional[float] = Field(None, description="Score de pertinence (si recherche)")


class RelatedConcept(BaseModel):
    """Concept lié via relations Neo4j."""

    canonical_id: str = Field(..., description="ID canonique du concept lié")
    name: str = Field(..., description="Nom du concept")
    relationship_type: str = Field(..., description="Type de relation (RELATED_TO, PART_OF, etc.)")
    direction: str = Field(..., description="Direction: 'outgoing' ou 'incoming'")


class ConceptExplanation(BaseModel):
    """Explication complète d'un concept avec sources et relations."""

    canonical_id: str = Field(..., description="ID canonique du concept")
    name: Optional[str] = Field(None, description="Nom canonique du concept")
    aliases: List[str] = Field(default_factory=list, description="Variantes/synonymes du concept")
    summary: Optional[str] = Field(None, description="Résumé généré du concept")
    source_chunks: List[SourceChunk] = Field(
        default_factory=list,
        description="Chunks sources où le concept apparaît"
    )
    related_concepts: List[RelatedConcept] = Field(
        default_factory=list,
        description="Concepts liés via le graph"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles (timestamps, counts, etc.)"
    )


class ConceptExplanationRequest(BaseModel):
    """Requête pour expliquer un concept."""

    canonical_id: str = Field(..., description="ID canonique du concept à expliquer")
    include_chunks: bool = Field(default=True, description="Inclure les chunks sources")
    include_relations: bool = Field(default=True, description="Inclure les concepts liés")
    max_chunks: int = Field(default=10, ge=1, le=50, description="Nombre max de chunks à retourner")
    max_relations: int = Field(default=10, ge=1, le=50, description="Nombre max de relations à retourner")


# =============================================================================
# Hybrid Anchor Model - Phase 2 Architecture
# =============================================================================
# ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md
# ADR: doc/ongoing/ADR_ASSERTION_AWARE_KG.md (PR2 - AnchorContext)

from enum import Enum


# === Assertion Context Enums (PR2) ===

class Polarity(str, Enum):
    """
    Polarite de l'assertion.

    Indique si le concept est affirme positivement, nie, futur, etc.
    ADR: ADR_ASSERTION_AWARE_KG.md - Section 4.2
    """
    POSITIVE = "positive"           # Concept present/affirme
    NEGATIVE = "negative"           # Concept nie/absent
    FUTURE = "future"               # Prevu pour le futur
    DEPRECATED = "deprecated"       # Obsolete/abandonne
    CONDITIONAL = "conditional"     # Depend de conditions
    UNKNOWN = "unknown"             # Impossible a determiner


class AssertionScope(str, Enum):
    """
    Scope de l'assertion.

    Indique si l'assertion s'applique generalement ou de maniere contrainte.
    ADR: ADR_ASSERTION_AWARE_KG.md - Section 4.2
    """
    GENERAL = "general"             # S'applique a toutes les variantes
    CONSTRAINED = "constrained"     # S'applique a une/des variantes specifiques
    UNKNOWN = "unknown"             # Impossible a determiner


class QualifierSource(str, Enum):
    """
    Source du qualificateur de contexte.

    Indique d'ou vient l'information de scope.
    ADR: ADR_ASSERTION_AWARE_KG.md - Section 4.2
    """
    EXPLICIT = "explicit"               # Marqueur explicite dans le passage
    INHERITED_STRONG = "inherited_strong"  # Herite du DocContext (strong)
    INHERITED_WEAK = "inherited_weak"      # Herite du DocContext (weak)
    NONE = "none"                       # Pas de qualificateur


# === Existing Enums ===

class AnchorRole(str, Enum):
    """Rôle sémantique d'un anchor dans le texte source."""

    DEFINITION = "definition"           # Définit le concept
    PROCEDURE = "procedure"             # Décrit un processus/méthode
    REQUIREMENT = "requirement"         # Obligation, exigence
    PROHIBITION = "prohibition"         # Interdiction
    CONSTRAINT = "constraint"           # Contrainte technique
    OBLIGATION = "obligation"           # Obligation légale/contractuelle
    EXAMPLE = "example"                 # Exemple illustratif
    REFERENCE = "reference"             # Référence/citation
    CONTEXT = "context"                 # Contexte général


class ConceptStability(str, Enum):
    """Niveau de stabilité d'un CanonicalConcept."""

    STABLE = "stable"           # ≥2 ProtoConcepts ou ≥2 sections
    SINGLETON = "singleton"     # 1 seul mais high-signal, needs_confirmation=true


class LocalMarker(BaseModel):
    """
    Marqueur local detecte dans un passage (version, edition, etc.).

    ADR: ADR_ASSERTION_AWARE_KG.md - Section 4.2
    """
    value: str = Field(..., description="Valeur du marqueur (ex: '1809', 'FPS03')")
    evidence: str = Field(default="", description="Quote textuelle contenant le marqueur")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Anchor(BaseModel):
    """
    Lien explicite entre un concept et un passage du texte source.

    Invariant d'Architecture: Un concept DOIT avoir au moins un anchor.
    Sans anchor = pas de concept (élimine le bruit et les hallucinations).

    Enrichi avec AnchorContext (PR2 - ADR_ASSERTION_AWARE_KG):
    - polarity: polarite de l'assertion
    - scope: scope de l'assertion (general, constrained)
    - local_markers: marqueurs detectes dans le passage
    - is_override: true si le passage override le contexte document
    - qualifier_source: source du qualificateur (explicit, inherited)
    """

    concept_id: str = Field(..., description="ID du concept (proto ou canonical)")
    chunk_id: str = Field(..., description="ID du chunk contenant la quote")
    quote: str = Field(..., description="Citation textuelle exacte du document")
    role: AnchorRole = Field(..., description="Rôle sémantique de l'anchor")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance dans l'anchor (score fuzzy matching)"
    )
    char_start: int = Field(..., ge=0, description="Position début dans le chunk")
    char_end: int = Field(..., gt=0, description="Position fin dans le chunk")
    approximate: bool = Field(
        default=False,
        description="True si fuzzy score < seuil exact mais > seuil minimum"
    )
    section_id: Optional[str] = Field(
        None,
        description="ID de la section du document (pour comptage multi-sections)"
    )
    # === PR2: Assertion Context Fields ===
    polarity: Polarity = Field(
        default=Polarity.UNKNOWN,
        description="Polarite de l'assertion (positive, negative, future, deprecated)"
    )
    scope: AssertionScope = Field(
        default=AssertionScope.UNKNOWN,
        description="Scope de l'assertion (general, constrained)"
    )
    local_markers: List[LocalMarker] = Field(
        default_factory=list,
        description="Marqueurs detectes localement dans le passage"
    )
    is_override: bool = Field(
        default=False,
        description="True si le passage override le contexte document"
    )
    qualifier_source: QualifierSource = Field(
        default=QualifierSource.NONE,
        description="Source du qualificateur (explicit, inherited_strong, inherited_weak)"
    )
    context_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confiance dans le contexte d'assertion"
    )


class AnchorPayload(BaseModel):
    """
    Payload minimal pour Qdrant (Invariant d'Architecture).

    SEULS ces champs sont autorisés dans anchored_concepts du payload Qdrant.
    Ne JAMAIS ajouter: definition, synthetic_text, full_context, embedding.
    """

    concept_id: str = Field(..., description="Référence vers Neo4j")
    label: str = Field(..., description="Nom du concept (affichage rapide)")
    role: str = Field(..., description="Rôle de l'anchor")
    span: List[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="[char_start, char_end] dans le chunk"
    )


class ProtoConceptContext(BaseModel):
    """
    Contexte agrege pour un ProtoConcept.

    Agrege les AnchorContext de tous les anchors d'un ProtoConcept.
    Detecte les conflits et calcule les valeurs consolidees.

    ADR: ADR_ASSERTION_AWARE_KG.md - Section 4.2
    """
    polarity: Polarity = Field(
        default=Polarity.UNKNOWN,
        description="Polarite consolidee"
    )
    scope: AssertionScope = Field(
        default=AssertionScope.UNKNOWN,
        description="Scope consolide"
    )
    markers: List[str] = Field(
        default_factory=list,
        description="Marqueurs agreges (top-K)"
    )
    qualifier_source: QualifierSource = Field(
        default=QualifierSource.NONE,
        description="Source du qualificateur"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confiance globale"
    )
    has_conflict: bool = Field(
        default=False,
        description="True si conflit detecte entre anchors"
    )
    conflict_flags: List[str] = Field(
        default_factory=list,
        description="Description des conflits"
    )


class ProtoConcept(BaseModel):
    """
    Concept document-level extrait par le LLM.

    Toujours conservé si anchor valide. Peut être promu en CanonicalConcept
    si répété ou high-signal.

    Enrichi avec ProtoConceptContext (PR2 - ADR_ASSERTION_AWARE_KG):
    - context: contexte agrege de tous les anchors
    """

    id: str = Field(..., description="ID unique du ProtoConcept (pc_xxx)")
    label: str = Field(..., description="Nom/label du concept")
    definition: str = Field(..., description="Définition courte extraite")
    type_heuristic: str = Field(
        default="abstract",
        description="Type heuristique (Pass 1): abstract, structural, procedural, regulatory"
    )
    document_id: str = Field(..., description="ID du document source")
    section_id: Optional[str] = Field(None, description="ID de la section")
    embedding: Optional[List[float]] = Field(
        None,
        description="Embedding du concept (label + quote principale)"
    )
    anchors: List[Anchor] = Field(
        default_factory=list,
        description="Anchors vers les passages sources"
    )
    tenant_id: str = Field(default="default")
    # === PR2: Aggregated Context ===
    context: Optional[ProtoConceptContext] = Field(
        None,
        description="Contexte agrege de tous les anchors (polarity, scope, markers)"
    )

    def has_valid_anchor(self) -> bool:
        """Vérifie qu'au moins un anchor est valide."""
        return len(self.anchors) > 0 and any(not a.approximate for a in self.anchors)

    def compute_context(self) -> ProtoConceptContext:
        """
        Calcule le contexte agrege depuis les anchors.

        Regles d'agregation (ADR Section 3.5):
        - Polarity: all positive -> positive, mixed -> conflict
        - Scope: any constrained with conf > 0.7 -> constrained
        - Markers: merge weighted by confidence, top-K
        """
        if not self.anchors:
            return ProtoConceptContext()

        # Agregation Polarity
        polarities = [a.polarity for a in self.anchors]
        unique_polarities = set(p for p in polarities if p != Polarity.UNKNOWN)

        conflict_flags = []
        if len(unique_polarities) == 0:
            polarity = Polarity.UNKNOWN
        elif len(unique_polarities) == 1:
            polarity = unique_polarities.pop()
        else:
            polarity = Polarity.POSITIVE  # Default
            conflict_flags.append(f"polarity_conflict: {[p.value for p in unique_polarities]}")

        # Agregation Scope
        constrained_high = any(
            a.scope == AssertionScope.CONSTRAINED and a.context_confidence > 0.7
            for a in self.anchors
        )
        general_any = any(
            a.scope == AssertionScope.GENERAL
            for a in self.anchors
        )

        if constrained_high:
            scope = AssertionScope.CONSTRAINED
        elif general_any and not constrained_high:
            scope = AssertionScope.GENERAL
        else:
            scope = AssertionScope.UNKNOWN

        # Agregation Markers
        marker_scores: Dict[str, float] = {}
        for a in self.anchors:
            for lm in a.local_markers:
                if lm.value not in marker_scores:
                    marker_scores[lm.value] = 0.0
                marker_scores[lm.value] += lm.confidence * a.context_confidence

        sorted_markers = sorted(
            marker_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        markers = [m[0] for m in sorted_markers[:3]]

        # Qualifier Source
        sources = [a.qualifier_source for a in self.anchors]
        if QualifierSource.EXPLICIT in sources:
            qualifier_source = QualifierSource.EXPLICIT
        elif QualifierSource.INHERITED_STRONG in sources:
            qualifier_source = QualifierSource.INHERITED_STRONG
        elif QualifierSource.INHERITED_WEAK in sources:
            qualifier_source = QualifierSource.INHERITED_WEAK
        else:
            qualifier_source = QualifierSource.NONE

        # Confidence moyenne
        confidence = sum(a.context_confidence for a in self.anchors) / len(self.anchors)

        return ProtoConceptContext(
            polarity=polarity,
            scope=scope,
            markers=markers,
            qualifier_source=qualifier_source,
            confidence=confidence,
            has_conflict=len(conflict_flags) > 0,
            conflict_flags=conflict_flags,
        )


class CanonicalConcept(BaseModel):
    """
    Concept corpus-level consolidé.

    Créé par promotion de ProtoConcepts similaires.
    Stabilité: "stable" (≥2 sources) ou "singleton" (1 mais high-signal).
    """

    id: str = Field(..., description="ID unique du CanonicalConcept (cc_xxx)")
    label: str = Field(..., description="Nom canonique du concept")
    definition_consolidated: Optional[str] = Field(
        None,
        description="Définition consolidée (Pass 2)"
    )
    type_fine: Optional[str] = Field(
        None,
        description="Type fin (Pass 2): regulatory_procedure, technical_component, etc."
    )
    stability: ConceptStability = Field(
        default=ConceptStability.STABLE,
        description="Niveau de stabilité"
    )
    needs_confirmation: bool = Field(
        default=False,
        description="True si singleton high-signal, nécessite validation humaine"
    )
    embedding: Optional[List[float]] = Field(
        None,
        description="Embedding (Pass 1: centroïde, Pass 2: synthèse LLM)"
    )
    proto_concept_ids: List[str] = Field(
        default_factory=list,
        description="IDs des ProtoConcepts fusionnés"
    )
    tenant_id: str = Field(default="default")

    @property
    def proto_count(self) -> int:
        """Nombre de ProtoConcepts fusionnés."""
        return len(self.proto_concept_ids)


class HighSignalCheck(BaseModel):
    """Résultat de vérification high-signal pour singleton."""

    is_high_signal: bool = Field(..., description="True si concept est high-signal")
    reasons: List[str] = Field(
        default_factory=list,
        description="Raisons du statut high-signal"
    )
    anchor_role_match: bool = Field(default=False)
    modal_match: bool = Field(default=False)
    section_match: bool = Field(default=False)
    domain_match: bool = Field(default=False)
