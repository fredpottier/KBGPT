"""
Tests unitaires pour EntityTypeRegistryService.

Phase 2 - Entity Types Registry

Objectif: 80%+ couverture pour:
- get_or_create_type (création, récupération existant, types système)
- update_entity_counts
- list_types (filtres status, pagination)
- approve_type, reject_type, delete_type
- Isolation tenant_id
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from knowbase.db.base import Base
from knowbase.db.models import EntityTypeRegistry
from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService


@pytest.fixture
def db_session():
    """Fixture session DB SQLite in-memory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def service(db_session):
    """Fixture EntityTypeRegistryService."""
    return EntityTypeRegistryService(db_session)


class TestGetOrCreateType:
    """Tests pour get_or_create_type."""

    def test_create_new_type_llm_discovery(self, service, db_session):
        """✅ Nouveau type découvert par LLM → créé avec status=pending."""
        entity_type = service.get_or_create_type(
            type_name="INFRASTRUCTURE",
            tenant_id="default",
            discovered_by="llm"
        )

        assert entity_type.type_name == "INFRASTRUCTURE"
        assert entity_type.status == "pending"
        assert entity_type.discovered_by == "llm"
        assert entity_type.tenant_id == "default"
        assert entity_type.entity_count == 0
        assert entity_type.pending_entity_count == 0

        # Vérifier persistance DB
        db_type = db_session.query(EntityTypeRegistry).filter_by(
            type_name="INFRASTRUCTURE"
        ).first()
        assert db_type is not None
        assert db_type.id == entity_type.id

    def test_create_new_type_system_bootstrap(self, service):
        """✅ Type système (bootstrap) → créé avec status=approved."""
        entity_type = service.get_or_create_type(
            type_name="SOLUTION",
            tenant_id="default",
            discovered_by="system"  # Types système auto-approuvés
        )

        assert entity_type.type_name == "SOLUTION"
        assert entity_type.status == "approved"
        assert entity_type.discovered_by == "system"

    def test_get_existing_type(self, service):
        """✅ Type existant → retourné sans créer doublon."""
        # Créer type
        type1 = service.get_or_create_type(
            type_name="TECHNOLOGY",
            tenant_id="default",
            discovered_by="llm"
        )

        # Récupérer type existant
        type2 = service.get_or_create_type(
            type_name="TECHNOLOGY",
            tenant_id="default",
            discovered_by="llm"
        )

        # Doit être la même instance
        assert type1.id == type2.id
        assert type1.type_name == type2.type_name
        assert type1.status == type2.status

    def test_normalize_type_name_uppercase(self, service):
        """✅ Nom type normalisé en UPPERCASE."""
        entity_type = service.get_or_create_type(
            type_name="infrastructure",  # Lowercase
            tenant_id="default",
            discovered_by="llm"
        )

        assert entity_type.type_name == "INFRASTRUCTURE"  # Uppercase

    def test_tenant_isolation(self, service):
        """✅ Types isolés par tenant_id."""
        # Créer type pour tenant1
        type1 = service.get_or_create_type(
            type_name="PROCESS",
            tenant_id="tenant1",
            discovered_by="llm"
        )

        # Créer type identique pour tenant2 (doit créer nouvel enregistrement)
        type2 = service.get_or_create_type(
            type_name="PROCESS",
            tenant_id="tenant2",
            discovered_by="llm"
        )

        # IDs différents (isolation tenant)
        assert type1.id != type2.id
        assert type1.tenant_id == "tenant1"
        assert type2.tenant_id == "tenant2"


class TestUpdateEntityCounts:
    """Tests pour update_entity_counts."""

    def test_update_counts_success(self, service):
        """✅ Mise à jour compteurs OK."""
        # Créer type
        entity_type = service.get_or_create_type(
            type_name="MODULE",
            tenant_id="default",
            discovered_by="llm"
        )

        # Mettre à jour compteurs
        updated = service.update_entity_counts(
            type_name="MODULE",
            tenant_id="default",
            total_count=150,
            pending_count=30
        )

        assert updated is not None
        assert updated.entity_count == 150
        assert updated.pending_entity_count == 30

    def test_update_counts_type_not_found(self, service):
        """❌ Type non trouvé → retourne None."""
        result = service.update_entity_counts(
            type_name="NONEXISTENT",
            tenant_id="default",
            total_count=10,
            pending_count=5
        )

        assert result is None


class TestListTypes:
    """Tests pour list_types."""

    @pytest.fixture(autouse=True)
    def setup_types(self, service):
        """Prépare plusieurs types pour tests."""
        # Types approved
        service.get_or_create_type("SOLUTION", "default", "system")
        service.get_or_create_type("MODULE", "default", "system")

        # Types pending
        service.get_or_create_type("INFRASTRUCTURE", "default", "llm")
        service.get_or_create_type("TECHNOLOGY", "default", "llm")

        # Type rejected
        rejected = service.get_or_create_type("OBSOLETE", "default", "llm")
        service.reject_type("OBSOLETE", "admin@example.com", "Type obsolète", "default")

    def test_list_all_types(self, service):
        """✅ Liste tous les types sans filtre."""
        types = service.list_types(tenant_id="default", limit=100)

        assert len(types) == 5  # 2 approved + 2 pending + 1 rejected

    def test_list_types_filter_pending(self, service):
        """✅ Filtre status=pending."""
        types = service.list_types(
            tenant_id="default",
            status="pending",
            limit=100
        )

        assert len(types) == 2
        assert all(t.status == "pending" for t in types)

    def test_list_types_filter_approved(self, service):
        """✅ Filtre status=approved."""
        types = service.list_types(
            tenant_id="default",
            status="approved",
            limit=100
        )

        assert len(types) == 2
        assert all(t.status == "approved" for t in types)

    def test_list_types_filter_rejected(self, service):
        """✅ Filtre status=rejected."""
        types = service.list_types(
            tenant_id="default",
            status="rejected",
            limit=100
        )

        assert len(types) == 1
        assert types[0].status == "rejected"
        assert types[0].type_name == "OBSOLETE"

    def test_list_types_pagination(self, service):
        """✅ Pagination limit/offset."""
        # Première page (2 résultats)
        page1 = service.list_types(
            tenant_id="default",
            limit=2,
            offset=0
        )

        # Deuxième page (2 résultats)
        page2 = service.list_types(
            tenant_id="default",
            limit=2,
            offset=2
        )

        assert len(page1) == 2
        assert len(page2) == 2

        # IDs différents (pas de doublon)
        page1_ids = {t.id for t in page1}
        page2_ids = {t.id for t in page2}
        assert page1_ids.isdisjoint(page2_ids)


class TestCountTypes:
    """Tests pour count_types."""

    @pytest.fixture(autouse=True)
    def setup_types(self, service):
        """Prépare types pour count."""
        service.get_or_create_type("TYPE1", "default", "system")  # approved
        service.get_or_create_type("TYPE2", "default", "llm")     # pending
        service.get_or_create_type("TYPE3", "default", "llm")     # pending

    def test_count_all_types(self, service):
        """✅ Count total sans filtre."""
        count = service.count_types(tenant_id="default")
        assert count == 3

    def test_count_types_filter_pending(self, service):
        """✅ Count avec filtre status=pending."""
        count = service.count_types(tenant_id="default", status="pending")
        assert count == 2

    def test_count_types_filter_approved(self, service):
        """✅ Count avec filtre status=approved."""
        count = service.count_types(tenant_id="default", status="approved")
        assert count == 1


class TestApproveType:
    """Tests pour approve_type."""

    def test_approve_pending_type_success(self, service):
        """✅ Approbation type pending OK."""
        # Créer type pending
        entity_type = service.get_or_create_type(
            type_name="NEWTYPE",
            tenant_id="default",
            discovered_by="llm"
        )
        assert entity_type.status == "pending"

        # Approuver
        approved = service.approve_type(
            type_name="NEWTYPE",
            admin_email="admin@example.com",
            tenant_id="default"
        )

        assert approved is not None
        assert approved.status == "approved"
        assert approved.approved_by == "admin@example.com"
        assert approved.approved_at is not None
        assert isinstance(approved.approved_at, datetime)

    def test_approve_type_not_found(self, service):
        """❌ Type non trouvé → retourne None."""
        result = service.approve_type(
            type_name="NONEXISTENT",
            admin_email="admin@example.com",
            tenant_id="default"
        )

        assert result is None


class TestRejectType:
    """Tests pour reject_type."""

    def test_reject_type_success(self, service):
        """✅ Rejet type OK."""
        # Créer type
        entity_type = service.get_or_create_type(
            type_name="BADTYPE",
            tenant_id="default",
            discovered_by="llm"
        )

        # Rejeter
        rejected = service.reject_type(
            type_name="BADTYPE",
            admin_email="admin@example.com",
            reason="Type non pertinent",
            tenant_id="default"
        )

        assert rejected is not None
        assert rejected.status == "rejected"
        assert rejected.rejected_by == "admin@example.com"
        assert rejected.rejected_at is not None
        assert rejected.rejection_reason == "Type non pertinent"

    def test_reject_type_without_reason(self, service):
        """✅ Rejet sans raison (optionnel)."""
        entity_type = service.get_or_create_type(
            type_name="TEMPTYPE",
            tenant_id="default",
            discovered_by="llm"
        )

        rejected = service.reject_type(
            type_name="TEMPTYPE",
            admin_email="admin@example.com",
            reason=None,  # Raison optionnelle
            tenant_id="default"
        )

        assert rejected is not None
        assert rejected.status == "rejected"
        assert rejected.rejection_reason is None

    def test_reject_type_not_found(self, service):
        """❌ Type non trouvé → retourne None."""
        result = service.reject_type(
            type_name="NONEXISTENT",
            admin_email="admin@example.com",
            tenant_id="default"
        )

        assert result is None


class TestDeleteType:
    """Tests pour delete_type."""

    def test_delete_type_success(self, service, db_session):
        """✅ Suppression type OK."""
        # Créer type
        entity_type = service.get_or_create_type(
            type_name="TODELETE",
            tenant_id="default",
            discovered_by="llm"
        )
        type_id = entity_type.id

        # Supprimer
        success = service.delete_type(
            type_name="TODELETE",
            tenant_id="default"
        )

        assert success is True

        # Vérifier suppression DB
        deleted = db_session.query(EntityTypeRegistry).filter_by(id=type_id).first()
        assert deleted is None

    def test_delete_type_not_found(self, service):
        """❌ Type non trouvé → retourne False."""
        success = service.delete_type(
            type_name="NONEXISTENT",
            tenant_id="default"
        )

        assert success is False


class TestTypeProperties:
    """Tests pour propriétés EntityTypeRegistry model."""

    def test_is_pending_property(self, service):
        """✅ Propriété is_pending."""
        entity_type = service.get_or_create_type(
            type_name="PENDING_TYPE",
            tenant_id="default",
            discovered_by="llm"
        )

        assert entity_type.is_pending is True
        assert entity_type.is_approved is False
        assert entity_type.is_rejected is False

    def test_is_approved_property(self, service):
        """✅ Propriété is_approved."""
        entity_type = service.get_or_create_type(
            type_name="APPROVED_TYPE",
            tenant_id="default",
            discovered_by="system"  # Auto-approved
        )

        assert entity_type.is_approved is True
        assert entity_type.is_pending is False
        assert entity_type.is_rejected is False

    def test_is_rejected_property(self, service):
        """✅ Propriété is_rejected."""
        entity_type = service.get_or_create_type(
            type_name="REJECTED_TYPE",
            tenant_id="default",
            discovered_by="llm"
        )

        service.reject_type(
            type_name="REJECTED_TYPE",
            admin_email="admin@example.com",
            tenant_id="default"
        )

        entity_type = service.get_type_by_name("REJECTED_TYPE", "default")

        assert entity_type.is_rejected is True
        assert entity_type.is_pending is False
        assert entity_type.is_approved is False


# === Résumé Tests ===
# Total: 26 tests
# Couverture attendue: 85%+
#
# Tests critiques:
# - Auto-discovery LLM (status=pending)
# - Bootstrap système (status=approved)
# - Isolation multi-tenant
# - Workflow approve/reject
# - CRUD complet
# - Filtres et pagination
