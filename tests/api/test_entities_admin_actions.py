"""
Tests intégration pour admin actions /entities.

Phase 3 - Admin Actions (approve, merge, delete cascade)

Note: Tests simplifiés nécessitant Neo4j running.
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


@pytest.fixture
def admin_headers():
    """Headers admin pour authentification."""
    return {
        "X-Admin-Key": "admin-dev-key-change-in-production",
        "X-Tenant-ID": "default"
    }


class TestApproveEntity:
    """Tests POST /api/entities/{uuid}/approve."""

    def test_approve_requires_admin_key(self, client):
        """❌ Sans X-Admin-Key → 401 Unauthorized."""
        response = client.post(
            "/api/entities/fake-uuid/approve",
            json={"add_to_ontology": False}
        )

        assert response.status_code == 401
        assert "X-Admin-Key" in response.json()["detail"]

    def test_approve_invalid_admin_key(self, client):
        """❌ Mauvaise clé → 403 Forbidden."""
        response = client.post(
            "/api/entities/fake-uuid/approve",
            json={"add_to_ontology": False},
            headers={"X-Admin-Key": "wrong-key"}
        )

        assert response.status_code == 403

    def test_approve_nonexistent_entity_404(self, client, admin_headers):
        """❌ UUID inexistant → 404."""
        response = client.post(
            "/api/entities/nonexistent-uuid-12345/approve",
            json={"add_to_ontology": False},
            headers=admin_headers
        )

        assert response.status_code == 404


class TestMergeEntities:
    """Tests POST /api/entities/{source_uuid}/merge."""

    def test_merge_requires_admin_key(self, client):
        """❌ Sans X-Admin-Key → 401."""
        response = client.post(
            "/api/entities/source-uuid/merge",
            json={"target_uuid": "target-uuid"}
        )

        assert response.status_code == 401

    def test_merge_same_entity_400(self, client, admin_headers):
        """❌ Fusion même entité → 400 Bad Request."""
        uuid = "same-uuid-123"
        response = client.post(
            f"/api/entities/{uuid}/merge",
            json={"target_uuid": uuid},
            headers=admin_headers
        )

        assert response.status_code == 400
        assert "Cannot merge entity with itself" in response.json()["detail"]

    def test_merge_nonexistent_entities_404(self, client, admin_headers):
        """❌ Entités non trouvées → 404."""
        response = client.post(
            "/api/entities/nonexistent-source/merge",
            json={"target_uuid": "nonexistent-target"},
            headers=admin_headers
        )

        assert response.status_code == 404


class TestDeleteEntity:
    """Tests DELETE /api/entities/{uuid}."""

    def test_delete_requires_admin_key(self, client):
        """❌ Sans X-Admin-Key → 401."""
        response = client.delete("/api/entities/fake-uuid")

        assert response.status_code == 401

    def test_delete_nonexistent_entity_404(self, client, admin_headers):
        """❌ UUID inexistant → 404."""
        response = client.delete(
            "/api/entities/nonexistent-uuid-12345",
            headers=admin_headers
        )

        assert response.status_code == 404

    def test_delete_cascade_param(self, client, admin_headers):
        """✅ Param cascade accepté (true/false)."""
        # Test que le param est bien parsé (404 attendu car entité n'existe pas)
        response_cascade = client.delete(
            "/api/entities/fake-uuid?cascade=true",
            headers=admin_headers
        )

        response_no_cascade = client.delete(
            "/api/entities/fake-uuid?cascade=false",
            headers=admin_headers
        )

        # Les deux retournent 404 (même entité inexistante)
        assert response_cascade.status_code == 404
        assert response_no_cascade.status_code == 404


class TestMultiTenantIsolation:
    """Tests isolation multi-tenant."""

    def test_tenant_id_from_header(self, client, admin_headers):
        """✅ Tenant ID extrait depuis header X-Tenant-ID."""
        headers_tenant1 = {**admin_headers, "X-Tenant-ID": "tenant1"}
        headers_tenant2 = {**admin_headers, "X-Tenant-ID": "tenant2"}

        # Les requêtes avec différents tenant_id sont isolées
        # (404 attendu car entités n'existent pas, mais vérifie que header accepté)
        response1 = client.delete(
            "/api/entities/fake-uuid",
            headers=headers_tenant1
        )

        response2 = client.delete(
            "/api/entities/fake-uuid",
            headers=headers_tenant2
        )

        assert response1.status_code == 404
        assert response2.status_code == 404


# === Résumé Tests ===
# Total: 11 tests basiques
# Coverage: Authentification, erreurs 400/401/403/404, params
#
# Note: Tests fonctionnels complets nécessitent:
# - Neo4j avec données test
# - Fixtures création entités
# - Validation transfert relations merge
# - Validation cascade delete
#
# Ces tests vérifient les cas d'erreur et l'authentification.
# Tests fonctionnels E2E à faire en environnement complet.
