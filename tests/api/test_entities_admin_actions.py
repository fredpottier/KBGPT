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


# Note: admin_headers fixture désormais fournie par tests/conftest.py avec JWT


class TestApproveEntity:
    """Tests POST /api/entities/{uuid}/approve."""

    def test_approve_requires_admin_key(self, client):
        """❌ Sans JWT → 401/403 (non authentifié)."""
        response = client.post(
            "/api/entities/fake-uuid/approve",
            json={"add_to_ontology": False}
        )

        # FastAPI peut retourner 401 ou 403 selon la configuration
        assert response.status_code in [401, 403]

    def test_approve_invalid_admin_key(self, client):
        """❌ JWT invalide → 401 Unauthorized."""
        response = client.post(
            "/api/entities/fake-uuid/approve",
            json={"add_to_ontology": False},
            headers={"Authorization": "Bearer invalid-token-xyz"}
        )

        assert response.status_code == 401

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
        """❌ Sans JWT → 401/403 (non authentifié)."""
        response = client.post(
            "/api/entities/source-uuid/merge",
            json={"target_uuid": "target-uuid"}
        )

        assert response.status_code in [401, 403]

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
        """❌ Sans JWT → 401/403 (non authentifié)."""
        response = client.delete("/api/entities/fake-uuid")

        assert response.status_code in [401, 403]

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
        """✅ Tenant ID extrait depuis JWT claims (pas header manuel)."""
        # Note: Avec JWT, tenant_id vient du token JWT lui-même
        # On ne peut plus le surcharger manuellement via header
        # Ce test vérifie simplement que l'endpoint fonctionne avec JWT admin

        response = client.delete(
            "/api/entities/fake-uuid",
            headers=admin_headers
        )

        # 404 attendu car entité n'existe pas (mais auth JWT fonctionne)
        assert response.status_code == 404


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
