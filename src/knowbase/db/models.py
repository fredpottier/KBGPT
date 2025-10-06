"""
Modèles SQLAlchemy pour gestion metadata système.

Phase 2 - Entity Types Registry
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func

from knowbase.db.base import Base


class EntityTypeRegistry(Base):
    """
    Registry des types d'entités découverts dynamiquement.

    Stocke tous les entity_types créés par le système (LLM ou admin),
    avec leur statut de validation et métadonnées.

    Workflow:
    1. LLM découvre nouveau type (ex: INFRASTRUCTURE) → créé avec status=pending
    2. Admin review → approve (status=approved) ou reject (status=rejected + cascade delete)
    3. Types approved deviennent "officiels" dans le système
    """

    __tablename__ = "entity_types_registry"

    # Primary key
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Type info
    type_name = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Nom du type (UPPERCASE, ex: INFRASTRUCTURE, SOLUTION)"
    )

    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="Statut: pending | approved | rejected"
    )

    # Metadata découverte
    first_seen = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Date première découverte du type"
    )

    discovered_by = Column(
        String(20),
        nullable=False,
        default="llm",
        comment="Source découverte: llm | admin | system"
    )

    # Compteurs (mis à jour périodiquement)
    entity_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Nombre total entités de ce type dans Neo4j"
    )

    pending_entity_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Nombre entités pending de ce type"
    )

    # Validation admin
    approved_by = Column(
        String(100),
        nullable=True,
        comment="Email/username admin qui a approuvé"
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date approbation"
    )

    rejected_by = Column(
        String(100),
        nullable=True,
        comment="Email/username admin qui a rejeté"
    )

    rejected_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date rejet"
    )

    rejection_reason = Column(
        Text,
        nullable=True,
        comment="Raison rejet (optionnel)"
    )

    # Multi-tenancy
    tenant_id = Column(
        String(50),
        nullable=False,
        default="default",
        index=True,
        comment="Tenant ID (isolation multi-tenant)"
    )

    # Metadata description (optionnel)
    description = Column(
        Text,
        nullable=True,
        comment="Description du type (ajoutée par admin)"
    )

    # Timestamps auto
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date création record"
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date dernière modification"
    )

    # Indexes composites pour queries fréquentes
    __table_args__ = (
        Index('ix_type_status_tenant', 'status', 'tenant_id'),
        Index('ix_type_name_tenant', 'type_name', 'tenant_id', unique=True),  # Contrainte unique composite
    )

    def __repr__(self) -> str:
        return (
            f"<EntityTypeRegistry(id={self.id}, type_name='{self.type_name}', "
            f"status='{self.status}', entity_count={self.entity_count})>"
        )

    @property
    def is_pending(self) -> bool:
        """True si type en attente validation."""
        return self.status == "pending"

    @property
    def is_approved(self) -> bool:
        """True si type approuvé."""
        return self.status == "approved"

    @property
    def is_rejected(self) -> bool:
        """True si type rejeté."""
        return self.status == "rejected"

    def approve(self, admin_email: str) -> None:
        """
        Approuve le type.

        Args:
            admin_email: Email admin qui approuve
        """
        self.status = "approved"
        self.approved_by = admin_email
        self.approved_at = datetime.now(timezone.utc)

    def reject(self, admin_email: str, reason: Optional[str] = None) -> None:
        """
        Rejette le type.

        Args:
            admin_email: Email admin qui rejette
            reason: Raison rejet (optionnel)
        """
        self.status = "rejected"
        self.rejected_by = admin_email
        self.rejected_at = datetime.now(timezone.utc)
        self.rejection_reason = reason


__all__ = ["EntityTypeRegistry"]
