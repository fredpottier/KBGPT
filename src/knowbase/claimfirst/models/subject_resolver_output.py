# src/knowbase/claimfirst/models/subject_resolver_output.py
"""
Modèles de sortie pour SubjectResolver v2.

INV-25: Domain-agnostic - pas de vocabulaire IT/SAP hardcodé.

Ce module définit les structures de sortie du prompt contractuel v2
qui classifie les candidats en:
- COMPARABLE_SUBJECT: sujet stable comparable
- AXIS_VALUE: valeur discriminante (avec rôle, pas label)
- DOC_TYPE: type/genre documentaire
- NOISE: bruit à ignorer
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DiscriminatingRole(str, Enum):
    """
    Rôle discriminant d'une valeur d'axe.

    INV-25: Décrit le RÔLE, pas un label domain-specific.
    Permet de rester agnostique domaine tout en capturant
    la fonction de la valeur.
    """

    TEMPORAL = "temporal"
    """Discrimine dans le temps (année, date, version date-based)."""

    GEOGRAPHIC = "geographic"
    """Discrimine par zone géographique (région, pays, juridiction)."""

    REVISION = "revision"
    """Discrimine par révision/édition (numéro de version, édition)."""

    APPLICABILITY_SCOPE = "applicability_scope"
    """Discrimine par périmètre d'application (Enterprise, Cloud, etc.)."""

    STATUS = "status"
    """Discrimine par statut (draft, final, deprecated)."""

    UNKNOWN = "unknown"
    """Rôle discriminant non identifiable."""


class CandidateClass(str, Enum):
    """Classification d'un candidat extrait."""

    COMPARABLE_SUBJECT = "COMPARABLE_SUBJECT"
    """Sujet stable comparable entre documents."""

    AXIS_VALUE = "AXIS_VALUE"
    """Valeur d'axe discriminante."""

    DOC_TYPE = "DOC_TYPE"
    """Type/genre documentaire."""

    NOISE = "NOISE"
    """Bruit à ignorer."""


class EvidenceSource(str, Enum):
    """Source de l'évidence."""

    TITLE = "title"
    FILENAME = "filename"
    HEADER = "header"
    COVER = "cover"
    GLOBAL_VIEW = "global_view"


class EvidenceSpanOutput(BaseModel):
    """Span d'évidence pour une décision."""

    source: EvidenceSource = Field(
        ...,
        description="Source de l'évidence"
    )

    quote: str = Field(
        ...,
        description="Citation textuelle de l'évidence"
    )


class SupportEvidence(BaseModel):
    """Évidence de support pour une décision."""

    signals: List[str] = Field(
        default_factory=list,
        description="Signaux utilisés pour la décision"
    )

    evidence_spans: List[EvidenceSpanOutput] = Field(
        default_factory=list,
        description="Spans d'évidence"
    )


class ComparableSubjectOutput(BaseModel):
    """Sortie pour le sujet comparable identifié."""

    label: str = Field(
        ...,
        description="Nom du sujet stable"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance [0-1]"
    )

    rationale: str = Field(
        ...,
        max_length=240,
        description="Justification courte"
    )

    support: SupportEvidence = Field(
        default_factory=SupportEvidence,
        description="Évidence de support"
    )


class AxisValueOutput(BaseModel):
    """Sortie pour une valeur d'axe identifiée."""

    value_raw: str = Field(
        ...,
        description="Valeur brute extraite"
    )

    discriminating_role: DiscriminatingRole = Field(
        ...,
        description="Rôle discriminant (temporal, geographic, revision, etc.)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance [0-1]"
    )

    rationale: str = Field(
        ...,
        max_length=240,
        description="Justification courte"
    )

    support: SupportEvidence = Field(
        default_factory=SupportEvidence,
        description="Évidence de support"
    )


class DocTypeOutput(BaseModel):
    """Sortie pour le type documentaire identifié."""

    label: str = Field(
        ...,
        description="Type/genre du document"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance [0-1]"
    )

    rationale: str = Field(
        ...,
        max_length=240,
        description="Justification courte"
    )

    support: SupportEvidence = Field(
        default_factory=SupportEvidence,
        description="Évidence de support"
    )


class ClassifiedCandidate(BaseModel):
    """Classification d'un candidat individuel."""

    candidate: str = Field(
        ...,
        description="Candidat original"
    )

    classification: CandidateClass = Field(
        ...,
        alias="class",
        description="Classe assignée"
    )

    mapped_to: str = Field(
        ...,
        description="Référence vers l'output (comparable_subject, axis_values[i], doc_type, none)"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score de confiance"
    )

    reason: str = Field(
        ...,
        max_length=160,
        description="Raison courte"
    )

    class Config:
        populate_by_name = True


class AbstainInfo(BaseModel):
    """Information d'abstention."""

    must_abstain: bool = Field(
        default=False,
        description="Si le resolver doit s'abstenir"
    )

    reason: str = Field(
        default="",
        description="Raison de l'abstention"
    )


class SubjectResolverOutput(BaseModel):
    """
    Sortie complète du SubjectResolver v2.

    Invariants:
    - Exactement 1 comparable_subject OU abstain.must_abstain=True
    - axis_values peut être vide
    - doc_type.label peut être "unknown"
    - Tous les candidats doivent apparaître dans classified_candidates
    """

    resolver_version: str = Field(
        default="subject_resolver_v2.0",
        description="Version du resolver"
    )

    comparable_subject: Optional[ComparableSubjectOutput] = Field(
        default=None,
        description="Sujet comparable identifié"
    )

    axis_values: List[AxisValueOutput] = Field(
        default_factory=list,
        description="Valeurs d'axes identifiées"
    )

    doc_type: Optional[DocTypeOutput] = Field(
        default=None,
        description="Type documentaire identifié"
    )

    classified_candidates: List[ClassifiedCandidate] = Field(
        default_factory=list,
        description="Classification de tous les candidats"
    )

    abstain: AbstainInfo = Field(
        default_factory=AbstainInfo,
        description="Information d'abstention"
    )

    def is_valid(self) -> bool:
        """
        Vérifie si la sortie respecte les invariants.

        Returns:
            True si valide
        """
        # Soit un comparable_subject, soit abstention
        if self.comparable_subject is None and not self.abstain.must_abstain:
            return False

        if self.comparable_subject is not None and self.abstain.must_abstain:
            return False

        # Confiance minimum pour comparable_subject
        if self.comparable_subject and self.comparable_subject.confidence < 0.70:
            return False

        return True

    def get_axis_by_role(self, role: DiscriminatingRole) -> Optional[AxisValueOutput]:
        """
        Récupère une valeur d'axe par son rôle.

        Args:
            role: Rôle discriminant recherché

        Returns:
            AxisValueOutput ou None
        """
        for axis in self.axis_values:
            if axis.discriminating_role == role:
                return axis
        return None

    @classmethod
    def create_abstain(cls, reason: str) -> "SubjectResolverOutput":
        """
        Factory pour créer une sortie d'abstention.

        Args:
            reason: Raison de l'abstention

        Returns:
            SubjectResolverOutput avec abstention
        """
        return cls(
            abstain=AbstainInfo(must_abstain=True, reason=reason)
        )


__all__ = [
    "DiscriminatingRole",
    "CandidateClass",
    "EvidenceSource",
    "EvidenceSpanOutput",
    "SupportEvidence",
    "ComparableSubjectOutput",
    "AxisValueOutput",
    "DocTypeOutput",
    "ClassifiedCandidate",
    "AbstainInfo",
    "SubjectResolverOutput",
]
