# src/knowbase/claimfirst/models/resolved_scope.py
"""
ResolvedScope + ScopeAxis — Scope de comparabilité résolu pour QS.

Le scope détermine POUR QUEL sujet/produit/contexte une QS est valide.
Sans scope résolu, deux QS ne peuvent pas être comparées.

Cascade de résolution (5 niveaux) :
1. claim_explicit (conf 0.95)
2. claim_entities (conf 0.85)
3. section_context (conf 0.70)
4. document_context (conf 0.60)
5. ambiguous (non comparable)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


VALID_SCOPE_BASES = frozenset({
    "claim_explicit", "claim_llm", "claim_entities", "section_context",
    "document_context",
})

VALID_SCOPE_STATUSES = frozenset({
    "resolved", "inherited", "ambiguous", "missing",
})

VALID_AXIS_KEYS = frozenset({
    "product", "legal_frame", "region", "edition",
})

VALID_INHERITANCE_MODES = frozenset({
    "asserted", "inherited", "mixed", "unknown",
})


@dataclass
class ScopeAxis:
    """Un axe de scope résolu (ex: product=SAP S/4HANA)."""

    axis_key: str          # product|legal_frame|region|edition
    value: str             # Valeur textuelle
    value_id: Optional[str] = None   # ID de l'entité canonique si disponible
    source: str = "claim"  # claim|section|document

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axis_key": self.axis_key,
            "value": self.value,
            "value_id": self.value_id,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ScopeAxis:
        return cls(
            axis_key=d["axis_key"],
            value=d["value"],
            value_id=d.get("value_id"),
            source=d.get("source", "claim"),
        )


@dataclass
class ResolvedScope:
    """Scope de comparabilité résolu pour une QuestionSignature."""

    # Ancre principale (produit, norme, etc.)
    primary_anchor_type: Optional[str] = None  # product|legal_frame|service_scope
    primary_anchor_id: Optional[str] = None    # canonical_entity_id si disponible
    primary_anchor_label: Optional[str] = None  # Nom lisible

    # Axes de scope
    axes: List[ScopeAxis] = field(default_factory=list)

    # Méta-données de résolution
    scope_basis: str = "missing"  # claim_explicit|claim_entities|section_context|document_context
    inheritance_mode: str = "unknown"  # asserted|inherited|mixed|unknown
    scope_status: str = "missing"  # resolved|inherited|ambiguous|missing
    scope_confidence: float = 0.0
    comparable_for_dimension: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_anchor_type": self.primary_anchor_type,
            "primary_anchor_id": self.primary_anchor_id,
            "primary_anchor_label": self.primary_anchor_label,
            "axes": [a.to_dict() for a in self.axes],
            "scope_basis": self.scope_basis,
            "inheritance_mode": self.inheritance_mode,
            "scope_status": self.scope_status,
            "scope_confidence": self.scope_confidence,
            "comparable_for_dimension": self.comparable_for_dimension,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ResolvedScope:
        return cls(
            primary_anchor_type=d.get("primary_anchor_type"),
            primary_anchor_id=d.get("primary_anchor_id"),
            primary_anchor_label=d.get("primary_anchor_label"),
            axes=[ScopeAxis.from_dict(a) for a in d.get("axes", [])],
            scope_basis=d.get("scope_basis", "missing"),
            inheritance_mode=d.get("inheritance_mode", "unknown"),
            scope_status=d.get("scope_status", "missing"),
            scope_confidence=d.get("scope_confidence", 0.0),
            comparable_for_dimension=d.get("comparable_for_dimension", False),
        )


__all__ = [
    "ScopeAxis",
    "ResolvedScope",
    "VALID_SCOPE_BASES",
    "VALID_SCOPE_STATUSES",
    "VALID_AXIS_KEYS",
    "VALID_INHERITANCE_MODES",
]
