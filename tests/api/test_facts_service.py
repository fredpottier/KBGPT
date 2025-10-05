"""
Tests pour FactsService.

Teste création, lecture, mise à jour, suppression, gouvernance,
détection conflits, timeline, et gestion erreurs.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from knowbase.api.services.facts_service import (
    FactsService,
    FactsServiceError,
    FactNotFoundError,
    FactValidationError,
)
from knowbase.api.schemas.facts import (
    FactCreate,
    FactUpdate,
    FactStatus,
    FactType,
    ValueType,
)


@pytest.fixture
def facts_service(mock_facts_queries: Mock) -> FactsService:
    """Instance FactsService avec mock Neo4j."""
    with patch("knowbase.api.services.facts_service.get_neo4j_client") as mock_client:
        mock_client.return_value = Mock()
        service = FactsService(tenant_id="test_tenant")
        service.facts_queries = mock_facts_queries
        return service


class TestFactsServiceCreate:
    """Tests création facts."""

    def test_create_fact_success(self, facts_service: FactsService, mock_facts_queries: Mock, sample_fact_create):
        """Test création fact valide."""
        mock_facts_queries.create_fact.return_value = mock_facts_queries.default_fact

        fact_data = FactCreate(**sample_fact_create)
        result = facts_service.create_fact(fact_data)

        assert result.uuid == "fact-uuid-123"
        assert result.subject == "SAP S/4HANA Cloud"
        assert result.value == 99.7
        assert result.status == "proposed"
        mock_facts_queries.create_fact.assert_called_once()

    def test_create_fact_invalid_date_range(self, facts_service: FactsService, sample_fact_create):
        """Test création avec valid_until avant valid_from."""
        sample_fact_create["valid_from"] = "2024-12-31T00:00:00"
        sample_fact_create["valid_until"] = "2024-01-01T00:00:00"

        fact_data = FactCreate(**sample_fact_create)

        with pytest.raises(FactValidationError, match="valid_until must be after valid_from"):
            facts_service.create_fact(fact_data)

    def test_create_fact_negative_confidence(self, facts_service: FactsService, sample_fact_create):
        """Test création avec confidence invalide."""
        sample_fact_create["confidence"] = -0.5

        with pytest.raises(ValueError):  # Pydantic validation
            FactCreate(**sample_fact_create)

    def test_create_fact_missing_required_fields(self):
        """Test création sans champs requis."""
        with pytest.raises(ValueError):
            FactCreate(subject="Test")  # Manque predicate, object, value, unit


class TestFactsServiceRead:
    """Tests lecture facts."""

    def test_get_fact_success(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test récupération fact existant."""
        mock_facts_queries.get_fact.return_value = mock_facts_queries.default_fact

        result = facts_service.get_fact("fact-uuid-123")

        assert result.uuid == "fact-uuid-123"
        assert result.subject == "SAP S/4HANA Cloud"
        mock_facts_queries.get_fact.assert_called_once_with("fact-uuid-123")

    def test_get_fact_not_found(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test récupération fact inexistant."""
        mock_facts_queries.get_fact.return_value = None

        with pytest.raises(FactNotFoundError, match="Fact not found: nonexistent-uuid"):
            facts_service.get_fact("nonexistent-uuid")

    def test_list_facts_all(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test liste tous les facts."""
        mock_facts_queries.list_facts.return_value = [
            mock_facts_queries.default_fact,
            {**mock_facts_queries.default_fact, "uuid": "fact-uuid-456"}
        ]

        result = facts_service.list_facts()

        assert len(result) == 2
        assert result[0].uuid == "fact-uuid-123"
        assert result[1].uuid == "fact-uuid-456"
        mock_facts_queries.list_facts.assert_called_once_with(status=None, fact_type=None, limit=100, offset=0)

    def test_list_facts_with_filters(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test liste avec filtres status et type."""
        mock_facts_queries.list_facts.return_value = [mock_facts_queries.default_fact]

        result = facts_service.list_facts(status=FactStatus.APPROVED, fact_type=FactType.SERVICE_LEVEL, limit=50)

        assert len(result) == 1
        mock_facts_queries.list_facts.assert_called_once_with(
            status="approved",
            fact_type="SERVICE_LEVEL",
            limit=50,
            offset=0
        )

    def test_list_facts_pagination(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test pagination."""
        mock_facts_queries.list_facts.return_value = []

        facts_service.list_facts(limit=20, offset=40)

        mock_facts_queries.list_facts.assert_called_once_with(
            status=None,
            fact_type=None,
            limit=20,
            offset=40
        )


class TestFactsServiceUpdate:
    """Tests mise à jour facts."""

    def test_update_fact_success(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test mise à jour fact."""
        mock_facts_queries.get_fact.return_value = mock_facts_queries.default_fact
        updated_fact = {**mock_facts_queries.default_fact, "confidence": 0.98}
        mock_facts_queries.update_fact.return_value = updated_fact

        update_data = FactUpdate(confidence=0.98)
        result = facts_service.update_fact("fact-uuid-123", update_data)

        assert result.confidence == 0.98
        mock_facts_queries.update_fact.assert_called_once()

    def test_update_fact_not_found(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test mise à jour fact inexistant."""
        mock_facts_queries.get_fact.return_value = None

        update_data = FactUpdate(confidence=0.98)

        with pytest.raises(FactNotFoundError):
            facts_service.update_fact("nonexistent-uuid", update_data)

    def test_update_fact_status_change(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test changement statut."""
        mock_facts_queries.get_fact.return_value = mock_facts_queries.default_fact
        updated_fact = {**mock_facts_queries.default_fact, "status": "approved"}
        mock_facts_queries.update_fact.return_value = updated_fact

        update_data = FactUpdate(status=FactStatus.APPROVED)
        result = facts_service.update_fact("fact-uuid-123", update_data)

        assert result.status == "approved"


class TestFactsServiceDelete:
    """Tests suppression facts."""

    def test_delete_fact_success(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test suppression fact."""
        mock_facts_queries.get_fact.return_value = mock_facts_queries.default_fact
        mock_facts_queries.delete_fact.return_value = True

        result = facts_service.delete_fact("fact-uuid-123")

        assert result is True
        mock_facts_queries.delete_fact.assert_called_once_with("fact-uuid-123")

    def test_delete_fact_not_found(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test suppression fact inexistant."""
        mock_facts_queries.get_fact.return_value = None

        with pytest.raises(FactNotFoundError):
            facts_service.delete_fact("nonexistent-uuid")


class TestFactsServiceGovernance:
    """Tests gouvernance (approve/reject)."""

    def test_approve_fact_success(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test approbation fact proposed."""
        proposed_fact = {**mock_facts_queries.default_fact, "status": "proposed"}
        approved_fact = {
            **proposed_fact,
            "status": "approved",
            "approved_by": "expert@example.com",
            "approved_at": datetime.now().isoformat()
        }
        mock_facts_queries.get_fact.return_value = proposed_fact
        mock_facts_queries.approve_fact.return_value = approved_fact

        result = facts_service.approve_fact("fact-uuid-123", "expert@example.com", "Looks good")

        assert result.status == "approved"
        assert result.approved_by == "expert@example.com"
        mock_facts_queries.approve_fact.assert_called_once_with(
            "fact-uuid-123",
            "expert@example.com",
            "Looks good"
        )

    def test_approve_fact_already_approved(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test approbation fact déjà approved."""
        approved_fact = {**mock_facts_queries.default_fact, "status": "approved"}
        mock_facts_queries.get_fact.return_value = approved_fact

        with pytest.raises(FactValidationError, match="Cannot approve non-proposed fact"):
            facts_service.approve_fact("fact-uuid-123", "expert@example.com", None)

    def test_reject_fact_success(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test rejet fact proposed."""
        proposed_fact = {**mock_facts_queries.default_fact, "status": "proposed"}
        rejected_fact = {**proposed_fact, "status": "rejected"}
        mock_facts_queries.get_fact.return_value = proposed_fact
        mock_facts_queries.reject_fact.return_value = rejected_fact

        result = facts_service.reject_fact("fact-uuid-123", "expert@example.com", "Incorrect value", "Source outdated")

        assert result.status == "rejected"
        mock_facts_queries.reject_fact.assert_called_once_with(
            "fact-uuid-123",
            "expert@example.com",
            "Incorrect value",
            "Source outdated"
        )

    def test_reject_fact_already_rejected(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test rejet fact déjà rejected."""
        rejected_fact = {**mock_facts_queries.default_fact, "status": "rejected"}
        mock_facts_queries.get_fact.return_value = rejected_fact

        with pytest.raises(FactValidationError, match="Cannot reject non-proposed fact"):
            facts_service.reject_fact("fact-uuid-123", "expert@example.com", "reason", None)


class TestFactsServiceConflicts:
    """Tests détection conflits."""

    def test_detect_conflicts_found(self, facts_service: FactsService, mock_facts_queries: Mock, sample_conflict):
        """Test détection conflits existants."""
        mock_facts_queries.detect_conflicts.return_value = [sample_conflict]

        result = facts_service.detect_conflicts()

        assert len(result) == 1
        assert result[0].conflict_type == "CONTRADICTS"
        assert result[0].value_diff_pct == 0.002
        mock_facts_queries.detect_conflicts.assert_called_once()

    def test_detect_conflicts_none(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test aucun conflit détecté."""
        mock_facts_queries.detect_conflicts.return_value = []

        result = facts_service.detect_conflicts()

        assert len(result) == 0


class TestFactsServiceTimeline:
    """Tests timeline facts."""

    def test_get_fact_timeline_success(self, facts_service: FactsService, mock_facts_queries: Mock, sample_timeline):
        """Test récupération timeline."""
        mock_facts_queries.get_fact_timeline.return_value = sample_timeline

        result = facts_service.get_fact_timeline("SAP S/4HANA Cloud", "SLA_garantie")

        assert len(result) == 2
        assert result[0].value == 99.5
        assert result[1].value == 99.7
        mock_facts_queries.get_fact_timeline.assert_called_once_with("SAP S/4HANA Cloud", "SLA_garantie")

    def test_get_fact_timeline_empty(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test timeline vide."""
        mock_facts_queries.get_fact_timeline.return_value = []

        result = facts_service.get_fact_timeline("Unknown", "unknown")

        assert len(result) == 0


class TestFactsServiceStats:
    """Tests statistiques."""

    def test_get_facts_stats_success(self, facts_service: FactsService, mock_facts_queries: Mock, sample_stats):
        """Test récupération stats."""
        mock_facts_queries.get_facts_stats.return_value = sample_stats

        result = facts_service.get_facts_stats()

        assert result.total_facts == 156
        assert result.by_status["approved"] == 120
        assert result.by_type["SERVICE_LEVEL"] == 45
        assert result.conflicts_count == 3
        mock_facts_queries.get_facts_stats.assert_called_once()

    def test_get_facts_stats_empty_db(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test stats base vide."""
        mock_facts_queries.get_facts_stats.return_value = {
            "total_facts": 0,
            "by_status": {},
            "by_type": {},
            "conflicts_count": 0,
            "latest_fact_created_at": None
        }

        result = facts_service.get_facts_stats()

        assert result.total_facts == 0
        assert result.conflicts_count == 0


class TestFactsServiceErrorHandling:
    """Tests gestion erreurs."""

    def test_neo4j_connection_error(self, facts_service: FactsService, mock_facts_queries: Mock):
        """Test erreur connexion Neo4j."""
        mock_facts_queries.get_fact.side_effect = Exception("Connection failed")

        with pytest.raises(FactsServiceError, match="Failed to get fact"):
            facts_service.get_fact("fact-uuid-123")

    def test_invalid_uuid_format(self, facts_service: FactsService):
        """Test UUID invalide."""
        # FactsService devrait tolérer n'importe quel string UUID
        # et laisser Neo4j déterminer s'il existe
        with patch.object(facts_service.facts_queries, "get_fact", return_value=None):
            with pytest.raises(FactNotFoundError):
                facts_service.get_fact("invalid-uuid")

    def test_validation_error_propagation(self, facts_service: FactsService, sample_fact_create):
        """Test propagation erreurs validation Pydantic."""
        sample_fact_create["confidence"] = 1.5  # Hors limite [0, 1]

        with pytest.raises(ValueError):
            FactCreate(**sample_fact_create)
