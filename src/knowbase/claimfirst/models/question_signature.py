# src/knowbase/claimfirst/models/question_signature.py
"""
QuestionSignature v2 — Runtime object complet pour comparaison cross-doc.

Combine :
- Une question factuelle stabilisée (via QuestionDimension)
- Un contrat de valeur comparable (ValueInfo)
- Un scope de comparabilité résolu (ResolvedScope)

V2 : Ajoute dimension_id, scope résolu, extraction_method.
     Garde QSValueType/QSExtractionLevel pour compatibilité.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from knowbase.claimfirst.models.resolved_scope import ResolvedScope


class QSValueType(str, Enum):
    """Type de la valeur extraite par la QuestionSignature."""

    NUMBER = "number"
    VERSION = "version"
    PERCENT = "percent"
    BOOLEAN = "boolean"
    STRING = "string"
    ENUM = "enum"


class QSExtractionLevel(str, Enum):
    """Niveau d'extraction de la QuestionSignature (legacy)."""

    LEVEL_A = "level_a"
    """Patterns regex déterministes — précision ~100%."""

    LEVEL_B = "level_b"
    """LLM evidence-locked — précision ~85-90%."""


class QSExtractionMethod(str, Enum):
    """Méthode d'extraction v2."""

    PATTERN_LEVEL_A = "pattern_level_a"
    """Patterns regex déterministes."""

    LLM_LEVEL_B = "llm_level_b"
    """Pipeline LLM 4 étapes."""


class QuestionSignature(BaseModel):
    """
    Question factuelle implicite extraite d'une Claim — v2.

    Le dimension_key pointe vers une QuestionDimension stabilisée.
    Le scope est résolu via la cascade 5 niveaux.
    La valeur suit le contrat ValueInfo.
    """

    qs_id: str = Field(
        ...,
        description="Identifiant unique"
    )

    claim_id: str = Field(
        ...,
        description="ID de la claim source"
    )

    doc_id: str = Field(
        ...,
        description="ID du document source"
    )

    tenant_id: str = Field(
        default="default",
        description="Tenant multi-locataire"
    )

    # Question factuelle (v1 compat)
    question: str = Field(
        ...,
        description="Question factuelle en langue naturelle"
    )

    dimension_key: str = Field(
        ...,
        description="Clé de regroupement cross-doc (snake_case, ≤5 mots)"
    )

    # V2 : lien vers QuestionDimension
    dimension_id: Optional[str] = Field(
        default=None,
        description="ID de la QuestionDimension stabilisée"
    )

    canonical_question: Optional[str] = Field(
        default=None,
        description="Question canonique de la dimension (si différente de question)"
    )

    # Valeur
    value_type: QSValueType = Field(
        ...,
        description="Type de la valeur extraite"
    )

    extracted_value: str = Field(
        ...,
        description="Valeur extraite de la claim (raw text)"
    )

    value_normalized: Optional[str] = Field(
        default=None,
        description="Valeur normalisée (si applicable)"
    )

    operator: str = Field(
        default="=",
        description="Opérateur : =|>=|<=|>|<|approx|in"
    )

    # V2 : Scope résolu
    scope: Optional[Dict[str, Any]] = Field(
        default=None,
        description="ResolvedScope sérialisé (dict)"
    )

    # Contexte d'extraction — v2
    extraction_method: QSExtractionMethod = Field(
        default=QSExtractionMethod.PATTERN_LEVEL_A,
        description="Méthode d'extraction v2"
    )

    # Legacy compat
    extraction_level: Optional[QSExtractionLevel] = Field(
        default=None,
        description="DEPRECATED — utiliser extraction_method"
    )

    pattern_name: Optional[str] = Field(
        default=None,
        description="Nom du pattern Level A (legacy, None pour LLM)"
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confiance"
    )

    # V2 : traçabilité gating
    gate_label: Optional[str] = Field(
        default=None,
        description="Label du gate LLM (COMPARABLE_FACT)"
    )

    gating_signals: Optional[List[str]] = Field(
        default=None,
        description="Signaux du candidate gating"
    )

    # Legacy compat
    scope_subject: Optional[str] = Field(
        default=None,
        description="DEPRECATED — utiliser scope"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
    )

    def get_resolved_scope(self) -> Optional[ResolvedScope]:
        """Désérialise le scope si présent."""
        if self.scope:
            return ResolvedScope.from_dict(self.scope)
        return None

    def set_resolved_scope(self, resolved: ResolvedScope) -> None:
        """Sérialise et stocke le scope."""
        self.scope = resolved.to_dict()

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Sérialise pour persistence Neo4j."""
        props: Dict[str, Any] = {
            "qs_id": self.qs_id,
            "claim_id": self.claim_id,
            "doc_id": self.doc_id,
            "tenant_id": self.tenant_id,
            "question": self.question,
            "dimension_key": self.dimension_key,
            "dimension_id": self.dimension_id,
            "canonical_question": self.canonical_question,
            "value_type": self.value_type.value,
            "extracted_value": self.extracted_value,
            "value_normalized": self.value_normalized,
            "operator": self.operator,
            "extraction_method": self.extraction_method.value,
            "confidence": self.confidence,
            "gate_label": self.gate_label,
            "gating_signals": self.gating_signals,
            # Legacy
            "extraction_level": self.extraction_level.value if self.extraction_level else None,
            "pattern_name": self.pattern_name,
            "scope_subject": self.scope_subject,
            "created_at": self.created_at.isoformat(),
        }
        # Scope sérialisé à plat pour Neo4j
        if self.scope:
            props["scope_basis"] = self.scope.get("scope_basis")
            props["scope_status"] = self.scope.get("scope_status")
            props["scope_confidence"] = self.scope.get("scope_confidence")
            props["scope_anchor_type"] = self.scope.get("primary_anchor_type")
            props["scope_anchor_id"] = self.scope.get("primary_anchor_id")
            props["scope_anchor_label"] = self.scope.get("primary_anchor_label")
        return props

    @classmethod
    def from_neo4j_record(cls, record: Dict[str, Any]) -> QuestionSignature:
        """Désérialise depuis Neo4j."""
        # Reconstruire scope dict si les champs à plat existent
        scope_dict = None
        if record.get("scope_basis") or record.get("scope_status"):
            scope_dict = {
                "primary_anchor_type": record.get("scope_anchor_type"),
                "primary_anchor_id": record.get("scope_anchor_id"),
                "primary_anchor_label": record.get("scope_anchor_label"),
                "axes": [],
                "scope_basis": record.get("scope_basis", "missing"),
                "inheritance_mode": "unknown",
                "scope_status": record.get("scope_status", "missing"),
                "scope_confidence": record.get("scope_confidence", 0.0),
                "comparable_for_dimension": record.get("scope_status") == "resolved",
            }

        # extraction_method avec fallback vers extraction_level
        extraction_method = QSExtractionMethod.PATTERN_LEVEL_A
        if record.get("extraction_method"):
            extraction_method = QSExtractionMethod(record["extraction_method"])
        elif record.get("extraction_level") == "level_b":
            extraction_method = QSExtractionMethod.LLM_LEVEL_B

        return cls(
            qs_id=record["qs_id"],
            claim_id=record["claim_id"],
            doc_id=record["doc_id"],
            tenant_id=record.get("tenant_id", "default"),
            question=record["question"],
            dimension_key=record["dimension_key"],
            dimension_id=record.get("dimension_id"),
            canonical_question=record.get("canonical_question"),
            value_type=QSValueType(record["value_type"]),
            extracted_value=record["extracted_value"],
            value_normalized=record.get("value_normalized"),
            operator=record.get("operator", "="),
            scope=scope_dict,
            extraction_method=extraction_method,
            extraction_level=QSExtractionLevel(record["extraction_level"])
            if record.get("extraction_level") else None,
            pattern_name=record.get("pattern_name"),
            confidence=record.get("confidence", 1.0),
            gate_label=record.get("gate_label"),
            gating_signals=record.get("gating_signals"),
            scope_subject=record.get("scope_subject"),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
        )


__all__ = [
    "QuestionSignature",
    "QSValueType",
    "QSExtractionLevel",
    "QSExtractionMethod",
]
