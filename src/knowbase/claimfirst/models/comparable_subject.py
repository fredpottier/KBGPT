# src/knowbase/claimfirst/models/comparable_subject.py
"""
Modèle ComparableSubject - Sujet stable et comparable entre documents.

INV-25: Domain-agnostic - pas de hardcoding SAP/IT.

Principe fondamental: Un ComparableSubject représente l'entité STABLE
qui traverse les versions, éditions, ou révisions d'un document.

Exemples:
- "SAP S/4HANA" (pas "S/4HANA Business Scope Release 1809")
- "GDPR" (pas "GDPR Consolidated 2021")
- "ISO 27001" (pas "ISO 27001:2022")

Le ComparableSubject permet de comparer des documents qui parlent
du MÊME sujet mais avec des valeurs d'axes différentes (version, année, etc.).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ComparableSubject(BaseModel):
    """
    Sujet stable et comparable entre documents.

    C'est le pivot de comparaison inter-documents. Plusieurs documents
    peuvent être "ABOUT" le même ComparableSubject mais avec des valeurs
    d'axes différentes.

    Attributes:
        subject_id: Identifiant unique du sujet
        tenant_id: Tenant multi-locataire
        canonical_name: Nom canonique stable
        aliases: Alias connus pour ce sujet
        description: Description optionnelle
        doc_count: Nombre de documents liés
        source_doc_ids: Documents source
        created_at: Date de création
        updated_at: Date de dernière mise à jour
    """

    subject_id: str = Field(
        ...,
        description="Identifiant unique du sujet comparable"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    canonical_name: str = Field(
        ...,
        description="Nom canonique stable (ex: 'SAP S/4HANA', 'GDPR', 'ISO 27001')"
    )

    aliases: List[str] = Field(
        default_factory=list,
        description="Alias connus pour ce sujet"
    )

    description: Optional[str] = Field(
        default=None,
        description="Description optionnelle du sujet"
    )

    doc_count: int = Field(
        default=0,
        ge=0,
        description="Nombre de documents liés à ce sujet"
    )

    source_doc_ids: List[str] = Field(
        default_factory=list,
        description="IDs des documents source"
    )

    # Métadonnées de confiance
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiance dans l'identification [0-1]"
    )

    rationale: Optional[str] = Field(
        default=None,
        description="Justification de l'identification (max 240 chars)"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de dernière mise à jour"
    )

    def add_alias(self, alias: str) -> bool:
        """
        Ajoute un alias s'il n'existe pas déjà.

        Args:
            alias: Alias à ajouter

        Returns:
            True si l'alias a été ajouté
        """
        normalized = alias.strip()
        if normalized and normalized not in self.aliases:
            if normalized.lower() != self.canonical_name.lower():
                self.aliases.append(normalized)
                self.updated_at = datetime.utcnow()
                return True
        return False

    def add_doc_reference(self, doc_id: str) -> None:
        """
        Ajoute une référence de document.

        Args:
            doc_id: ID du document
        """
        if doc_id and doc_id not in self.source_doc_ids:
            self.source_doc_ids.append(doc_id)
            self.doc_count = len(self.source_doc_ids)
            self.updated_at = datetime.utcnow()

    def matches(self, query: str) -> bool:
        """
        Vérifie si le sujet correspond à une requête.

        Args:
            query: Requête à vérifier

        Returns:
            True si match
        """
        query_lower = query.lower().strip()

        # Match sur canonical_name
        if self.canonical_name.lower() == query_lower:
            return True

        # Match sur aliases
        for alias in self.aliases:
            if alias.lower() == query_lower:
                return True

        return False

    def compute_hash(self) -> str:
        """
        Calcule un hash stable pour le sujet.

        Returns:
            Hash hexadécimal sur 12 caractères
        """
        content = f"{self.tenant_id}:{self.canonical_name.lower()}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convertit en propriétés pour Neo4j."""
        return {
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "canonical_name": self.canonical_name,
            "aliases": self.aliases if self.aliases else None,
            "description": self.description,
            "doc_count": self.doc_count,
            "source_doc_ids": self.source_doc_ids if self.source_doc_ids else None,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "subject_hash": self.compute_hash(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_neo4j_record(cls, record: Dict[str, Any]) -> "ComparableSubject":
        """Construit un ComparableSubject depuis un record Neo4j."""
        return cls(
            subject_id=record["subject_id"],
            tenant_id=record["tenant_id"],
            canonical_name=record["canonical_name"],
            aliases=record.get("aliases") or [],
            description=record.get("description"),
            doc_count=record.get("doc_count", 0),
            source_doc_ids=record.get("source_doc_ids") or [],
            confidence=record.get("confidence", 0.0),
            rationale=record.get("rationale"),
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
        )

    @classmethod
    def create_new(
        cls,
        tenant_id: str,
        canonical_name: str,
        confidence: float = 0.0,
        rationale: Optional[str] = None,
        doc_id: Optional[str] = None,
    ) -> "ComparableSubject":
        """
        Factory pour créer un nouveau ComparableSubject.

        Args:
            tenant_id: Tenant ID
            canonical_name: Nom canonique du sujet
            confidence: Score de confiance
            rationale: Justification
            doc_id: Document source (optionnel)

        Returns:
            Nouveau ComparableSubject
        """
        name_hash = hashlib.md5(
            f"{tenant_id}:{canonical_name.lower()}".encode()
        ).hexdigest()[:12]
        subject_id = f"cs_{name_hash}"

        return cls(
            subject_id=subject_id,
            tenant_id=tenant_id,
            canonical_name=canonical_name,
            confidence=confidence,
            rationale=rationale,
            source_doc_ids=[doc_id] if doc_id else [],
            doc_count=1 if doc_id else 0,
        )


__all__ = [
    "ComparableSubject",
]
