"""
Modèles Pydantic pour le Concept Assembly Engine (Couche 4 OSMOSE).

Définit les structures de données pour les evidence packs :
- EvidenceUnit : atome de preuve normalisé (claim ou chunk)
- EvidencePack : paquet structuré avec timeline, conflits, qualité
- ResolvedConcept : concept résolu depuis le KG
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ScopeSignature(BaseModel):
    """Signature de portée d'une preuve — permet de détecter les mélanges de scope."""

    doc_type: Optional[str] = Field(
        default=None, description="Type de document source (regulation, annual_report, etc.)"
    )
    axis_values: Dict[str, str] = Field(
        default_factory=dict, description="Axes d'applicabilité (release_id, version, etc.)"
    )
    generality_level: str = Field(
        default="universal",
        description="Niveau de généralité : universal | regional | local",
    )
    geographic_scope: Optional[str] = Field(
        default=None, description="Portée géographique (EU, Global, etc.)"
    )
    source_granularity: str = Field(
        default="policy",
        description="Granularité : policy | example | exception | implementation_note",
    )
    temporal_scope_kind: str = Field(
        default="timeless",
        description="Nature temporelle : timeless | versioned | point_in_time",
    )


class EvidenceUnit(BaseModel):
    """Atome de preuve normalisé — 1 claim ou 1 chunk = 1 unit."""

    unit_id: str = Field(..., description="Identifiant unique (eu_{uuid4_short})")
    source_type: str = Field(..., description="claim | chunk")
    source_id: str = Field(..., description="claim_id ou chunk_id d'origine")
    text: str = Field(..., description="Contenu textuel")
    doc_id: str = Field(..., description="Document source")
    doc_title: str = Field(default="", description="Titre du document source")
    rhetorical_role: str = Field(
        ...,
        description="Rôle rhétorique : definition | rule | mention | exception | context",
    )
    claim_type: Optional[str] = Field(
        default=None, description="Type de claim (DEFINITIONAL, PRESCRIPTIVE, etc.)"
    )
    scope_signature: ScopeSignature = Field(default_factory=ScopeSignature)
    weight: float = Field(default=1.0, description="Poids dans le pack (après plafonnement)")
    facet_domains: List[str] = Field(default_factory=list)
    diagnostic_flags: List[str] = Field(
        default_factory=list,
        description="Flags de diagnostic (dominant_doc, low_definitionality, etc.)",
    )
    chunk_context: Optional[str] = Field(
        default=None,
        description="Contexte verbatim long du chunk source (paragraphe complet)",
    )
    chunk_id: Optional[str] = Field(
        default=None,
        description="ID du chunk source dans Qdrant (via pont claim↔chunk)",
    )


class TemporalStep(BaseModel):
    """Pas temporel dans l'évolution d'un concept."""

    axis_value: str = Field(..., description="Valeur d'axe (2022, 2023, etc.)")
    change_type: str = Field(
        ..., description="ADDED | REMOVED | MODIFIED | UNCHANGED"
    )
    unit_ids: List[str] = Field(default_factory=list)


class TemporalEvolution(BaseModel):
    """Évolution temporelle d'un concept le long d'un axe."""

    axis_name: str = Field(..., description="Nom de l'axe (release_id, version, etc.)")
    timeline: List[TemporalStep] = Field(default_factory=list)


class ConfirmedConflict(BaseModel):
    """Conflit confirmé entre deux evidence units (verdict formel INCOMPATIBLE)."""

    unit_id_a: str
    unit_id_b: str
    conflict_type: str = Field(default="INCOMPATIBLE")
    description: str = Field(default="")


class CandidateTension(BaseModel):
    """Tension candidate nécessitant arbitrage LLM ou humain."""

    unit_id_a: str
    unit_id_b: str
    tension_type: str = Field(default="NEED_LLM")
    description: str = Field(default="")


class RelatedConcept(BaseModel):
    """Concept lié par co-occurrence dans les mêmes claims."""

    entity_name: str
    entity_type: str
    co_occurrence_count: int = Field(default=0)
    supporting_unit_ids: List[str] = Field(default_factory=list)


class SourceEntry(BaseModel):
    """Entrée dans l'index des sources d'un evidence pack."""

    doc_id: str
    doc_title: str
    unit_count: int = Field(default=0)
    doc_type: Optional[str] = Field(default=None)
    contribution_pct: float = Field(default=0.0)


class QualitySignals(BaseModel):
    """Signaux de qualité de l'evidence pack — 2 scores distincts."""

    total_units: int = Field(default=0)
    claim_units: int = Field(default=0)
    chunk_units: int = Field(default=0)
    doc_count: int = Field(default=0)
    type_diversity: int = Field(default=0, description="Nb de rhetorical_roles distincts")
    has_definition: bool = Field(default=False)
    has_temporal_data: bool = Field(default=False)
    confirmed_conflict_count: int = Field(default=0)
    candidate_tension_count: int = Field(default=0)
    coverage_score: float = Field(
        default=0.0, description="0-1, richesse du pack"
    )
    coherence_risk_score: float = Field(
        default=0.0, description="0-1, risque (haut = mauvais)"
    )
    scope_diversity_score: float = Field(
        default=0.0, description="0-1, diversité des scope_signatures"
    )
    coherence_risk_factors: List[str] = Field(
        default_factory=list,
        description="Facteurs de risque (doc_dominance, low_type_diversity, etc.)",
    )


class ResolvedConcept(BaseModel):
    """Concept résolu depuis le Knowledge Graph."""

    canonical_name: str = Field(..., description="Nom canonique de l'entité")
    entity_type: str = Field(..., description="Type d'entité (concept, actor, legal_term, etc.)")
    entity_ids: List[str] = Field(
        default_factory=list,
        description="IDs Neo4j des entités regroupées",
    )
    aliases: List[str] = Field(default_factory=list)
    claim_count: int = Field(default=0)
    doc_ids: List[str] = Field(default_factory=list)
    facet_domains: List[str] = Field(default_factory=list)
    resolution_method: str = Field(
        default="exact",
        description="Méthode de résolution : exact | alias | fuzzy",
    )
    resolution_confidence: float = Field(
        default=1.0, description="Confiance de résolution (0-1)"
    )
    ambiguity_notes: List[str] = Field(default_factory=list)


class EvidencePack(BaseModel):
    """Paquet de preuves structuré pour un concept — sortie principale de la Couche 4."""

    concept: ResolvedConcept
    units: List[EvidenceUnit] = Field(default_factory=list)
    temporal_evolution: Optional[TemporalEvolution] = Field(default=None)
    confirmed_conflicts: List[ConfirmedConflict] = Field(default_factory=list)
    candidate_tensions: List[CandidateTension] = Field(default_factory=list)
    related_concepts: List[RelatedConcept] = Field(default_factory=list)
    source_index: List[SourceEntry] = Field(default_factory=list)
    quality_signals: QualitySignals = Field(default_factory=QualitySignals)
    generated_at: str = Field(default="", description="ISO datetime de génération")


# ─── Phase 2 : Article Generation ──────────────────────────────────────


class PlannedSection(BaseModel):
    """Section planifiée par le SectionPlanner — guide la génération."""

    section_type: str = Field(..., description="overview, definition, key_properties, etc.")
    title: str = Field(..., description="Titre français de la section")
    unit_ids: List[str] = Field(default_factory=list, description="EvidenceUnit IDs assignés")
    generation_instructions: str = Field(default="", description="Instructions pour le LLM")
    is_deterministic: bool = Field(
        default=False, description="True → pas de LLM (ex: sources)"
    )


class ArticlePlan(BaseModel):
    """Plan d'article produit par le SectionPlanner."""

    concept_name: str
    slug: str
    sections: List[PlannedSection] = Field(default_factory=list)
    total_units_assigned: int = Field(default=0)
    unassigned_unit_ids: List[str] = Field(default_factory=list)


class GeneratedSection(BaseModel):
    """Section générée par le ConstrainedGenerator."""

    section_type: str
    title: str
    content: str = Field(default="", description="Markdown avec [citations]")
    citations_used: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    gaps: List[str] = Field(default_factory=list)


class GeneratedArticle(BaseModel):
    """Article complet généré — sortie finale de la Phase 2."""

    concept_name: str
    plan: ArticlePlan
    sections: List[GeneratedSection] = Field(default_factory=list)
    generated_at: str = Field(default="")
    total_citations: int = Field(default=0)
    average_confidence: float = Field(default=0.0)
    all_gaps: List[str] = Field(default_factory=list)
