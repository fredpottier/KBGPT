# src/knowbase/claimfirst/models/document_context.py
"""
Modèle DocumentContext - Contexte d'applicabilité d'un document.

INV-8: Applicability over Truth (Scope Épistémique)

Principe fondamental: Une claim n'est jamais vraie "dans l'absolu".
Elle est vraie sous un ensemble de CONDITIONS D'APPLICABILITÉ
héritées du document.

Règles:
1. Le scope appartient au Document, pas à la Claim
   - DocumentContext porte les sujets et qualificateurs d'applicabilité
   - Les claims héritent par relation, sans universaliser
   - ⚠️ CORRECTIF 1: Claim.scope SUPPRIMÉ en V1 (pas de double source)

2. Une Claim affirme "ceci est DIT dans ce document"
   - PAS "ceci est VRAI pour ce produit en général"
   - Le contexte est un cadre de lecture, pas une vérité positive

3. Vocabulaire distinct: Facet ≠ ApplicabilityQualifier
   - Facet (HAS_FACET) = axe de navigation thématique
   - ApplicabilityQualifier = discriminant de scope

4. À la requête, on cherche des claims APPLICABLES dans un contexte
   - Pas des vérités globales
   - Si contexte ambigu: exposer les différentes claims avec leurs sources

5. Schéma Neo4j canonique UNIQUE:
   (Document)-[:HAS_CONTEXT]->(DocumentContext)-[:ABOUT_SUBJECT]->(SubjectAnchor)
   (Document)<-[:FROM]-(Passage)<-[:SUPPORTED_BY]-(Claim)
   (Claim)-[:IN_DOCUMENT]->(Document)  # Shortcut unique autorisé
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ResolutionStatus(str, Enum):
    """Statut de résolution du sujet."""

    RESOLVED = "resolved"
    """Match exact ou fort (confiance 1.0)."""

    LOW_CONFIDENCE = "low_confidence"
    """Soft match embedding avec delta suffisant (confiance 0.85-0.95)."""

    AMBIGUOUS = "ambiguous"
    """Plusieurs candidats possibles, delta insuffisant."""

    UNRESOLVED = "unresolved"
    """Aucun match, nouveau sujet créé ou rejeté."""


class DocumentContext(BaseModel):
    """
    Contexte d'applicabilité d'un document.

    INV-8: Le scope appartient au Document, pas à la Claim.
    Les claims héritent de ce contexte par relation, sans universaliser.

    Attributes:
        doc_id: Identifiant du document
        tenant_id: Tenant multi-locataire
        raw_subjects: Sujets bruts extraits du document
        subject_ids: Sujets résolus vers SubjectAnchor
        resolution_status: Statut de résolution
        resolution_confidence: Score de confiance [0-1]
        qualifiers: Qualificateurs validés pour ce document
        qualifier_candidates: Qualificateurs découverts non validés
        document_type: Type de document
        temporal_scope: Portée temporelle
        extraction_method: Méthode d'extraction utilisée
    """

    doc_id: str = Field(
        ...,
        description="Identifiant du document"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    # Sujet principal du document (INV-8: identification claire)
    primary_subject: Optional[str] = Field(
        default=None,
        description="Sujet principal traité par ce document (produit, règlement, norme, service...)"
    )

    # Sujets secondaires extraits du document
    raw_subjects: List[str] = Field(
        default_factory=list,
        description="Sujets/topics secondaires extraits du document"
    )

    # Sujets résolus vers SubjectAnchor
    subject_ids: List[str] = Field(
        default_factory=list,
        description="IDs des SubjectAnchor résolus"
    )

    resolution_status: ResolutionStatus = Field(
        default=ResolutionStatus.UNRESOLVED,
        description="Statut de résolution des sujets"
    )

    resolution_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score de confiance de la résolution [0-1]"
    )

    # PATCH F: Qualificateurs d'applicabilité pour CE document (INV-10)
    # Séparation validated (utiliser) vs candidates (proposer)
    qualifiers: Dict[str, str] = Field(
        default_factory=dict,
        description="Qualificateurs validés pour ce doc: {version: '2021', region: 'EU'}"
    )

    qualifier_candidates: Dict[str, str] = Field(
        default_factory=dict,
        description="Qualificateurs candidats découverts, pas encore validés"
    )

    # Métadonnées document
    document_type: Optional[str] = Field(
        default=None,
        description="Type de document: 'Operations Guide', 'Security Guide'..."
    )

    temporal_scope: Optional[str] = Field(
        default=None,
        description="Portée temporelle: 'as of 2021', 'Q1 2024'..."
    )

    # Source de l'extraction
    extraction_method: str = Field(
        default="llm",
        description="Méthode d'extraction: 'llm' | 'metadata' | 'manual'"
    )

    # Applicability Axis (INV-25, INV-26)
    # Note: Dict values sont sérialisés, pas AxisValue directement pour éviter import circulaire
    axis_values: Dict[str, Dict] = Field(
        default_factory=dict,
        description="Valeurs d'axes pour ce document: {axis_key: AxisValue.to_neo4j_properties()}"
    )

    applicable_axes: List[str] = Field(
        default_factory=list,
        description="Liste des axis_keys applicables à ce document"
    )

    # Métadonnées
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de dernière mise à jour"
    )

    @property
    def is_resolved(self) -> bool:
        """Vérifie si au moins un sujet est résolu."""
        return (
            self.resolution_status == ResolutionStatus.RESOLVED
            and len(self.subject_ids) > 0
        )

    @property
    def has_subjects(self) -> bool:
        """Vérifie si des sujets ont été identifiés."""
        return len(self.subject_ids) > 0 or len(self.raw_subjects) > 0

    @property
    def qualifier_keys(self) -> List[str]:
        """Liste des clés de qualificateurs validés."""
        return list(self.qualifiers.keys())

    def add_subject(
        self,
        subject_id: str,
        status: ResolutionStatus,
        confidence: float,
    ) -> None:
        """
        Ajoute un sujet résolu.

        Args:
            subject_id: ID du SubjectAnchor
            status: Statut de résolution
            confidence: Score de confiance
        """
        if subject_id not in self.subject_ids:
            self.subject_ids.append(subject_id)

        # Mettre à jour le statut global (prendre le plus fort)
        status_priority = {
            ResolutionStatus.RESOLVED: 4,
            ResolutionStatus.LOW_CONFIDENCE: 3,
            ResolutionStatus.AMBIGUOUS: 2,
            ResolutionStatus.UNRESOLVED: 1,
        }
        if status_priority.get(status, 0) > status_priority.get(self.resolution_status, 0):
            self.resolution_status = status

        # Mettre à jour la confiance (moyenne pondérée)
        if self.resolution_confidence > 0:
            self.resolution_confidence = (self.resolution_confidence + confidence) / 2
        else:
            self.resolution_confidence = confidence

    def set_qualifier(self, key: str, value: str, validated: bool = True) -> None:
        """
        Définit un qualificateur pour ce document.

        INV-10: Les qualificateurs sont découverts du corpus.
        Un qualificateur est validé si sa clé est dans qualifiers_validated
        du SubjectAnchor associé.

        Args:
            key: Clé du qualificateur (ex: 'version')
            value: Valeur (ex: '2021')
            validated: Si True, ajoute aux qualifiers, sinon aux candidates
        """
        if validated:
            self.qualifiers[key] = value
            # Retirer des candidates si présent
            self.qualifier_candidates.pop(key, None)
        else:
            if key not in self.qualifiers:  # Ne pas écraser un validated
                self.qualifier_candidates[key] = value

    def get_scope_description(self) -> str:
        """
        Génère une description lisible du scope.

        Utilisé pour afficher le contexte à l'utilisateur.

        Returns:
            Description du scope
        """
        parts = []

        # Ajouter le sujet principal en premier
        if self.primary_subject:
            parts.append(self.primary_subject)

        # Ajouter les sujets secondaires (premiers 2 max)
        for raw in self.raw_subjects[:2]:
            if raw != self.primary_subject:  # Éviter doublon
                parts.append(raw)

        # Ajouter les qualificateurs validés
        for key, value in sorted(self.qualifiers.items()):
            parts.append(f"{value}")

        # Ajouter le type de document si présent
        if self.document_type:
            parts.append(f"({self.document_type})")

        return " - ".join(parts) if parts else f"Document {self.doc_id}"

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "doc_id": self.doc_id,
            "tenant_id": self.tenant_id,
            "primary_subject": self.primary_subject,
            "raw_subjects": self.raw_subjects if self.raw_subjects else None,
            "subject_ids": self.subject_ids if self.subject_ids else None,
            "resolution_status": self.resolution_status.value,
            "resolution_confidence": self.resolution_confidence,
            "qualifiers": self.qualifiers if self.qualifiers else None,
            "qualifier_candidates": self.qualifier_candidates if self.qualifier_candidates else None,
            "document_type": self.document_type,
            "temporal_scope": self.temporal_scope,
            "extraction_method": self.extraction_method,
            # Applicability Axis (INV-25, INV-26)
            "axis_values": self.axis_values if self.axis_values else None,
            "applicable_axes": self.applicable_axes if self.applicable_axes else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "DocumentContext":
        """Construit un DocumentContext depuis un record Neo4j."""
        return cls(
            doc_id=record["doc_id"],
            tenant_id=record["tenant_id"],
            primary_subject=record.get("primary_subject"),
            raw_subjects=record.get("raw_subjects") or [],
            subject_ids=record.get("subject_ids") or [],
            resolution_status=ResolutionStatus(record.get("resolution_status", "unresolved")),
            resolution_confidence=record.get("resolution_confidence", 0.0),
            qualifiers=record.get("qualifiers") or {},
            qualifier_candidates=record.get("qualifier_candidates") or {},
            document_type=record.get("document_type"),
            temporal_scope=record.get("temporal_scope"),
            extraction_method=record.get("extraction_method", "llm"),
            # Applicability Axis (INV-25, INV-26)
            axis_values=record.get("axis_values") or {},
            applicable_axes=record.get("applicable_axes") or [],
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
        )

    @classmethod
    def create_for_document(
        cls,
        doc_id: str,
        tenant_id: str,
        raw_subjects: Optional[List[str]] = None,
        document_type: Optional[str] = None,
    ) -> "DocumentContext":
        """
        Factory pour créer un nouveau DocumentContext.

        Args:
            doc_id: ID du document
            tenant_id: Tenant ID
            raw_subjects: Sujets bruts (optionnel)
            document_type: Type de document (optionnel)

        Returns:
            Nouveau DocumentContext
        """
        return cls(
            doc_id=doc_id,
            tenant_id=tenant_id,
            raw_subjects=raw_subjects or [],
            document_type=document_type,
        )


# Bootstrap qualificateurs (INV-10: mini-set pour accélérer, PAS universel)
# Ces patterns NE DOIVENT PAS imposer le schéma SAP/IT à des docs non-SAP
BOOTSTRAP_QUALIFIERS = {
    "version": re.compile(
        r"(?:version|release|v\.?)\s*(\d+(?:\.\d+)*|\d{4})",
        re.IGNORECASE
    ),
    "region": re.compile(
        r"(?:for|in)\s+(EU|US|APAC|China|global)",
        re.IGNORECASE
    ),
    "edition": re.compile(
        r"(Enterprise|Standard|Professional|Private|Public)\s+(?:Edition|Cloud)",
        re.IGNORECASE
    ),
    "year": re.compile(
        r"\b(20\d{2})\b"
    ),
}


def extract_bootstrap_qualifiers(text: str) -> Dict[str, str]:
    """
    Extrait les qualificateurs bootstrap depuis un texte.

    INV-10: Ces patterns sont un kickstart, pas un schéma universel.
    Les nouveaux domaines découvrent leurs propres qualificateurs.

    Args:
        text: Texte à analyser

    Returns:
        Dict des qualificateurs trouvés
    """
    found = {}

    for key, pattern in BOOTSTRAP_QUALIFIERS.items():
        match = pattern.search(text)
        if match:
            found[key] = match.group(1)

    return found


__all__ = [
    "DocumentContext",
    "ResolutionStatus",
    "BOOTSTRAP_QUALIFIERS",
    "extract_bootstrap_qualifiers",
]
