# src/knowbase/claimfirst/models/axis_value.py
"""
Modèle AxisValue - Valeur d'un axe d'applicabilité.

INV-26: Toute axis_value a evidence (passage_id ou snippet_ref)

Types de valeurs supportés:
- SCALAR: Valeur unique (ex: "2021", "3.0")
- RANGE: Intervalle (ex: "2021-2023", "1.0-2.0")
- SET: Ensemble de valeurs (ex: ["EU", "US"])

La traçabilité est garantie: chaque valeur référence son passage source.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class AxisValueType(str, Enum):
    """Type de valeur d'axe."""

    SCALAR = "scalar"
    """Valeur unique (ex: "2021", "3.0")."""

    RANGE = "range"
    """Intervalle de valeurs (ex: "2021" à "2023")."""

    SET = "set"
    """Ensemble de valeurs discrètes (ex: ["EU", "US"])."""


class EvidenceSpan(BaseModel):
    """
    Référence à l'évidence source d'une valeur d'axe.

    INV-26: Traçabilité obligatoire pour toute axis_value.
    """

    passage_id: Optional[str] = Field(
        default=None,
        description="ID du passage source"
    )

    snippet_ref: str = Field(
        ...,
        description="Référence au snippet: 'section:3|offset:142' ou 'page:5'"
    )

    text_snippet: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Extrait de texte source (max 500 chars)"
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confiance dans l'extraction"
    )


class AxisValue(BaseModel):
    """
    Valeur d'un axe d'applicabilité.

    INV-26: Toute valeur doit avoir une evidence (passage_id ou snippet_ref).

    Attributes:
        value_type: Type de valeur (scalar, range, set)
        scalar_value: Valeur scalaire (si type == SCALAR)
        range_start: Début de l'intervalle (si type == RANGE)
        range_end: Fin de l'intervalle (si type == RANGE)
        set_values: Ensemble de valeurs (si type == SET)
        evidence: Référence à l'évidence source
        reliability: Fiabilité de l'extraction
    """

    value_type: AxisValueType = Field(
        ...,
        description="Type de valeur"
    )

    scalar_value: Optional[str] = Field(
        default=None,
        description="Valeur scalaire (si type == SCALAR)"
    )

    range_start: Optional[str] = Field(
        default=None,
        description="Début de l'intervalle (si type == RANGE)"
    )

    range_end: Optional[str] = Field(
        default=None,
        description="Fin de l'intervalle (si type == RANGE)"
    )

    set_values: List[str] = Field(
        default_factory=list,
        description="Ensemble de valeurs (si type == SET)"
    )

    # INV-26: Evidence obligatoire
    evidence: EvidenceSpan = Field(
        ...,
        description="Référence à l'évidence source (obligatoire)"
    )

    reliability: str = Field(
        default="explicit_text",
        description="Fiabilité: metadata | explicit_text | inferred"
    )

    @field_validator("reliability")
    @classmethod
    def validate_reliability(cls, v: str) -> str:
        """Valide que reliability est une valeur connue."""
        valid = {"metadata", "explicit_text", "inferred"}
        if v not in valid:
            raise ValueError(f"reliability must be one of {valid}")
        return v

    def model_post_init(self, __context) -> None:
        """Validation post-initialisation."""
        if self.value_type == AxisValueType.SCALAR and not self.scalar_value:
            raise ValueError("scalar_value required for SCALAR type")
        if self.value_type == AxisValueType.RANGE and (not self.range_start or not self.range_end):
            raise ValueError("range_start and range_end required for RANGE type")
        if self.value_type == AxisValueType.SET and not self.set_values:
            raise ValueError("set_values required for SET type")

    @classmethod
    def from_scalar(
        cls,
        value: str,
        evidence: EvidenceSpan,
        reliability: str = "explicit_text",
    ) -> "AxisValue":
        """
        Crée une AxisValue scalaire.

        Args:
            value: Valeur scalaire
            evidence: Référence à l'évidence
            reliability: Fiabilité

        Returns:
            AxisValue de type SCALAR
        """
        return cls(
            value_type=AxisValueType.SCALAR,
            scalar_value=value.strip(),
            evidence=evidence,
            reliability=reliability,
        )

    @classmethod
    def from_range(
        cls,
        start: str,
        end: str,
        evidence: EvidenceSpan,
        reliability: str = "explicit_text",
    ) -> "AxisValue":
        """
        Crée une AxisValue intervalle.

        Args:
            start: Début de l'intervalle
            end: Fin de l'intervalle
            evidence: Référence à l'évidence
            reliability: Fiabilité

        Returns:
            AxisValue de type RANGE
        """
        return cls(
            value_type=AxisValueType.RANGE,
            range_start=start.strip(),
            range_end=end.strip(),
            evidence=evidence,
            reliability=reliability,
        )

    @classmethod
    def from_set(
        cls,
        values: List[str],
        evidence: EvidenceSpan,
        reliability: str = "explicit_text",
    ) -> "AxisValue":
        """
        Crée une AxisValue ensemble.

        Args:
            values: Liste de valeurs
            evidence: Référence à l'évidence
            reliability: Fiabilité

        Returns:
            AxisValue de type SET
        """
        return cls(
            value_type=AxisValueType.SET,
            set_values=[v.strip() for v in values if v.strip()],
            evidence=evidence,
            reliability=reliability,
        )

    def get_display_value(self) -> str:
        """
        Retourne une représentation lisible de la valeur.

        Returns:
            Chaîne lisible
        """
        if self.value_type == AxisValueType.SCALAR:
            return self.scalar_value or ""
        elif self.value_type == AxisValueType.RANGE:
            return f"{self.range_start} - {self.range_end}"
        elif self.value_type == AxisValueType.SET:
            return ", ".join(self.set_values)
        return ""

    def get_all_values(self) -> List[str]:
        """
        Retourne toutes les valeurs contenues.

        Returns:
            Liste de valeurs
        """
        if self.value_type == AxisValueType.SCALAR:
            return [self.scalar_value] if self.scalar_value else []
        elif self.value_type == AxisValueType.RANGE:
            return [self.range_start, self.range_end] if self.range_start and self.range_end else []
        elif self.value_type == AxisValueType.SET:
            return list(self.set_values)
        return []

    def overlaps_with(self, other: "AxisValue") -> bool:
        """
        Vérifie si deux AxisValue se chevauchent.

        Args:
            other: Autre AxisValue à comparer

        Returns:
            True si les valeurs se chevauchent
        """
        self_values = set(self.get_all_values())
        other_values = set(other.get_all_values())

        # Intersection non vide = chevauchement
        return len(self_values & other_values) > 0

    def contains_value(self, value: str) -> bool:
        """
        Vérifie si la valeur est contenue.

        Args:
            value: Valeur à chercher

        Returns:
            True si la valeur est contenue
        """
        normalized = value.strip()
        return normalized in self.get_all_values()

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """
        Convertit en propriétés pour relation Neo4j HAS_AXIS_VALUE.

        INV-26: Evidence obligatoire (passage_id ou snippet_ref).
        """
        props = {
            "value_type": self.value_type.value,
            "reliability": self.reliability,
            # INV-26: Evidence traçabilité
            "evidence_passage_id": self.evidence.passage_id,
            "evidence_snippet_ref": self.evidence.snippet_ref,
        }

        if self.value_type == AxisValueType.SCALAR:
            props["scalar_value"] = self.scalar_value
        elif self.value_type == AxisValueType.RANGE:
            props["range_start"] = self.range_start
            props["range_end"] = self.range_end
        elif self.value_type == AxisValueType.SET:
            props["set_values"] = self.set_values

        return props

    @classmethod
    def from_neo4j_properties(cls, props: Dict[str, Any]) -> "AxisValue":
        """Reconstruit une AxisValue depuis propriétés Neo4j."""
        evidence = EvidenceSpan(
            passage_id=props.get("evidence_passage_id"),
            snippet_ref=props.get("evidence_snippet_ref", "unknown"),
        )

        value_type = AxisValueType(props["value_type"])

        if value_type == AxisValueType.SCALAR:
            return cls.from_scalar(
                value=props.get("scalar_value", ""),
                evidence=evidence,
                reliability=props.get("reliability", "explicit_text"),
            )
        elif value_type == AxisValueType.RANGE:
            return cls.from_range(
                start=props.get("range_start", ""),
                end=props.get("range_end", ""),
                evidence=evidence,
                reliability=props.get("reliability", "explicit_text"),
            )
        elif value_type == AxisValueType.SET:
            return cls.from_set(
                values=props.get("set_values", []),
                evidence=evidence,
                reliability=props.get("reliability", "explicit_text"),
            )

        raise ValueError(f"Unknown value_type: {value_type}")


__all__ = [
    "AxisValue",
    "AxisValueType",
    "EvidenceSpan",
]
