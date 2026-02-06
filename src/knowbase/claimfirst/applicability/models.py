# src/knowbase/claimfirst/applicability/models.py
"""
Modèles pour le module ApplicabilityFrame (Evidence-Locked).

Architecture à 4 couches:
  Layer A: EvidenceUnit (phrases atomiques, IDs stables)
  Layer B: CandidateProfile (markers + values + stats, 100% déterministe)
  Layer C: ApplicabilityFrame (LLM evidence-locked, le LLM ne voit que des IDs)
  Layer D: Validation pipeline

Le LLM ne peut référencer que des unit_ids pré-existants.
Si une valeur n'existe dans aucun candidat, elle ne peut pas apparaître en sortie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Layer A: EvidenceUnit
# ============================================================================

@dataclass
class EvidenceUnit:
    """
    Unité de texte atomique (phrase) avec ID stable.

    ID format: EU:{passage_reading_order}:{sentence_index}
    Déterministe et stable pour un même document.
    """

    unit_id: str
    """ID stable au format EU:{p_idx}:{s_idx}."""

    text: str
    """Texte verbatim de la phrase."""

    passage_idx: int
    """Index du passage parent (reading_order)."""

    sentence_idx: int
    """Index de la phrase dans le passage."""

    page_no: Optional[int] = None
    """Numéro de page hérité du passage parent."""

    section_title: Optional[str] = None
    """Titre de section hérité du passage parent."""

    def __len__(self) -> int:
        return len(self.text)


# ============================================================================
# Layer B: Markers & Value Candidates
# ============================================================================

class MarkerCategory(str, Enum):
    """Catégories de markers d'applicabilité (domain-agnostic)."""

    CONDITIONALITY = "conditionality"
    """if, only if, unless, except, provided that, subject to"""

    SCOPE = "scope"
    """applies to, in scope, limited to, for the purposes of"""

    TEMPORAL = "temporal"
    """effective as of, from, until, starting, supersedes"""

    DEFINITION = "definition"
    """means, shall mean, is defined as, refers to"""

    ENVIRONMENT = "environment"
    """when configured, prerequisite, requires, only for, available with"""

    REFERENCE = "reference"
    """based on, derived from, version, release, edition"""


@dataclass
class MarkerHit:
    """Cue word détecté dans une EvidenceUnit."""

    category: MarkerCategory
    """Catégorie du marker."""

    matched_text: str
    """Texte exact du match."""

    unit_id: str
    """ID de l'EvidenceUnit contenant le marker."""

    char_offset: int = 0
    """Offset dans le texte de l'unité."""


@dataclass
class ValueCandidate:
    """
    Valeur candidate extraite par scan déterministe.

    Chaque candidat porte ses statistiques de fréquence et de co-occurrence.
    """

    candidate_id: str
    """ID unique: VC:{value_type}:{raw_value_hash}."""

    raw_value: str
    """Valeur brute extraite."""

    value_type: str
    """Type: year, version, named_version, date."""

    unit_ids: List[str] = field(default_factory=list)
    """IDs des EvidenceUnits où la valeur a été trouvée."""

    frequency: int = 1
    """Nombre d'occurrences dans le document."""

    in_title: bool = False
    """Trouvée dans le titre du document."""

    in_header_zone: bool = False
    """Trouvée dans les 10% premiers du document."""

    cooccurs_with_subject: bool = False
    """Co-occurre avec le primary_subject."""

    nearby_markers: List[str] = field(default_factory=list)
    """Markers d'applicabilité à ≤200 chars de distance."""

    context_snippets: List[str] = field(default_factory=list)
    """Max 3 extraits de contexte autour de la valeur (±50 chars)."""


@dataclass
class CandidateProfile:
    """
    Profil complet de candidats pour un document.

    Contient tous les markers et value candidates extraits par scan
    déterministe exhaustif (0 appel LLM).
    """

    doc_id: str
    """ID du document analysé."""

    title: Optional[str] = None
    """Titre du document."""

    primary_subject: Optional[str] = None
    """Sujet principal du document."""

    total_units: int = 0
    """Nombre total d'EvidenceUnits."""

    total_chars: int = 0
    """Nombre total de caractères analysés."""

    markers: List[MarkerHit] = field(default_factory=list)
    """Tous les markers détectés."""

    value_candidates: List[ValueCandidate] = field(default_factory=list)
    """Toutes les valeurs candidates."""

    markers_by_category: Dict[str, int] = field(default_factory=dict)
    """Compteurs de markers par catégorie."""

    def get_candidates_by_type(self, value_type: str) -> List[ValueCandidate]:
        """Retourne les candidats d'un type donné."""
        return [vc for vc in self.value_candidates if vc.value_type == value_type]


# ============================================================================
# Layer C: ApplicabilityFrame
# ============================================================================

class FrameFieldConfidence(str, Enum):
    """Niveau de confiance pour un champ du frame."""

    HIGH = "high"
    """Evidence forte et concordante."""

    MEDIUM = "medium"
    """Evidence partielle mais cohérente."""

    LOW = "low"
    """Evidence faible ou ambiguë."""

    ABSENT = "absent"
    """Aucune evidence trouvée."""


class FrameField(BaseModel):
    """
    Champ résolu de l'ApplicabilityFrame.

    Chaque champ est verrouillé sur des evidence_unit_ids existants.
    La valeur normalisée doit exister dans les candidats.
    """

    field_name: str = Field(
        ...,
        description="Nom du champ (release_id, year, edition, effective_date...)"
    )

    value_normalized: str = Field(
        ...,
        description="Valeur normalisée (doit exister dans un ValueCandidate)"
    )

    display_label: Optional[str] = Field(
        default=None,
        description="Label d'affichage trouvé dans le corpus (version, release...)"
    )

    evidence_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs des EvidenceUnits sources (DOIVENT exister)"
    )

    candidate_ids: List[str] = Field(
        default_factory=list,
        description="IDs des ValueCandidates qui supportent cette valeur"
    )

    confidence: FrameFieldConfidence = Field(
        default=FrameFieldConfidence.MEDIUM,
        description="Niveau de confiance"
    )

    reasoning: Optional[str] = Field(
        default=None,
        description="Raisonnement du LLM ou de l'heuristique"
    )


class ApplicabilityFrame(BaseModel):
    """
    Frame d'applicabilité complet d'un document.

    Le frame est evidence-locked: chaque champ référence des
    EvidenceUnits et ValueCandidates pré-existants.
    Le LLM ne peut pas inventer de valeurs.

    Sortie de Layer C, validé par Layer D.
    """

    doc_id: str = Field(
        ...,
        description="ID du document"
    )

    fields: List[FrameField] = Field(
        default_factory=list,
        description="Champs résolus avec evidence"
    )

    unknowns: List[str] = Field(
        default_factory=list,
        description="Champs indéterminables (listés par le LLM ou l'heuristique)"
    )

    method: str = Field(
        default="llm_evidence_locked",
        description="Méthode: llm_evidence_locked | deterministic_fallback"
    )

    validation_notes: List[str] = Field(
        default_factory=list,
        description="Notes de la pipeline de validation (Layer D)"
    )

    def get_field(self, field_name: str) -> Optional[FrameField]:
        """Retourne un champ par son nom."""
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None

    def get_field_value(self, field_name: str) -> Optional[str]:
        """Retourne la valeur normalisée d'un champ."""
        f = self.get_field(field_name)
        return f.value_normalized if f else None

    def to_json_dict(self) -> dict:
        """Sérialise le frame en dict JSON-safe pour stockage Neo4j."""
        return {
            "doc_id": self.doc_id,
            "fields": [
                {
                    "field_name": f.field_name,
                    "value_normalized": f.value_normalized,
                    "display_label": f.display_label,
                    "evidence_unit_ids": f.evidence_unit_ids,
                    "candidate_ids": f.candidate_ids,
                    "confidence": f.confidence.value,
                    "reasoning": f.reasoning,
                }
                for f in self.fields
            ],
            "unknowns": self.unknowns,
            "method": self.method,
            "validation_notes": self.validation_notes,
        }


__all__ = [
    "EvidenceUnit",
    "MarkerCategory",
    "MarkerHit",
    "ValueCandidate",
    "CandidateProfile",
    "FrameFieldConfidence",
    "FrameField",
    "ApplicabilityFrame",
]
