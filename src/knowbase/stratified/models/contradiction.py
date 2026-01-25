# src/knowbase/stratified/models/contradiction.py
"""
Modèle Contradiction pour MVP V1.
Représente une tension détectée entre deux Informations.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ContradictionNature(str, Enum):
    """Types de contradictions."""
    VALUE_CONFLICT = "value_conflict"
    VALUE_EXCEEDS_MINIMUM = "value_exceeds_minimum"  # Soft
    VALUE_BELOW_MAXIMUM = "value_below_maximum"      # Soft
    SCOPE_CONFLICT = "scope_conflict"
    TEMPORAL_CONFLICT = "temporal_conflict"
    MISSING_CLAIM = "missing_claim"


class TensionLevel(str, Enum):
    """Niveaux de tension."""
    NONE = "none"
    SOFT = "soft"    # Compatible mais différent
    HARD = "hard"    # Incompatible
    UNKNOWN = "unknown"


@dataclass
class Contradiction:
    """
    Modèle Contradiction MVP V1.

    Représente une tension entre deux Informations
    sur le même ClaimKey.
    """
    # Identifiants
    contradiction_id: str
    claimkey_id: str

    # Informations en conflit
    info_a_id: str
    info_a_document: str
    info_a_value_raw: Optional[str]
    info_a_context: dict

    info_b_id: str
    info_b_document: str
    info_b_value_raw: Optional[str]
    info_b_context: dict

    # Classification
    nature: ContradictionNature
    tension_level: TensionLevel
    explanation: str

    # Métadonnées
    detected_at: datetime = field(default_factory=datetime.utcnow)
    detection_method: str = "value_normalized_comparison"

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "contradiction_id": self.contradiction_id,
            "claimkey_id": self.claimkey_id,
            "info_a_id": self.info_a_id,
            "info_a_document": self.info_a_document,
            "info_a_value_raw": self.info_a_value_raw,
            "info_b_id": self.info_b_id,
            "info_b_document": self.info_b_document,
            "info_b_value_raw": self.info_b_value_raw,
            "nature": self.nature.value,
            "tension_level": self.tension_level.value,
            "explanation": self.explanation,
            "detected_at": self.detected_at.isoformat(),
            "detection_method": self.detection_method
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "Contradiction":
        """Construit depuis un record Neo4j."""
        return cls(
            contradiction_id=record["contradiction_id"],
            claimkey_id=record["claimkey_id"],
            info_a_id=record["info_a_id"],
            info_a_document=record["info_a_document"],
            info_a_value_raw=record.get("info_a_value_raw"),
            info_a_context=record.get("info_a_context", {}),
            info_b_id=record["info_b_id"],
            info_b_document=record["info_b_document"],
            info_b_value_raw=record.get("info_b_value_raw"),
            info_b_context=record.get("info_b_context", {}),
            nature=ContradictionNature(record["nature"]),
            tension_level=TensionLevel(record["tension_level"]),
            explanation=record.get("explanation", ""),
            detected_at=datetime.fromisoformat(record["detected_at"]) if record.get("detected_at") else datetime.utcnow(),
            detection_method=record.get("detection_method", "value_normalized_comparison")
        )
