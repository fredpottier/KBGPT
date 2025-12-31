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

from enum import Enum


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


class Anchor(BaseModel):
    """
    Lien explicite entre un concept et un passage du texte source.

    Invariant d'Architecture: Un concept DOIT avoir au moins un anchor.
    Sans anchor = pas de concept (élimine le bruit et les hallucinations).
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


class ProtoConcept(BaseModel):
    """
    Concept document-level extrait par le LLM.

    Toujours conservé si anchor valide. Peut être promu en CanonicalConcept
    si répété ou high-signal.
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

    def has_valid_anchor(self) -> bool:
        """Vérifie qu'au moins un anchor est valide."""
        return len(self.anchors) > 0 and any(not a.approximate for a in self.anchors)


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
