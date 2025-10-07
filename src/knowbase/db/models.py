"""
Modèles SQLAlchemy pour gestion metadata système.

Phase 2 - Entity Types Registry
Phase 6 - Document Types Management
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index, ForeignKey, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

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


class DocumentType(Base):
    """
    Types de documents pour guider l'extraction d'entités.

    Permet de définir des contextes métier (technique, marketing, produit...)
    avec types d'entités suggérés pour améliorer la précision du LLM.

    Phase 6 - Document Types Management
    """

    __tablename__ = "document_types"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID du document type"
    )

    # Informations de base
    name = Column(
        String(100),
        nullable=False,
        comment="Nom du type (ex: Technical Documentation)"
    )

    slug = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Slug pour référence dans code (ex: technical)"
    )

    description = Column(
        Text,
        nullable=True,
        comment="Description du type de document"
    )

    # Prompt contextuel pour guider le LLM
    context_prompt = Column(
        Text,
        nullable=True,
        comment="Prompt additionnel pour contextualiser l'extraction"
    )

    # Configuration prompt généré
    prompt_config = Column(
        Text,
        nullable=True,
        comment="JSON config pour génération prompt (template, paramètres...)"
    )

    # Statistiques
    usage_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Nombre de documents importés avec ce type"
    )

    # État
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Type actif ou archivé"
    )

    # Multi-tenancy
    tenant_id = Column(
        String(50),
        nullable=False,
        default="default",
        index=True,
        comment="Tenant ID (isolation multi-tenant)"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date création"
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date dernière modification"
    )

    # Relations
    entity_type_associations = relationship(
        "DocumentTypeEntityType",
        back_populates="document_type",
        cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index('ix_doctype_slug_tenant', 'slug', 'tenant_id', unique=True),
        Index('ix_doctype_active_tenant', 'is_active', 'tenant_id'),
    )

    def __repr__(self) -> str:
        return f"<DocumentType(id={self.id}, name='{self.name}', slug='{self.slug}')>"


class DocumentTypeEntityType(Base):
    """
    Association entre DocumentType et EntityType (many-to-many).

    Indique quels types d'entités sont suggérés pour un type de document,
    avec métadonnées sur la source et validation.

    Phase 6 - Document Types Management
    """

    __tablename__ = "document_type_entity_types"

    # Primary key composite
    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    # Foreign keys
    document_type_id = Column(
        String(36),
        ForeignKey("document_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK vers document_types"
    )

    entity_type_name = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Nom du type d'entité (ex: SOLUTION, PRODUCT)"
    )

    # Métadonnées
    source = Column(
        String(20),
        nullable=False,
        default="manual",
        comment="Source: manual | llm_discovered | template"
    )

    confidence = Column(
        Float,
        nullable=True,
        comment="Confidence score si découvert par LLM (0.0-1.0)"
    )

    # Validation
    validated_by = Column(
        String(100),
        nullable=True,
        comment="Email admin qui a validé ce type"
    )

    validated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date validation"
    )

    # Metadata additionnelle
    examples = Column(
        Text,
        nullable=True,
        comment="JSON array d'exemples d'entités de ce type"
    )

    # Multi-tenancy
    tenant_id = Column(
        String(50),
        nullable=False,
        default="default",
        index=True,
        comment="Tenant ID"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date création"
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date dernière modification"
    )

    # Relations
    document_type = relationship("DocumentType", back_populates="entity_type_associations")

    # Indexes
    __table_args__ = (
        Index('ix_doctype_entitytype', 'document_type_id', 'entity_type_name', unique=True),
        Index('ix_entitytype_source', 'entity_type_name', 'source'),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentTypeEntityType(document_type_id={self.document_type_id}, "
            f"entity_type_name='{self.entity_type_name}', source='{self.source}')>"
        )


__all__ = ["EntityTypeRegistry", "DocumentType", "DocumentTypeEntityType"]
