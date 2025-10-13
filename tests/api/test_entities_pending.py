"""
Tests intégration pour API /entities/pending.

Phase 1 - Liste entités non cataloguées

Note: Tests basiques sans fixtures Neo4j complexes.
"""

import pytest
from fastapi.testclient import TestClient

from knowbase.api.main import create_app


@pytest.fixture(scope="module")
def client():
    """Fixture client FastAPI."""
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestListPendingEntities:
    """Tests GET /api/entities/pending."""

    def test_list_pending_default_params(self, client, viewer_headers):
        """✅ Liste pending avec params défaut."""
        response = client.get("/api/entities/pending", headers=viewer_headers)

        assert response.status_code == 200
        data = response.json()

        # Structure réponse
        assert "entities" in data
        assert "total" in data
        assert "entity_type_filter" in data

        assert isinstance(data["entities"], list)
        assert isinstance(data["total"], int)

    def test_list_pending_with_entity_type_filter(self, client, viewer_headers):
        """✅ Filtre par entity_type."""
        response = client.get("/api/entities/pending?entity_type=SOLUTION", headers=viewer_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["entity_type_filter"] == "SOLUTION"

    def test_list_pending_with_pagination(self, client, viewer_headers):
        """✅ Pagination limit/offset."""
        response = client.get("/api/entities/pending?limit=10&offset=0", headers=viewer_headers)

        assert response.status_code == 200
        data = response.json()

        # Max 10 résultats
        assert len(data["entities"]) <= 10

    def test_list_pending_with_tenant_id(self, client, viewer_headers):
        """✅ Filtrage par tenant_id (via JWT, pas query param)."""
        # Note: Avec JWT, tenant_id vient du token automatiquement
        response = client.get("/api/entities/pending", headers=viewer_headers)

        assert response.status_code == 200

    def test_list_pending_invalid_limit(self, client, viewer_headers):
        """❌ Limite invalide → 422."""
        response = client.get("/api/entities/pending?limit=0", headers=viewer_headers)

        assert response.status_code == 422

    def test_list_pending_invalid_offset(self, client, viewer_headers):
        """❌ Offset négatif → 422."""
        response = client.get("/api/entities/pending?offset=-1", headers=viewer_headers)

        assert response.status_code == 422


class TestDiscoveredTypes:
    """Tests GET /api/entities/types/discovered."""

    def test_list_discovered_types(self, client, viewer_headers):
        """✅ Liste types découverts."""
        response = client.get("/api/entities/types/discovered", headers=viewer_headers)

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

        # Structure chaque type
        if len(data) > 0:
            type_entry = data[0]
            assert "type_name" in type_entry
            assert "total_entities" in type_entry
            assert "pending_count" in type_entry
            assert "validated_count" in type_entry

    def test_discovered_types_with_tenant(self, client, viewer_headers):
        """✅ Types découverts par tenant (via JWT)."""
        # Tenant ID vient automatiquement du JWT
        response = client.get("/api/entities/types/discovered", headers=viewer_headers)

        assert response.status_code == 200


# === Résumé Tests ===
# Total: 8 tests basiques
# Coverage: Params, filtres, pagination, validation
#
# Note: Tests fonctionnels avec données réelles nécessitent:
# - Neo4j avec entités test
# - Fixtures création entités pending/validated
# - Validation compteurs exact
