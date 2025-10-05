"""
Tests endpoints API /api/facts.

Teste tous les endpoints CRUD, gouvernance, conflits, timeline, stats
avec client FastAPI test et mocks Neo4j.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient


class TestFactsEndpointCreate:
    """Tests POST /api/facts."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_create_fact_success(self, mock_service_class, test_client: TestClient, sample_fact_create, sample_fact_response, auth_headers):
        """Test création fact valide."""
        mock_service = Mock()
        mock_service.create_fact.return_value = Mock(**sample_fact_response)
        mock_service_class.return_value = mock_service

        response = test_client.post("/api/facts", json=sample_fact_create, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["uuid"] == "fact-uuid-123"
        assert data["subject"] == "SAP S/4HANA Cloud"
        assert data["value"] == 99.7

    @patch("knowbase.api.routers.facts.FactsService")
    def test_create_fact_validation_error(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test validation Pydantic champs manquants."""
        invalid_payload = {"subject": "Test"}  # Manque predicate, object, value, unit

        response = test_client.post("/api/facts", json=invalid_payload, headers=auth_headers)

        assert response.status_code == 422  # Unprocessable Entity
        assert "detail" in response.json()

    @patch("knowbase.api.routers.facts.FactsService")
    def test_create_fact_invalid_date(self, mock_service_class, test_client: TestClient, sample_fact_create, auth_headers):
        """Test création avec date invalide."""
        sample_fact_create["valid_from"] = "invalid-date"

        response = test_client.post("/api/facts", json=sample_fact_create, headers=auth_headers)

        assert response.status_code == 422

    @patch("knowbase.api.routers.facts.FactsService")
    def test_create_fact_missing_auth_headers(self, mock_service_class, test_client: TestClient, sample_fact_create):
        """Test création sans headers auth."""
        response = test_client.post("/api/facts", json=sample_fact_create)

        # Dépend de l'implémentation dependency injection
        # Si tenant_id obligatoire, devrait échouer
        assert response.status_code in [400, 401, 422]


class TestFactsEndpointRead:
    """Tests GET /api/facts/{uuid} et GET /api/facts."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_fact_success(self, mock_service_class, test_client: TestClient, sample_fact_response, auth_headers):
        """Test récupération fact par UUID."""
        mock_service = Mock()
        mock_service.get_fact.return_value = Mock(**sample_fact_response)
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/fact-uuid-123", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["uuid"] == "fact-uuid-123"
        assert data["subject"] == "SAP S/4HANA Cloud"

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_fact_not_found(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test récupération fact inexistant."""
        from knowbase.api.services.facts_service import FactNotFoundError

        mock_service = Mock()
        mock_service.get_fact.side_effect = FactNotFoundError("Fact not found: nonexistent")
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/nonexistent-uuid", headers=auth_headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("knowbase.api.routers.facts.FactsService")
    def test_list_facts_all(self, mock_service_class, test_client: TestClient, sample_fact_response, auth_headers):
        """Test liste tous les facts."""
        mock_service = Mock()
        mock_service.list_facts.return_value = [
            Mock(**sample_fact_response),
            Mock(**{**sample_fact_response, "uuid": "fact-uuid-456"})
        ]
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["uuid"] == "fact-uuid-123"
        assert data[1]["uuid"] == "fact-uuid-456"

    @patch("knowbase.api.routers.facts.FactsService")
    def test_list_facts_with_filters(self, mock_service_class, test_client: TestClient, sample_fact_response, auth_headers):
        """Test liste avec filtres query params."""
        mock_service = Mock()
        mock_service.list_facts.return_value = [Mock(**sample_fact_response)]
        mock_service_class.return_value = mock_service

        response = test_client.get(
            "/api/facts?status=approved&fact_type=SERVICE_LEVEL&limit=50",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_service.list_facts.assert_called_once_with(
            status="approved",
            fact_type="SERVICE_LEVEL",
            limit=50,
            offset=0
        )

    @patch("knowbase.api.routers.facts.FactsService")
    def test_list_facts_pagination(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test pagination."""
        mock_service = Mock()
        mock_service.list_facts.return_value = []
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts?limit=20&offset=40", headers=auth_headers)

        assert response.status_code == 200
        mock_service.list_facts.assert_called_once_with(
            status=None,
            fact_type=None,
            limit=20,
            offset=40
        )

    @patch("knowbase.api.routers.facts.FactsService")
    def test_list_facts_limit_exceeded(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test limite max 500."""
        response = test_client.get("/api/facts?limit=1000", headers=auth_headers)

        assert response.status_code == 422  # Validation échoue (limit max 500)


class TestFactsEndpointUpdate:
    """Tests PUT /api/facts/{uuid}."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_update_fact_success(self, mock_service_class, test_client: TestClient, sample_fact_response, auth_headers):
        """Test mise à jour fact."""
        updated_fact = {**sample_fact_response, "confidence": 0.98}
        mock_service = Mock()
        mock_service.update_fact.return_value = Mock(**updated_fact)
        mock_service_class.return_value = mock_service

        update_payload = {"confidence": 0.98}
        response = test_client.put("/api/facts/fact-uuid-123", json=update_payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["confidence"] == 0.98

    @patch("knowbase.api.routers.facts.FactsService")
    def test_update_fact_not_found(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test mise à jour fact inexistant."""
        from knowbase.api.services.facts_service import FactNotFoundError

        mock_service = Mock()
        mock_service.update_fact.side_effect = FactNotFoundError("Fact not found")
        mock_service_class.return_value = mock_service

        update_payload = {"confidence": 0.98}
        response = test_client.put("/api/facts/nonexistent-uuid", json=update_payload, headers=auth_headers)

        assert response.status_code == 404

    @patch("knowbase.api.routers.facts.FactsService")
    def test_update_fact_validation_error(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test mise à jour avec données invalides."""
        invalid_payload = {"confidence": 1.5}  # Hors limite [0, 1]

        response = test_client.put("/api/facts/fact-uuid-123", json=invalid_payload, headers=auth_headers)

        assert response.status_code == 422


class TestFactsEndpointDelete:
    """Tests DELETE /api/facts/{uuid}."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_delete_fact_success(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test suppression fact."""
        mock_service = Mock()
        mock_service.delete_fact.return_value = True
        mock_service_class.return_value = mock_service

        response = test_client.delete("/api/facts/fact-uuid-123", headers=auth_headers)

        assert response.status_code == 204  # No Content

    @patch("knowbase.api.routers.facts.FactsService")
    def test_delete_fact_not_found(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test suppression fact inexistant."""
        from knowbase.api.services.facts_service import FactNotFoundError

        mock_service = Mock()
        mock_service.delete_fact.side_effect = FactNotFoundError("Fact not found")
        mock_service_class.return_value = mock_service

        response = test_client.delete("/api/facts/nonexistent-uuid", headers=auth_headers)

        assert response.status_code == 404


class TestFactsEndpointGovernance:
    """Tests POST /api/facts/{uuid}/approve et /reject."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_approve_fact_success(self, mock_service_class, test_client: TestClient, sample_fact_response, auth_headers):
        """Test approbation fact."""
        approved_fact = {
            **sample_fact_response,
            "status": "approved",
            "approved_by": "expert@example.com",
            "approved_at": datetime.now().isoformat()
        }
        mock_service = Mock()
        mock_service.approve_fact.return_value = Mock(**approved_fact)
        mock_service_class.return_value = mock_service

        payload = {"comment": "Looks good"}
        response = test_client.post("/api/facts/fact-uuid-123/approve", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["approved_by"] == "expert@example.com"

    @patch("knowbase.api.routers.facts.FactsService")
    def test_approve_fact_validation_error(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test approbation fact non-proposed."""
        from knowbase.api.services.facts_service import FactValidationError

        mock_service = Mock()
        mock_service.approve_fact.side_effect = FactValidationError("Cannot approve non-proposed fact")
        mock_service_class.return_value = mock_service

        payload = {"comment": "Approve"}
        response = test_client.post("/api/facts/fact-uuid-123/approve", json=payload, headers=auth_headers)

        assert response.status_code == 422
        assert "cannot approve" in response.json()["detail"].lower()

    @patch("knowbase.api.routers.facts.FactsService")
    def test_reject_fact_success(self, mock_service_class, test_client: TestClient, sample_fact_response, auth_headers):
        """Test rejet fact."""
        rejected_fact = {**sample_fact_response, "status": "rejected"}
        mock_service = Mock()
        mock_service.reject_fact.return_value = Mock(**rejected_fact)
        mock_service_class.return_value = mock_service

        payload = {"reason": "Incorrect value", "comment": "Source is outdated"}
        response = test_client.post("/api/facts/fact-uuid-123/reject", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

    @patch("knowbase.api.routers.facts.FactsService")
    def test_reject_fact_missing_reason(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test rejet sans raison (champ requis)."""
        payload = {"comment": "No reason provided"}

        response = test_client.post("/api/facts/fact-uuid-123/reject", json=payload, headers=auth_headers)

        assert response.status_code == 422  # Reason requis


class TestFactsEndpointConflicts:
    """Tests GET /api/facts/conflicts."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_list_conflicts_found(self, mock_service_class, test_client: TestClient, sample_conflict, auth_headers):
        """Test détection conflits."""
        mock_service = Mock()
        mock_service.detect_conflicts.return_value = [Mock(**sample_conflict)]
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/conflicts", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["conflict_type"] == "CONTRADICTS"
        assert data[0]["value_diff_pct"] == 0.002

    @patch("knowbase.api.routers.facts.FactsService")
    def test_list_conflicts_none(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test aucun conflit."""
        mock_service = Mock()
        mock_service.detect_conflicts.return_value = []
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/conflicts", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestFactsEndpointTimeline:
    """Tests GET /api/facts/timeline/{subject}/{predicate}."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_timeline_success(self, mock_service_class, test_client: TestClient, sample_timeline, auth_headers):
        """Test récupération timeline."""
        mock_service = Mock()
        mock_service.get_fact_timeline.return_value = [Mock(**t) for t in sample_timeline]
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/timeline/SAP S/4HANA Cloud/SLA_garantie", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["value"] == 99.5
        assert data[1]["value"] == 99.7

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_timeline_url_encoding(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test timeline avec caractères spéciaux encodés."""
        mock_service = Mock()
        mock_service.get_fact_timeline.return_value = []
        mock_service_class.return_value = mock_service

        # URL avec espaces encodés
        response = test_client.get("/api/facts/timeline/SAP%20S%2F4HANA/SLA_garantie", headers=auth_headers)

        assert response.status_code == 200
        mock_service.get_fact_timeline.assert_called_once_with("SAP S/4HANA", "SLA_garantie")

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_timeline_empty(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test timeline vide."""
        mock_service = Mock()
        mock_service.get_fact_timeline.return_value = []
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/timeline/Unknown/unknown", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestFactsEndpointStats:
    """Tests GET /api/facts/stats."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_stats_success(self, mock_service_class, test_client: TestClient, sample_stats, auth_headers):
        """Test récupération statistiques."""
        mock_service = Mock()
        mock_service.get_facts_stats.return_value = Mock(**sample_stats)
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/stats", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_facts"] == 156
        assert data["by_status"]["approved"] == 120
        assert data["by_type"]["SERVICE_LEVEL"] == 45
        assert data["conflicts_count"] == 3

    @patch("knowbase.api.routers.facts.FactsService")
    def test_get_stats_empty_db(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test stats base vide."""
        empty_stats = {
            "total_facts": 0,
            "by_status": {},
            "by_type": {},
            "conflicts_count": 0,
            "latest_fact_created_at": None
        }
        mock_service = Mock()
        mock_service.get_facts_stats.return_value = Mock(**empty_stats)
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/stats", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_facts"] == 0
        assert data["conflicts_count"] == 0


class TestFactsEndpointErrorHandling:
    """Tests gestion erreurs globales."""

    @patch("knowbase.api.routers.facts.FactsService")
    def test_internal_server_error(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test erreur interne (500)."""
        from knowbase.api.services.facts_service import FactsServiceError

        mock_service = Mock()
        mock_service.get_fact.side_effect = FactsServiceError("Database connection failed")
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/facts/fact-uuid-123", headers=auth_headers)

        assert response.status_code == 500
        assert "error" in response.json()["detail"].lower()

    @patch("knowbase.api.routers.facts.FactsService")
    def test_malformed_json(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test JSON malformé."""
        response = test_client.post(
            "/api/facts",
            data="not-valid-json",
            headers={**auth_headers, "Content-Type": "application/json"}
        )

        assert response.status_code == 422

    @patch("knowbase.api.routers.facts.FactsService")
    def test_method_not_allowed(self, mock_service_class, test_client: TestClient, auth_headers):
        """Test méthode HTTP non autorisée."""
        # PATCH non implémenté
        response = test_client.patch("/api/facts/fact-uuid-123", json={}, headers=auth_headers)

        assert response.status_code == 405  # Method Not Allowed
