# src/knowbase/claimfirst/models/question_dimension.py
"""
QuestionDimension — Registre de questions factuelles cross-doc stabilisées.

Une QuestionDimension représente une question factuelle stable (ex: "What is
the minimum version required?") qui peut apparaître dans plusieurs documents
indépendants. C'est le pivot de comparaison cross-doc.

Principes :
- Le registre démarre VIDE (pas de seed IT/infra)
- Les dimensions émergent du corpus via le Dimension Mapper
- Chaque dimension a un contrat de valeur strict (value_type + operators)
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Listes fermées contractuelles
VALID_VALUE_TYPES = frozenset({"number", "version", "boolean", "percent", "enum", "string"})
VALID_OPERATORS = frozenset({"=", ">=", "<=", ">", "<", "approx", "in"})
VALID_COMPARABILITY = frozenset({"strict", "loose", "non_comparable"})
VALID_STATUSES = frozenset({"candidate", "validated", "deprecated", "merged"})


class QuestionDimension(BaseModel):
    """
    Question factuelle stable identifiable cross-doc.

    Exemple :
        dimension_key = "min_tls_version"
        canonical_question = "What is the minimum TLS version required?"
        value_type = "version"
        allowed_operators = [">=", "="]
    """

    dimension_id: str = Field(
        ...,
        description="ID déterministe qd_ + md5(tenant:dimension_key)[:12]"
    )

    dimension_key: str = Field(
        ...,
        min_length=1,
        description="Clé snake_case ≤5 mots, domain-agnostic"
    )

    canonical_question: str = Field(
        ...,
        min_length=1,
        description="Question factuelle en langue naturelle"
    )

    value_type: str = Field(
        ...,
        description="Type de valeur : number|version|boolean|percent|enum|string"
    )

    allowed_operators: List[str] = Field(
        default_factory=lambda: ["="],
        description="Sous-ensemble de =|>=|<=|>|<|approx|in"
    )

    value_comparable: str = Field(
        default="non_comparable",
        description="strict|loose|non_comparable"
    )

    scope_policy: str = Field(
        default="any",
        description="Politique de scope (v1 : toujours 'any')"
    )

    scope_axis_keys: List[str] = Field(
        default_factory=list,
        description="Axes de scope applicables (product, legal_frame, region, edition)"
    )

    status: str = Field(
        default="candidate",
        description="candidate|validated|deprecated|merged"
    )

    info_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de QS rattachées à cette dimension"
    )

    doc_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de documents distincts couverts"
    )

    positive_examples: List[str] = Field(
        default_factory=list,
        description="Exemples de claims qui correspondent"
    )

    negative_examples: List[str] = Field(
        default_factory=list,
        description="Exemples de claims qui NE correspondent PAS"
    )

    merged_into: Optional[str] = Field(
        default=None,
        description="ID de la dimension cible si status=merged"
    )

    tenant_id: str = Field(
        default="default",
        description="Tenant multi-locataire"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
    )

    created_by: str = Field(
        default="pipeline",
        description="Source de création (pipeline|manual|llm)"
    )

    @classmethod
    def make_id(cls, tenant_id: str, dimension_key: str) -> str:
        """Génère un ID déterministe pour une QuestionDimension."""
        normalized = dimension_key.lower().strip()
        content = f"{tenant_id}:{normalized}"
        return f"qd_{hashlib.md5(content.encode()).hexdigest()[:12]}"

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Sérialise pour persistence Neo4j."""
        return {
            "dimension_id": self.dimension_id,
            "dimension_key": self.dimension_key,
            "canonical_question": self.canonical_question,
            "value_type": self.value_type,
            "allowed_operators": self.allowed_operators,
            "value_comparable": self.value_comparable,
            "scope_policy": self.scope_policy,
            "scope_axis_keys": self.scope_axis_keys if self.scope_axis_keys else None,
            "status": self.status,
            "info_count": self.info_count,
            "doc_count": self.doc_count,
            "positive_examples": self.positive_examples[:5] if self.positive_examples else None,
            "negative_examples": self.negative_examples[:5] if self.negative_examples else None,
            "merged_into": self.merged_into,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_neo4j_record(cls, record: Dict[str, Any]) -> QuestionDimension:
        """Désérialise depuis Neo4j."""
        return cls(
            dimension_id=record["dimension_id"],
            dimension_key=record["dimension_key"],
            canonical_question=record["canonical_question"],
            value_type=record.get("value_type", "string"),
            allowed_operators=record.get("allowed_operators") or ["="],
            value_comparable=record.get("value_comparable", "non_comparable"),
            scope_policy=record.get("scope_policy", "any"),
            scope_axis_keys=record.get("scope_axis_keys") or [],
            status=record.get("status", "candidate"),
            info_count=record.get("info_count", 0),
            doc_count=record.get("doc_count", 0),
            positive_examples=record.get("positive_examples") or [],
            negative_examples=record.get("negative_examples") or [],
            merged_into=record.get("merged_into"),
            tenant_id=record.get("tenant_id", "default"),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
            created_by=record.get("created_by", "pipeline"),
        )


__all__ = [
    "QuestionDimension",
    "VALID_VALUE_TYPES",
    "VALID_OPERATORS",
    "VALID_COMPARABILITY",
    "VALID_STATUSES",
]
