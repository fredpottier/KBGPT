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

    # Normalisation workflow (Phase 5B)
    normalization_status = Column(
        String(20),
        nullable=True,
        comment="Statut normalisation: generating | pending_review | NULL (none)"
    )

    normalization_job_id = Column(
        String(50),
        nullable=True,
        comment="Job ID RQ de la génération d'ontologie en cours"
    )

    normalization_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date lancement dernière normalisation"
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

    .. deprecated::
        Cette fonctionnalité est DEPRECATED depuis la version domain-agnostic.
        La solution s'adapte maintenant progressivement aux documents importés
        via le Domain Context global au lieu de types de documents prédéfinis.
        Ce modèle sera supprimé dans une future version.
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


class User(Base):
    """
    Utilisateurs du système avec authentification.

    Phase 0 - Security Hardening
    """

    __tablename__ = "users"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID de l'utilisateur"
    )

    # Informations d'identification
    email = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Email de l'utilisateur (login)"
    )

    password_hash = Column(
        String(255),
        nullable=False,
        comment="Hash bcrypt du mot de passe"
    )

    # Informations personnelles
    full_name = Column(
        String(100),
        nullable=True,
        comment="Nom complet de l'utilisateur"
    )

    # Rôle (RBAC Phase 0)
    role = Column(
        String(20),
        nullable=False,
        default="viewer",
        index=True,
        comment="Rôle: admin | editor | viewer"
    )

    # Multi-tenancy
    tenant_id = Column(
        String(50),
        nullable=False,
        default="default",
        index=True,
        comment="Tenant ID (isolation multi-tenant)"
    )

    # État
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Utilisateur actif ou désactivé"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date création compte"
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date dernière modification"
    )

    last_login_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date dernière connexion"
    )

    # Indexes
    __table_args__ = (
        Index('ix_user_email', 'email'),
        Index('ix_user_tenant_role', 'tenant_id', 'role'),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"


class AuditLog(Base):
    """
    Journal d'audit pour traçabilité des actions admin.

    Phase 0 - Security Hardening
    """

    __tablename__ = "audit_log"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID de l'entrée audit"
    )

    # Qui
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK vers users (null si user supprimé)"
    )

    user_email = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Email user (redondant pour historique)"
    )

    # Quoi
    action = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Action effectuée: CREATE | UPDATE | DELETE | APPROVE | REJECT"
    )

    resource_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Type de ressource: entity | fact | entity_type | document_type..."
    )

    resource_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="ID de la ressource affectée"
    )

    # Contexte
    tenant_id = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Tenant ID"
    )

    details = Column(
        Text,
        nullable=True,
        comment="JSON avec détails (before, after, reason...)"
    )

    # Quand
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
        comment="Date/heure de l'action"
    )

    # Indexes
    __table_args__ = (
        Index('ix_audit_timestamp', 'timestamp'),
        Index('ix_audit_user_action', 'user_id', 'action'),
        Index('ix_audit_resource', 'resource_type', 'resource_id'),
        Index('ix_audit_tenant_timestamp', 'tenant_id', 'timestamp'),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, user='{self.user_email}', "
            f"action='{self.action}', resource='{self.resource_type}')>"
        )


# ============================================================================
# Phase 2.5 - Memory Layer Models
# ============================================================================


class Session(Base):
    """
    Session de conversation persistante.

    Phase 2.5 - Memory Layer

    Permet de maintenir un contexte de conversation sur plusieurs interactions,
    avec gestion automatique du résumé via LangChain Memory.
    """

    __tablename__ = "sessions"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID de la session"
    )

    # Utilisateur propriétaire
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK vers users"
    )

    # Informations session
    title = Column(
        String(255),
        nullable=True,
        comment="Titre de la session (auto-généré ou défini par user)"
    )

    # Résumé LangChain Memory (auto-généré)
    summary = Column(
        Text,
        nullable=True,
        comment="Résumé cumulatif de la conversation (LangChain Memory)"
    )

    # Contexte métier (pour Context Resolver)
    context_metadata = Column(
        Text,
        nullable=True,
        comment="JSON métadonnées contexte (documents référencés, entités mentionnées...)"
    )

    # État
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Session active ou archivée"
    )

    # Multi-tenancy
    tenant_id = Column(
        String(50),
        nullable=False,
        default="default",
        index=True,
        comment="Tenant ID"
    )

    # Compteurs
    message_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Nombre de messages dans la session"
    )

    token_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Estimation tokens consommés (pour tracking)"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date création session"
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Date dernière activité"
    )

    last_message_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date dernier message"
    )

    # Relations
    user = relationship("User", backref="sessions")
    messages = relationship(
        "SessionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionMessage.created_at"
    )

    # Indexes
    __table_args__ = (
        Index('ix_session_user_active', 'user_id', 'is_active'),
        Index('ix_session_tenant_updated', 'tenant_id', 'updated_at'),
    )

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, user_id={self.user_id}, title='{self.title}')>"


class SessionMessage(Base):
    """
    Message individuel dans une session de conversation.

    Phase 2.5 - Memory Layer

    Stocke chaque échange (question user + réponse assistant) avec métadonnées
    pour le context resolver et l'audit.
    """

    __tablename__ = "session_messages"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID du message"
    )

    # Session parente
    session_id = Column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK vers sessions"
    )

    # Rôle du message
    role = Column(
        String(20),
        nullable=False,
        index=True,
        comment="Rôle: user | assistant | system"
    )

    # Contenu
    content = Column(
        Text,
        nullable=False,
        comment="Contenu textuel du message"
    )

    # Métadonnées pour Context Resolver
    entities_mentioned = Column(
        Text,
        nullable=True,
        comment="JSON array entités mentionnées dans ce message"
    )

    documents_referenced = Column(
        Text,
        nullable=True,
        comment="JSON array documents référencés (sources RAG)"
    )

    # Métadonnées LLM
    model_used = Column(
        String(50),
        nullable=True,
        comment="Modèle LLM utilisé pour la réponse (si role=assistant)"
    )

    tokens_input = Column(
        Integer,
        nullable=True,
        comment="Tokens input pour cette réponse"
    )

    tokens_output = Column(
        Integer,
        nullable=True,
        comment="Tokens output pour cette réponse"
    )

    latency_ms = Column(
        Integer,
        nullable=True,
        comment="Latence réponse en millisecondes"
    )

    # Feedback utilisateur (optionnel)
    feedback_rating = Column(
        Integer,
        nullable=True,
        comment="Rating user: 1 (thumbs down) | 2 (thumbs up)"
    )

    feedback_comment = Column(
        Text,
        nullable=True,
        comment="Commentaire feedback user"
    )

    # Multi-tenancy
    tenant_id = Column(
        String(50),
        nullable=False,
        default="default",
        index=True,
        comment="Tenant ID"
    )

    # Timestamp
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
        comment="Date création message"
    )

    # Relations
    session = relationship("Session", back_populates="messages")

    # Indexes
    __table_args__ = (
        Index('ix_message_session_created', 'session_id', 'created_at'),
        Index('ix_message_tenant_created', 'tenant_id', 'created_at'),
    )

    def __repr__(self) -> str:
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<SessionMessage(id={self.id}, role='{self.role}', content='{content_preview}')>"


# ============================================================================
# Domain Context - Configuration Métier
# ============================================================================


class DomainContext(Base):
    """
    Profil de contexte métier pour un tenant.

    Stocke la configuration du domaine métier (industrie, acronymes, concepts clés)
    pour injection dynamique dans les prompts LLM.

    Migré depuis Neo4j vers PostgreSQL pour:
    - Survie aux purges du Knowledge Graph
    - Cohérence avec autres métadonnées (users, entity types)
    - Backup/restore simplifié
    """

    __tablename__ = "domain_contexts"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID du domain context"
    )

    # Tenant (unique constraint)
    tenant_id = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Tenant ID (unique - un contexte par tenant)"
    )

    # Informations domaine
    domain_summary = Column(
        Text,
        nullable=False,
        comment="Résumé concis du domaine métier (1-2 phrases)"
    )

    industry = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Industrie principale (regulatory, pharmaceutical, technology, etc.)"
    )

    # Listes stockées en JSON
    sub_domains = Column(
        Text,
        nullable=True,
        default="[]",
        comment="JSON array des sous-domaines"
    )

    target_users = Column(
        Text,
        nullable=True,
        default="[]",
        comment="JSON array des profils utilisateurs cibles"
    )

    document_types = Column(
        Text,
        nullable=True,
        default="[]",
        comment="JSON array des types de documents traités"
    )

    common_acronyms = Column(
        Text,
        nullable=True,
        default="{}",
        comment="JSON object acronymes → expansions"
    )

    key_concepts = Column(
        Text,
        nullable=True,
        default="[]",
        comment="JSON array des concepts clés du domaine"
    )

    # Configuration injection
    context_priority = Column(
        String(20),
        nullable=False,
        default="medium",
        comment="Priorité injection: low | medium | high"
    )

    llm_injection_prompt = Column(
        Text,
        nullable=False,
        comment="Texte prêt pour injection dans prompts système LLM"
    )

    versioning_hints = Column(
        Text,
        nullable=True,
        default="",
        comment="Conventions de versioning spécifiques au domaine (texte libre)"
    )

    identification_semantics = Column(
        Text,
        nullable=True,
        default="",
        comment="Règles d'identification sémantique des valeurs ambiguës (release_id vs year, etc.)"
    )

    axis_reclassification_rules = Column(
        Text,
        nullable=True,
        default="",
        comment="JSON array of deterministic post-LLM reclassification rules"
    )

    axis_policy = Column(
        Text,
        nullable=True,
        default="",
        comment="JSON object defining axis policy for ApplicabilityFrame pipeline"
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

    def __repr__(self) -> str:
        return f"<DomainContext(tenant_id='{self.tenant_id}', industry='{self.industry}')>"


__all__ = [
    "EntityTypeRegistry",
    "DocumentType",
    "DocumentTypeEntityType",
    "User",
    "AuditLog",
    "Session",
    "SessionMessage",
    "DomainContext"
]
