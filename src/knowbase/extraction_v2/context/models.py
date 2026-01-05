"""
Modeles de donnees pour DocContext extraction.

Ces modeles definissent:
- DocScope: classification du document (GENERAL, VARIANT_SPECIFIC, MIXED)
- MarkerEvidence: marqueur avec evidence et source
- ScopeSignals: signaux de scoring pour la classification
- DocContextFrame: frame complet stocke sur le document
- DocScopeAnalysis: sortie LLM pour validation

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 4
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class DocScope(str, Enum):
    """
    Classification du scope documentaire.

    - GENERAL: pas de marqueur dominant, contenu applicable largement
    - VARIANT_SPECIFIC: marqueur dominant existe (version, edition, etc.)
    - MIXED: plusieurs variantes comparees/contrastees
    """
    GENERAL = "GENERAL"
    VARIANT_SPECIFIC = "VARIANT_SPECIFIC"
    MIXED = "MIXED"


@dataclass
class MarkerEvidence:
    """
    Un marqueur de contexte avec son evidence.

    Attributes:
        value: Valeur du marqueur (ex: "1809", "2025", "FPS03")
        evidence: Quote textuelle justifiant le marqueur
        source: Origine du marqueur (cover, header, filename, revision, title, low_conf)
        confidence: Score de confiance [0.0, 1.0]
    """
    value: str
    evidence: str
    source: str  # cover, header, filename, revision, title, body, low_conf
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire."""
        return {
            "value": self.value,
            "evidence": self.evidence,
            "source": self.source,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarkerEvidence":
        """Deserialise depuis un dictionnaire."""
        return cls(
            value=data["value"],
            evidence=data.get("evidence", ""),
            source=data.get("source", "unknown"),
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class ScopeSignals:
    """
    Signaux de scoring pour la classification DocScope.

    Ces signaux sont calcules par le candidate mining et valides par le LLM.

    Attributes:
        marker_position_score: Position des marqueurs (cover > header > body)
        marker_repeat_score: Repetition des marqueurs dans le document
        scope_language_score: Presence de langage scope (applies to, version, etc.)
        marker_diversity_score: Diversite des marqueurs (high = MIXED probable)
        conflict_score: Conflits detectes (comparaisons, "vs", "unlike")
    """
    marker_position_score: float = 0.0
    marker_repeat_score: float = 0.0
    scope_language_score: float = 0.0
    marker_diversity_score: float = 0.0
    conflict_score: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        """Serialise en dictionnaire."""
        return {
            "marker_position_score": self.marker_position_score,
            "marker_repeat_score": self.marker_repeat_score,
            "scope_language_score": self.scope_language_score,
            "marker_diversity_score": self.marker_diversity_score,
            "conflict_score": self.conflict_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScopeSignals":
        """Deserialise depuis un dictionnaire."""
        return cls(
            marker_position_score=data.get("marker_position_score", 0.0),
            marker_repeat_score=data.get("marker_repeat_score", 0.0),
            scope_language_score=data.get("scope_language_score", 0.0),
            marker_diversity_score=data.get("marker_diversity_score", 0.0),
            conflict_score=data.get("conflict_score", 0.0),
        )

    def compute_variant_score(self) -> float:
        """
        Calcule un score global pour VARIANT_SPECIFIC.

        Heuristique: position et repetition elevees, diversite faible.
        """
        return (
            self.marker_position_score * 0.35 +
            self.marker_repeat_score * 0.25 +
            self.scope_language_score * 0.20 -
            self.marker_diversity_score * 0.10 -
            self.conflict_score * 0.10
        )

    def compute_mixed_score(self) -> float:
        """
        Calcule un score global pour MIXED.

        Heuristique: diversite et conflits eleves.
        """
        return (
            self.marker_diversity_score * 0.40 +
            self.conflict_score * 0.40 +
            self.scope_language_score * 0.20
        )


@dataclass
class DocContextFrame:
    """
    Frame de contexte documentaire stocke sur le document.

    Contient les marqueurs extraits et la classification du document.
    Ce frame est utilise pour l'heritage de contexte vers les assertions.

    Spec: ADR_ASSERTION_AWARE_KG.md - Section 4.3
    """
    # Identifiant du document
    document_id: str

    # Marqueurs forts (haute confiance, source fiable)
    strong_markers: List[str] = field(default_factory=list)

    # Marqueurs faibles (basse confiance, source moins fiable)
    weak_markers: List[str] = field(default_factory=list)

    # Evidence pour les marqueurs forts
    strong_evidence: List[str] = field(default_factory=list)

    # Evidence pour les marqueurs faibles
    weak_evidence: List[str] = field(default_factory=list)

    # Classification du scope documentaire
    doc_scope: DocScope = DocScope.GENERAL

    # Confiance dans la classification
    scope_confidence: float = 0.0

    # Signaux de scoring
    scope_signals: ScopeSignals = field(default_factory=ScopeSignals)

    # Notes du LLM (max 2 phrases)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire pour stockage."""
        return {
            "document_id": self.document_id,
            "strong_markers": self.strong_markers,
            "weak_markers": self.weak_markers,
            "strong_evidence": self.strong_evidence,
            "weak_evidence": self.weak_evidence,
            "doc_scope": self.doc_scope.value,
            "scope_confidence": self.scope_confidence,
            "scope_signals": self.scope_signals.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocContextFrame":
        """Deserialise depuis un dictionnaire."""
        return cls(
            document_id=data["document_id"],
            strong_markers=data.get("strong_markers", []),
            weak_markers=data.get("weak_markers", []),
            strong_evidence=data.get("strong_evidence", []),
            weak_evidence=data.get("weak_evidence", []),
            doc_scope=DocScope(data.get("doc_scope", "GENERAL")),
            scope_confidence=data.get("scope_confidence", 0.0),
            scope_signals=ScopeSignals.from_dict(data.get("scope_signals", {})),
            notes=data.get("notes", ""),
        )

    @classmethod
    def empty(cls, document_id: str) -> "DocContextFrame":
        """Cree un frame vide (document sans contexte detectable)."""
        return cls(
            document_id=document_id,
            doc_scope=DocScope.GENERAL,
            scope_confidence=0.5,
            notes="No context markers detected",
        )

    def has_markers(self) -> bool:
        """Retourne True si des marqueurs existent."""
        return bool(self.strong_markers or self.weak_markers)

    def get_dominant_marker(self) -> Optional[str]:
        """Retourne le marqueur dominant (premier strong, sinon premier weak)."""
        if self.strong_markers:
            return self.strong_markers[0]
        if self.weak_markers:
            return self.weak_markers[0]
        return None

    def __repr__(self) -> str:
        markers = self.strong_markers + self.weak_markers
        markers_str = ", ".join(markers[:3]) if markers else "none"
        return (
            f"DocContextFrame({self.doc_scope.value}, "
            f"markers=[{markers_str}], conf={self.scope_confidence:.2f})"
        )


@dataclass
class DocScopeAnalysis:
    """
    Sortie du LLM pour la validation de contexte.

    Ce modele correspond au JSON contract de l'ADR (Section 4.1).
    Le LLM recoit les candidats et retourne cette structure.

    Contrainte: Le LLM ne doit pas introduire de marqueurs
    non presents dans les candidats ou le texte cite.
    """
    # Marqueurs valides selectionnes parmi les candidats
    strong_markers: List[MarkerEvidence] = field(default_factory=list)
    weak_markers: List[MarkerEvidence] = field(default_factory=list)

    # Classification
    doc_scope: DocScope = DocScope.GENERAL
    scope_confidence: float = 0.0

    # Signaux
    signals: ScopeSignals = field(default_factory=ScopeSignals)

    # Evidence et notes
    evidence: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire (format JSON contract ADR)."""
        return {
            "strong_markers": [m.to_dict() for m in self.strong_markers],
            "weak_markers": [m.to_dict() for m in self.weak_markers],
            "doc_scope": self.doc_scope.value,
            "scope_confidence": self.scope_confidence,
            "signals": self.signals.to_dict(),
            "evidence": self.evidence,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocScopeAnalysis":
        """Deserialise depuis un dictionnaire."""
        return cls(
            strong_markers=[
                MarkerEvidence.from_dict(m)
                for m in data.get("strong_markers", [])
            ],
            weak_markers=[
                MarkerEvidence.from_dict(m)
                for m in data.get("weak_markers", [])
            ],
            doc_scope=DocScope(data.get("doc_scope", "GENERAL")),
            scope_confidence=data.get("scope_confidence", 0.0),
            signals=ScopeSignals.from_dict(data.get("signals", {})),
            evidence=data.get("evidence", []),
            notes=data.get("notes", ""),
        )

    def to_context_frame(self, document_id: str) -> DocContextFrame:
        """Convertit en DocContextFrame pour stockage."""
        return DocContextFrame(
            document_id=document_id,
            strong_markers=[m.value for m in self.strong_markers],
            weak_markers=[m.value for m in self.weak_markers],
            strong_evidence=[m.evidence for m in self.strong_markers],
            weak_evidence=[m.evidence for m in self.weak_markers],
            doc_scope=self.doc_scope,
            scope_confidence=self.scope_confidence,
            scope_signals=self.signals,
            notes=self.notes,
        )


__all__ = [
    "DocScope",
    "MarkerEvidence",
    "ScopeSignals",
    "DocContextFrame",
    "DocScopeAnalysis",
]
