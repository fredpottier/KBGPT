"""
Modeles AnchorContext pour enrichissement des assertions.

Ces modeles definissent:
- Polarity: polarite de l'assertion (positive, negative, future, deprecated, conditional)
- AssertionScope: scope de l'assertion (general, constrained, unknown)
- OverrideType: type de remplacement si local override
- AnchorContext: contexte complet d'un anchor
- ProtoConceptContext: contexte agrege d'un ProtoConcept

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 4.2
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class Polarity(str, Enum):
    """
    Polarite de l'assertion.

    Indique si le concept est affirme positivement, nie, futur, etc.
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
    """
    GENERAL = "general"             # S'applique a toutes les variantes
    CONSTRAINED = "constrained"     # S'applique a une/des variantes specifiques
    UNKNOWN = "unknown"             # Impossible a determiner


class OverrideType(str, Enum):
    """
    Type de remplacement local.

    Utilise quand le passage contient un override explicite du contexte document.
    """
    SWITCH = "switch"               # Bascule vers un autre marqueur
    RANGE = "range"                 # Specifie une plage (from X to Y)
    GENERALIZATION = "generalization"  # Generalise (all versions)
    NULL = "null"                   # Pas d'override


class QualifierSource(str, Enum):
    """
    Source du qualificateur de contexte.

    Indique d'ou vient l'information de scope.
    """
    EXPLICIT = "explicit"           # Marqueur explicite dans le passage
    INHERITED_STRONG = "inherited_strong"  # Herite du DocContext (strong)
    INHERITED_WEAK = "inherited_weak"      # Herite du DocContext (weak)
    NONE = "none"                   # Pas de qualificateur


@dataclass
class LocalMarker:
    """
    Marqueur local detecte dans un passage.

    Un marqueur local peut overrider le contexte document.
    """
    value: str                      # Valeur du marqueur
    evidence: str                   # Quote textuelle
    confidence: float = 1.0         # Confiance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "evidence": self.evidence[:100] if self.evidence else "",
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalMarker":
        return cls(
            value=data["value"],
            evidence=data.get("evidence", ""),
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class AnchorContext:
    """
    Contexte d'assertion pour un Anchor.

    Enrichit un Anchor avec des informations de polarite, scope et marqueurs.
    Spec: ADR_ASSERTION_AWARE_KG.md - Section 4.2

    Attributes:
        polarity: Polarite de l'assertion
        scope: Scope de l'assertion
        local_markers: Marqueurs detectes localement dans le passage
        is_override: True si le passage override le contexte document
        override_type: Type d'override si applicable
        confidence: Confiance globale dans l'analyse
        qualifier_source: Source du qualificateur de scope
        evidence: Quotes justificatives
    """
    polarity: Polarity = Polarity.UNKNOWN
    scope: AssertionScope = AssertionScope.UNKNOWN
    local_markers: List[LocalMarker] = field(default_factory=list)
    is_override: bool = False
    override_type: OverrideType = OverrideType.NULL
    confidence: float = 0.5
    qualifier_source: QualifierSource = QualifierSource.NONE
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire."""
        return {
            "polarity": self.polarity.value,
            "scope": self.scope.value,
            "local_markers": [m.to_dict() for m in self.local_markers],
            "is_override": self.is_override,
            "override_type": self.override_type.value,
            "confidence": self.confidence,
            "qualifier_source": self.qualifier_source.value,
            "evidence": self.evidence[:2],  # Max 2 evidences
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnchorContext":
        """Deserialise depuis un dictionnaire."""
        return cls(
            polarity=Polarity(data.get("polarity", "unknown")),
            scope=AssertionScope(data.get("scope", "unknown")),
            local_markers=[
                LocalMarker.from_dict(m)
                for m in data.get("local_markers", [])
            ],
            is_override=data.get("is_override", False),
            override_type=OverrideType(data.get("override_type", "null")),
            confidence=data.get("confidence", 0.5),
            qualifier_source=QualifierSource(data.get("qualifier_source", "none")),
            evidence=data.get("evidence", []),
        )

    @classmethod
    def neutral(cls) -> "AnchorContext":
        """Cree un contexte neutre (passage neutre, pas d'analyse possible)."""
        return cls(
            polarity=Polarity.POSITIVE,
            scope=AssertionScope.UNKNOWN,
            confidence=0.3,
        )

    def get_markers(self) -> List[str]:
        """Retourne les valeurs des marqueurs locaux."""
        return [m.value for m in self.local_markers]

    def has_local_markers(self) -> bool:
        """True si des marqueurs locaux sont presents."""
        return len(self.local_markers) > 0


@dataclass
class ProtoConceptContext:
    """
    Contexte agrege pour un ProtoConcept.

    Agrege les AnchorContext de tous les anchors d'un ProtoConcept.
    Detecte les conflits et calcule les valeurs consolidees.

    Attributes:
        polarity: Polarite consolidee
        scope: Scope consolide
        markers: Marqueurs agreges (top-K)
        qualifier_source: Source du qualificateur
        confidence: Confiance globale
        has_conflict: True si conflit detecte entre anchors
        conflict_flags: Description des conflits
    """
    polarity: Polarity = Polarity.UNKNOWN
    scope: AssertionScope = AssertionScope.UNKNOWN
    markers: List[str] = field(default_factory=list)
    qualifier_source: QualifierSource = QualifierSource.NONE
    confidence: float = 0.5
    has_conflict: bool = False
    conflict_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire."""
        return {
            "polarity": self.polarity.value,
            "scope": self.scope.value,
            "markers": self.markers[:3],  # Top-3 marqueurs
            "qualifier_source": self.qualifier_source.value,
            "confidence": self.confidence,
            "has_conflict": self.has_conflict,
            "conflict_flags": self.conflict_flags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProtoConceptContext":
        """Deserialise depuis un dictionnaire."""
        return cls(
            polarity=Polarity(data.get("polarity", "unknown")),
            scope=AssertionScope(data.get("scope", "unknown")),
            markers=data.get("markers", []),
            qualifier_source=QualifierSource(data.get("qualifier_source", "none")),
            confidence=data.get("confidence", 0.5),
            has_conflict=data.get("has_conflict", False),
            conflict_flags=data.get("conflict_flags", []),
        )

    @classmethod
    def from_anchors(cls, anchor_contexts: List[AnchorContext]) -> "ProtoConceptContext":
        """
        Cree un ProtoConceptContext en agregeant les AnchorContext.

        Regles d'agregation (ADR Section 3.5):
        - Polarity: all positive -> positive, all negative -> negative, mixed -> conflict
        - Scope: any constrained with conf > 0.7 -> constrained
        - Markers: merge weighted by confidence, top-K
        """
        if not anchor_contexts:
            return cls()

        # === Agregation Polarity ===
        polarities = [ac.polarity for ac in anchor_contexts]
        unique_polarities = set(p for p in polarities if p != Polarity.UNKNOWN)

        conflict_flags = []
        if len(unique_polarities) == 0:
            polarity = Polarity.UNKNOWN
        elif len(unique_polarities) == 1:
            polarity = unique_polarities.pop()
        else:
            # Conflit de polarite
            polarity = Polarity.POSITIVE  # Default to positive
            conflict_flags.append(f"polarity_conflict: {[p.value for p in unique_polarities]}")

        # === Agregation Scope ===
        # Si au moins un anchor est constrained avec haute confiance -> constrained
        constrained_high = any(
            ac.scope == AssertionScope.CONSTRAINED and ac.confidence > 0.7
            for ac in anchor_contexts
        )
        general_any = any(
            ac.scope == AssertionScope.GENERAL
            for ac in anchor_contexts
        )

        if constrained_high:
            scope = AssertionScope.CONSTRAINED
        elif general_any and not constrained_high:
            scope = AssertionScope.GENERAL
        else:
            scope = AssertionScope.UNKNOWN

        # === Agregation Markers ===
        # Collecter tous les marqueurs avec leur confiance
        marker_scores: Dict[str, float] = {}
        for ac in anchor_contexts:
            for lm in ac.local_markers:
                if lm.value not in marker_scores:
                    marker_scores[lm.value] = 0.0
                marker_scores[lm.value] += lm.confidence * ac.confidence

        # Trier par score et prendre top-3
        sorted_markers = sorted(
            marker_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        markers = [m[0] for m in sorted_markers[:3]]

        # === Qualifier Source ===
        # Prendre la source la plus fiable
        sources = [ac.qualifier_source for ac in anchor_contexts]
        if QualifierSource.EXPLICIT in sources:
            qualifier_source = QualifierSource.EXPLICIT
        elif QualifierSource.INHERITED_STRONG in sources:
            qualifier_source = QualifierSource.INHERITED_STRONG
        elif QualifierSource.INHERITED_WEAK in sources:
            qualifier_source = QualifierSource.INHERITED_WEAK
        else:
            qualifier_source = QualifierSource.NONE

        # === Confidence ===
        # Moyenne ponderee des confidences
        if anchor_contexts:
            confidence = sum(ac.confidence for ac in anchor_contexts) / len(anchor_contexts)
        else:
            confidence = 0.5

        return cls(
            polarity=polarity,
            scope=scope,
            markers=markers,
            qualifier_source=qualifier_source,
            confidence=confidence,
            has_conflict=len(conflict_flags) > 0,
            conflict_flags=conflict_flags,
        )


__all__ = [
    "Polarity",
    "AssertionScope",
    "OverrideType",
    "QualifierSource",
    "LocalMarker",
    "AnchorContext",
    "ProtoConceptContext",
]
