# src/knowbase/claimfirst/models/canonical_entity.py
"""
Modèle CanonicalEntity — Nœud pivot cross-doc pour entités variantes.

Couche 1 de l'architecture Cross-Doc Knowledge Layers.
Un CanonicalEntity regroupe N Entity variantes (ex: "SAP Fiori", "Fiori",
"SAP Fiori apps") via des relations SAME_CANON_AS.

Les Entity existantes ne sont PAS modifiées. Le CanonicalEntity est un
nœud pivot additionnel qui permet la traversée cross-doc.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from knowbase.claimfirst.models.entity import EntityType


class CanonicalEntity(BaseModel):
    """
    Nœud pivot regroupant des Entity variantes cross-doc.

    Attributes:
        canonical_entity_id: ID déterministe "ce_" + md5(tenant:name)[:12]
        canonical_name: Nom élu par scoring multi-critères
        tenant_id: Tenant multi-locataire
        entity_type: Type inféré par vote majoritaire
        source_entity_ids: IDs des Entity regroupées
        doc_count: Nombre de documents distincts couverts
        total_mention_count: Somme des mentions de toutes les Entity
        method: Meilleure méthode ayant contribué au groupe
        created_at: Date de création
    """

    canonical_entity_id: str = Field(
        ...,
        description="ID déterministe ce_ + md5(tenant:normalized_name)[:12]"
    )

    canonical_name: str = Field(
        ...,
        min_length=1,
        description="Nom canonique élu par scoring multi-critères"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    entity_type: EntityType = Field(
        default=EntityType.OTHER,
        description="Type inféré par vote majoritaire (hors OTHER)"
    )

    source_entity_ids: List[str] = Field(
        default_factory=list,
        description="IDs des Entity regroupées"
    )

    doc_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de documents distincts couverts"
    )

    total_mention_count: int = Field(
        default=0,
        ge=0,
        description="Somme des mentions de toutes les Entity sources"
    )

    method: str = Field(
        default="",
        description="Meilleure méthode ayant contribué (alias_identity, prefix_dedup)"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    @classmethod
    def make_id(cls, tenant_id: str, canonical_name: str) -> str:
        """
        Génère un ID déterministe pour un CanonicalEntity.

        Pattern identique à SubjectAnchor.create_new().
        """
        normalized = canonical_name.lower().strip()
        content = f"{tenant_id}:{normalized}"
        return f"ce_{hashlib.md5(content.encode()).hexdigest()[:12]}"

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "canonical_entity_id": self.canonical_entity_id,
            "canonical_name": self.canonical_name,
            "tenant_id": self.tenant_id,
            "entity_type": self.entity_type.value,
            "source_entity_ids": self.source_entity_ids if self.source_entity_ids else None,
            "doc_count": self.doc_count,
            "total_mention_count": self.total_mention_count,
            "method": self.method,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "CanonicalEntity":
        """Construit un CanonicalEntity depuis un record Neo4j."""
        return cls(
            canonical_entity_id=record["canonical_entity_id"],
            canonical_name=record["canonical_name"],
            tenant_id=record["tenant_id"],
            entity_type=EntityType(record.get("entity_type", "other")),
            source_entity_ids=record.get("source_entity_ids") or [],
            doc_count=record.get("doc_count", 0),
            total_mention_count=record.get("total_mention_count", 0),
            method=record.get("method", ""),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
        )

    @staticmethod
    def majority_vote_type(
        entity_types: List[EntityType],
    ) -> EntityType:
        """
        Vote majoritaire sur les types d'entités, en ignorant OTHER.

        Si 50/50 entre 2 types non-OTHER → fallback OTHER.
        Si tous OTHER → OTHER.
        """
        non_other = [t for t in entity_types if t != EntityType.OTHER]
        if not non_other:
            return EntityType.OTHER

        counts = Counter(non_other)
        top_two = counts.most_common(2)

        # Un seul type non-OTHER, ou un type clairement majoritaire
        if len(top_two) == 1 or top_two[0][1] > top_two[1][1]:
            return top_two[0][0]

        # 50/50 exact → ambiguïté → OTHER
        return EntityType.OTHER


__all__ = [
    "CanonicalEntity",
]
