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
