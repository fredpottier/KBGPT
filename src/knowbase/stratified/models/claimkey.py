# src/knowbase/stratified/models/claimkey.py
"""
Modèle ClaimKey pour MVP V1.
Représente une question factuelle canonique.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ClaimKeyStatus(str, Enum):
    """Statuts de ClaimKey."""
    EMERGENT = "emergent"        # < 3 infos ou 1 seul doc
    COMPARABLE = "comparable"    # >= 2 docs avec valeurs comparables
    DEPRECATED = "deprecated"    # Remplacé par autre ClaimKey
    ORPHAN = "orphan"            # Aucune info récente


@dataclass
class ClaimKey:
    """
    Modèle ClaimKey MVP V1.

    Représente une question factuelle canonique,
    indépendante du vocabulaire des documents.
    """
    # Identifiants
    claimkey_id: str
    tenant_id: str

    # Question factuelle
    key: str  # Identifiant machine (ex: "tls_min_version")
    canonical_question: str  # Question en langage naturel

    # Domaine
    domain: str  # Ex: "security.encryption"

    # Statut
    status: ClaimKeyStatus = ClaimKeyStatus.EMERGENT

    # Métriques
    info_count: int = 0
    doc_count: int = 0
    has_contradiction: bool = False

    # Méthode d'inférence
    inference_method: str = "pattern_level_a"

    # Métadonnées
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "claimkey_id": self.claimkey_id,
            "tenant_id": self.tenant_id,
            "key": self.key,
            "canonical_question": self.canonical_question,
            "domain": self.domain,
            "status": self.status.value,
            "info_count": self.info_count,
            "doc_count": self.doc_count,
            "has_contradiction": self.has_contradiction,
            "inference_method": self.inference_method,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "ClaimKey":
        """Construit depuis un record Neo4j."""
        return cls(
            claimkey_id=record["claimkey_id"],
            tenant_id=record["tenant_id"],
            key=record["key"],
            canonical_question=record.get("canonical_question", ""),
            domain=record.get("domain", ""),
            status=ClaimKeyStatus(record.get("status", "emergent")),
            info_count=record.get("info_count", 0),
            doc_count=record.get("doc_count", 0),
            has_contradiction=record.get("has_contradiction", False),
            inference_method=record.get("inference_method", "pattern_level_a"),
            created_at=datetime.fromisoformat(record["created_at"]) if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"]) if record.get("updated_at") else datetime.utcnow()
        )

    def update_metrics(self, info_count: int, doc_count: int):
        """Met à jour les métriques et recalcule le statut."""
        self.info_count = info_count
        self.doc_count = doc_count
        self.updated_at = datetime.utcnow()

        # Recalculer le statut
        if info_count == 0:
            self.status = ClaimKeyStatus.ORPHAN
        elif doc_count < 2:
            self.status = ClaimKeyStatus.EMERGENT
        else:
            self.status = ClaimKeyStatus.COMPARABLE
