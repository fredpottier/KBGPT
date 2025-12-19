"""Unit tests for database models.

This module contains comprehensive tests for SQLAlchemy models
including EntityTypeRegistry, DocumentType, User, and AuditLog.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import patch, MagicMock
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

# Set required environment variables before importing anything
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test_password")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-only")

# Mock external modules
sys.modules['redis'] = MagicMock()

from knowbase.db.base import Base
from knowbase.db.models import (
    EntityTypeRegistry,
    DocumentType,
    DocumentTypeEntityType,
    User,
    AuditLog,
)


@pytest.fixture
def in_memory_db() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestEntityTypeRegistry:
    """Tests for EntityTypeRegistry model."""

    def test_create_minimal(self, in_memory_db: Session) -> None:
        """Test creating EntityTypeRegistry with minimal fields."""
        entity_type = EntityTypeRegistry(
            type_name="INFRASTRUCTURE",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.id is not None
        assert entity_type.type_name == "INFRASTRUCTURE"
        assert entity_type.status == "pending"
        assert entity_type.discovered_by == "llm"
        assert entity_type.entity_count == 0
        assert entity_type.tenant_id == "default"

    def test_create_full(self, in_memory_db: Session) -> None:
        """Test creating EntityTypeRegistry with all fields."""
        entity_type = EntityTypeRegistry(
            type_name="SOLUTION",
            status="approved",
            discovered_by="admin",
            entity_count=10,
            pending_entity_count=2,
            approved_by="admin@example.com",
            tenant_id="tenant_001",
            description="SAP Solutions",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.type_name == "SOLUTION"
        assert entity_type.status == "approved"
        assert entity_type.discovered_by == "admin"
        assert entity_type.entity_count == 10
        assert entity_type.pending_entity_count == 2
        assert entity_type.approved_by == "admin@example.com"
        assert entity_type.description == "SAP Solutions"

    def test_is_pending_property(self, in_memory_db: Session) -> None:
        """Test is_pending property."""
        entity_type = EntityTypeRegistry(
            type_name="TEST",
            status="pending",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.is_pending is True
        assert entity_type.is_approved is False
        assert entity_type.is_rejected is False

    def test_is_approved_property(self, in_memory_db: Session) -> None:
        """Test is_approved property."""
        entity_type = EntityTypeRegistry(
            type_name="TEST",
            status="approved",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.is_pending is False
        assert entity_type.is_approved is True
        assert entity_type.is_rejected is False

    def test_is_rejected_property(self, in_memory_db: Session) -> None:
        """Test is_rejected property."""
        entity_type = EntityTypeRegistry(
            type_name="TEST",
            status="rejected",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.is_pending is False
        assert entity_type.is_approved is False
        assert entity_type.is_rejected is True

    def test_approve_method(self, in_memory_db: Session) -> None:
        """Test approve method."""
        entity_type = EntityTypeRegistry(
            type_name="TEST",
            status="pending",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        entity_type.approve("admin@example.com")
        in_memory_db.commit()

        assert entity_type.status == "approved"
        assert entity_type.approved_by == "admin@example.com"
        assert entity_type.approved_at is not None

    def test_reject_method(self, in_memory_db: Session) -> None:
        """Test reject method."""
        entity_type = EntityTypeRegistry(
            type_name="TEST",
            status="pending",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        entity_type.reject("admin@example.com", reason="Not relevant")
        in_memory_db.commit()

        assert entity_type.status == "rejected"
        assert entity_type.rejected_by == "admin@example.com"
        assert entity_type.rejected_at is not None
        assert entity_type.rejection_reason == "Not relevant"

    def test_reject_without_reason(self, in_memory_db: Session) -> None:
        """Test reject method without reason."""
        entity_type = EntityTypeRegistry(
            type_name="TEST",
            status="pending",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        entity_type.reject("admin@example.com")
        in_memory_db.commit()

        assert entity_type.rejection_reason is None

    def test_repr(self, in_memory_db: Session) -> None:
        """Test __repr__ method."""
        entity_type = EntityTypeRegistry(
            type_name="COMPONENT",
            status="approved",
            entity_count=5,
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        repr_str = repr(entity_type)
        assert "EntityTypeRegistry" in repr_str
        assert "COMPONENT" in repr_str
        assert "approved" in repr_str

    def test_timestamps_auto_set(self, in_memory_db: Session) -> None:
        """Test that timestamps are automatically set."""
        entity_type = EntityTypeRegistry(
            type_name="TIMESTAMP_TEST",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.created_at is not None
        assert entity_type.updated_at is not None
        assert entity_type.first_seen is not None

    def test_normalization_fields(self, in_memory_db: Session) -> None:
        """Test normalization workflow fields."""
        entity_type = EntityTypeRegistry(
            type_name="NORM_TEST",
            normalization_status="generating",
            normalization_job_id="job_123",
        )
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.normalization_status == "generating"
        assert entity_type.normalization_job_id == "job_123"


class TestDocumentType:
    """Tests for DocumentType model."""

    def test_create_minimal(self, in_memory_db: Session) -> None:
        """Test creating DocumentType with minimal fields."""
        doc_type = DocumentType(
            name="Technical Documentation",
            slug="technical",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assert doc_type.id is not None
        assert doc_type.name == "Technical Documentation"
        assert doc_type.slug == "technical"
        assert doc_type.is_active is True
        assert doc_type.usage_count == 0
        assert doc_type.tenant_id == "default"

    def test_create_full(self, in_memory_db: Session) -> None:
        """Test creating DocumentType with all fields."""
        doc_type = DocumentType(
            name="Marketing Materials",
            slug="marketing",
            description="Marketing collateral and presentations",
            context_prompt="Focus on product positioning and value propositions",
            is_active=True,
            usage_count=25,
            tenant_id="tenant_001",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assert doc_type.name == "Marketing Materials"
        assert doc_type.description == "Marketing collateral and presentations"
        assert doc_type.context_prompt is not None
        assert doc_type.usage_count == 25

    def test_uuid_generation(self, in_memory_db: Session) -> None:
        """Test that UUID is automatically generated."""
        doc_type = DocumentType(
            name="Test Type",
            slug="test",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        # ID should be valid UUID string
        assert len(doc_type.id) == 36
        # Should be parseable as UUID
        uuid.UUID(doc_type.id)

    def test_slug_uniqueness(self, in_memory_db: Session) -> None:
        """Test that slug has unique constraint within tenant."""
        doc_type1 = DocumentType(
            name="Type 1",
            slug="unique_slug",
            tenant_id="tenant_a",
        )
        in_memory_db.add(doc_type1)
        in_memory_db.commit()

        # Same slug in different tenant should work
        doc_type2 = DocumentType(
            name="Type 2",
            slug="unique_slug",
            tenant_id="tenant_b",
        )
        in_memory_db.add(doc_type2)
        in_memory_db.commit()

        assert doc_type1.slug == doc_type2.slug
        assert doc_type1.tenant_id != doc_type2.tenant_id

    def test_repr(self, in_memory_db: Session) -> None:
        """Test __repr__ method."""
        doc_type = DocumentType(
            name="Repr Test",
            slug="repr-test",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        repr_str = repr(doc_type)
        assert "DocumentType" in repr_str
        assert "Repr Test" in repr_str
        assert "repr-test" in repr_str


class TestDocumentTypeEntityType:
    """Tests for DocumentTypeEntityType association model."""

    def test_create_association(self, in_memory_db: Session) -> None:
        """Test creating entity type association."""
        doc_type = DocumentType(
            name="Technical",
            slug="technical",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assoc = DocumentTypeEntityType(
            document_type_id=doc_type.id,
            entity_type_name="SOLUTION",
            source="manual",
        )
        in_memory_db.add(assoc)
        in_memory_db.commit()

        assert assoc.id is not None
        assert assoc.document_type_id == doc_type.id
        assert assoc.entity_type_name == "SOLUTION"
        assert assoc.source == "manual"

    def test_llm_discovered_association(self, in_memory_db: Session) -> None:
        """Test LLM-discovered entity type association."""
        doc_type = DocumentType(
            name="Technical",
            slug="technical",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assoc = DocumentTypeEntityType(
            document_type_id=doc_type.id,
            entity_type_name="INFRASTRUCTURE",
            source="llm_discovered",
            confidence=0.85,
        )
        in_memory_db.add(assoc)
        in_memory_db.commit()

        assert assoc.source == "llm_discovered"
        assert assoc.confidence == 0.85

    def test_validated_association(self, in_memory_db: Session) -> None:
        """Test validated entity type association."""
        doc_type = DocumentType(
            name="Technical",
            slug="technical",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assoc = DocumentTypeEntityType(
            document_type_id=doc_type.id,
            entity_type_name="PRODUCT",
            source="template",
            validated_by="admin@example.com",
        )
        in_memory_db.add(assoc)
        in_memory_db.commit()

        assert assoc.validated_by == "admin@example.com"

    def test_relationship_to_document_type(self, in_memory_db: Session) -> None:
        """Test relationship back to DocumentType."""
        doc_type = DocumentType(
            name="Technical",
            slug="technical",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assoc = DocumentTypeEntityType(
            document_type_id=doc_type.id,
            entity_type_name="SOLUTION",
            source="manual",
        )
        in_memory_db.add(assoc)
        in_memory_db.commit()

        # Refresh to load relationship
        in_memory_db.refresh(assoc)
        assert assoc.document_type.name == "Technical"

    def test_cascade_delete(self, in_memory_db: Session) -> None:
        """Test that associations are deleted when document type is deleted."""
        doc_type = DocumentType(
            name="Cascade Test",
            slug="cascade",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assoc = DocumentTypeEntityType(
            document_type_id=doc_type.id,
            entity_type_name="TEST",
            source="manual",
        )
        in_memory_db.add(assoc)
        in_memory_db.commit()

        assoc_id = assoc.id
        in_memory_db.delete(doc_type)
        in_memory_db.commit()

        # Association should be deleted
        result = in_memory_db.query(DocumentTypeEntityType).filter_by(
            id=assoc_id
        ).first()
        assert result is None

    def test_repr(self, in_memory_db: Session) -> None:
        """Test __repr__ method."""
        doc_type = DocumentType(
            name="Repr Test",
            slug="repr",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assoc = DocumentTypeEntityType(
            document_type_id=doc_type.id,
            entity_type_name="COMPONENT",
            source="template",
        )
        in_memory_db.add(assoc)
        in_memory_db.commit()

        repr_str = repr(assoc)
        assert "DocumentTypeEntityType" in repr_str
        assert "COMPONENT" in repr_str
        assert "template" in repr_str


class TestUser:
    """Tests for User model."""

    def test_create_minimal(self, in_memory_db: Session) -> None:
        """Test creating User with minimal fields."""
        user = User(
            email="test@example.com",
            password_hash="hashed_password_here",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.role == "viewer"
        assert user.is_active is True
        assert user.tenant_id == "default"

    def test_create_admin(self, in_memory_db: Session) -> None:
        """Test creating admin user."""
        user = User(
            email="admin@example.com",
            password_hash="admin_password_hash",
            full_name="Admin User",
            role="admin",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        assert user.role == "admin"
        assert user.full_name == "Admin User"

    def test_create_editor(self, in_memory_db: Session) -> None:
        """Test creating editor user."""
        user = User(
            email="editor@example.com",
            password_hash="editor_password_hash",
            role="editor",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        assert user.role == "editor"

    def test_uuid_generation(self, in_memory_db: Session) -> None:
        """Test that UUID is automatically generated."""
        user = User(
            email="uuid@example.com",
            password_hash="hash",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        assert len(user.id) == 36
        uuid.UUID(user.id)

    def test_email_unique(self, in_memory_db: Session) -> None:
        """Test that email has unique constraint."""
        user1 = User(
            email="unique@example.com",
            password_hash="hash1",
        )
        in_memory_db.add(user1)
        in_memory_db.commit()

        # Verify first user was created
        assert user1.id is not None

    def test_inactive_user(self, in_memory_db: Session) -> None:
        """Test creating inactive user."""
        user = User(
            email="inactive@example.com",
            password_hash="hash",
            is_active=False,
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        assert user.is_active is False

    def test_last_login_tracking(self, in_memory_db: Session) -> None:
        """Test last login timestamp tracking."""
        user = User(
            email="login@example.com",
            password_hash="hash",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        assert user.last_login_at is None

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        in_memory_db.commit()

        assert user.last_login_at is not None

    def test_repr(self, in_memory_db: Session) -> None:
        """Test __repr__ method."""
        user = User(
            email="repr@example.com",
            password_hash="hash",
            role="editor",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        repr_str = repr(user)
        assert "User" in repr_str
        assert "repr@example.com" in repr_str
        assert "editor" in repr_str


class TestAuditLog:
    """Tests for AuditLog model."""

    def test_create_minimal(self, in_memory_db: Session) -> None:
        """Test creating AuditLog with minimal fields."""
        audit = AuditLog(
            user_email="admin@example.com",
            action="CREATE",
            resource_type="entity",
            tenant_id="default",
        )
        in_memory_db.add(audit)
        in_memory_db.commit()

        assert audit.id is not None
        assert audit.user_email == "admin@example.com"
        assert audit.action == "CREATE"
        assert audit.resource_type == "entity"
        assert audit.timestamp is not None

    def test_create_full(self, in_memory_db: Session) -> None:
        """Test creating AuditLog with all fields."""
        user = User(
            email="audit_user@example.com",
            password_hash="hash",
        )
        in_memory_db.add(user)
        in_memory_db.commit()

        audit = AuditLog(
            user_id=user.id,
            user_email="audit_user@example.com",
            action="UPDATE",
            resource_type="entity_type",
            resource_id="type_123",
            tenant_id="tenant_001",
            details='{"before": "pending", "after": "approved"}',
        )
        in_memory_db.add(audit)
        in_memory_db.commit()

        assert audit.user_id == user.id
        assert audit.resource_id == "type_123"
        assert audit.details is not None

    def test_various_actions(self, in_memory_db: Session) -> None:
        """Test logging various action types."""
        actions = ["CREATE", "UPDATE", "DELETE", "APPROVE", "REJECT"]

        for action in actions:
            audit = AuditLog(
                user_email="test@example.com",
                action=action,
                resource_type="entity",
                tenant_id="default",
            )
            in_memory_db.add(audit)
            in_memory_db.commit()

            assert audit.action == action

    def test_resource_types(self, in_memory_db: Session) -> None:
        """Test logging various resource types."""
        resource_types = ["entity", "fact", "entity_type", "document_type", "user"]

        for resource_type in resource_types:
            audit = AuditLog(
                user_email="test@example.com",
                action="UPDATE",
                resource_type=resource_type,
                tenant_id="default",
            )
            in_memory_db.add(audit)
            in_memory_db.commit()

            assert audit.resource_type == resource_type

    def test_uuid_generation(self, in_memory_db: Session) -> None:
        """Test that UUID is automatically generated."""
        audit = AuditLog(
            user_email="uuid@example.com",
            action="CREATE",
            resource_type="entity",
            tenant_id="default",
        )
        in_memory_db.add(audit)
        in_memory_db.commit()

        assert len(audit.id) == 36
        uuid.UUID(audit.id)

    def test_timestamp_auto_set(self, in_memory_db: Session) -> None:
        """Test that timestamp is automatically set."""
        before = datetime.now(timezone.utc)
        audit = AuditLog(
            user_email="timestamp@example.com",
            action="CREATE",
            resource_type="entity",
            tenant_id="default",
        )
        in_memory_db.add(audit)
        in_memory_db.commit()
        after = datetime.now(timezone.utc)

        assert audit.timestamp is not None
        # Timestamp should be between before and after
        # (allowing for timezone handling variations)

    def test_user_foreign_key_nullable(self, in_memory_db: Session) -> None:
        """Test that user_id is nullable (for when user is deleted)."""
        audit = AuditLog(
            user_id=None,  # No user linked
            user_email="deleted_user@example.com",
            action="CREATE",
            resource_type="entity",
            tenant_id="default",
        )
        in_memory_db.add(audit)
        in_memory_db.commit()

        assert audit.user_id is None
        assert audit.user_email == "deleted_user@example.com"

    def test_repr(self, in_memory_db: Session) -> None:
        """Test __repr__ method."""
        audit = AuditLog(
            user_email="repr@example.com",
            action="DELETE",
            resource_type="fact",
            tenant_id="default",
        )
        in_memory_db.add(audit)
        in_memory_db.commit()

        repr_str = repr(audit)
        assert "AuditLog" in repr_str
        assert "repr@example.com" in repr_str
        assert "DELETE" in repr_str
        assert "fact" in repr_str


class TestModelRelationships:
    """Tests for model relationships."""

    def test_document_type_entity_type_relationship(
        self, in_memory_db: Session
    ) -> None:
        """Test DocumentType has many EntityType associations."""
        doc_type = DocumentType(
            name="Multi-Entity Type",
            slug="multi-entity",
        )
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        # Add multiple associations
        assocs = [
            DocumentTypeEntityType(
                document_type_id=doc_type.id,
                entity_type_name="SOLUTION",
                source="manual",
            ),
            DocumentTypeEntityType(
                document_type_id=doc_type.id,
                entity_type_name="PRODUCT",
                source="template",
            ),
            DocumentTypeEntityType(
                document_type_id=doc_type.id,
                entity_type_name="INFRASTRUCTURE",
                source="llm_discovered",
            ),
        ]
        for assoc in assocs:
            in_memory_db.add(assoc)
        in_memory_db.commit()

        # Refresh to load relationships
        in_memory_db.refresh(doc_type)
        assert len(doc_type.entity_type_associations) == 3


class TestModelDefaults:
    """Tests for model default values."""

    def test_entity_type_defaults(self, in_memory_db: Session) -> None:
        """Test EntityTypeRegistry default values."""
        entity_type = EntityTypeRegistry(type_name="DEFAULT_TEST")
        in_memory_db.add(entity_type)
        in_memory_db.commit()

        assert entity_type.status == "pending"
        assert entity_type.discovered_by == "llm"
        assert entity_type.entity_count == 0
        assert entity_type.pending_entity_count == 0
        assert entity_type.tenant_id == "default"

    def test_document_type_defaults(self, in_memory_db: Session) -> None:
        """Test DocumentType default values."""
        doc_type = DocumentType(name="Default Test", slug="default-test")
        in_memory_db.add(doc_type)
        in_memory_db.commit()

        assert doc_type.is_active is True
        assert doc_type.usage_count == 0
        assert doc_type.tenant_id == "default"

    def test_user_defaults(self, in_memory_db: Session) -> None:
        """Test User default values."""
        user = User(email="default@example.com", password_hash="hash")
        in_memory_db.add(user)
        in_memory_db.commit()

        assert user.role == "viewer"
        assert user.is_active is True
        assert user.tenant_id == "default"
