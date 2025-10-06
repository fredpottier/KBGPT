"""
Tests insertion facts Neo4j et détection conflits.

NOTE: L'extraction de facts se fait maintenant via le prompt unifié
(slide_default_v3_unified_facts) dans pptx_pipeline.py.
Ces tests couvrent uniquement l'insertion Neo4j et la détection de conflits.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, AsyncMock
import json

from knowbase.api.schemas.facts import FactCreate, FactType, ValueType


class TestFactsInsertion:
    """Tests insertion facts Neo4j."""

    @pytest.mark.asyncio
    @patch("knowbase.ingestion.facts_extractor.FactsService")
    async def test_insert_facts_to_neo4j_success(self, mock_service_class):
        """Test insertion facts Neo4j."""
        from knowbase.ingestion.facts_extractor import insert_facts_to_neo4j

        # Mock FactsService
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock create_fact response
        mock_response = Mock()
        mock_response.uuid = "fact-uuid-123"
        mock_service.create_fact.return_value = mock_response

        # Facts à insérer
        fact = FactCreate(
            subject="SAP BTP",
            predicate="capacite_storage_max",
            object="5 TB",
            value=5,
            unit="TB",
            fact_type=FactType.CAPACITY,
            confidence=0.9,
        )

        uuids = await insert_facts_to_neo4j([fact], tenant_id="test_tenant")

        assert len(uuids) == 1
        assert uuids[0] == "fact-uuid-123"
        mock_service.create_fact.assert_called_once()

    @pytest.mark.asyncio
    @patch("knowbase.ingestion.facts_extractor.FactsService")
    async def test_detect_conflicts_found(self, mock_service_class):
        """Test détection conflits critiques."""
        from knowbase.ingestion.facts_extractor import detect_and_log_conflicts

        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock conflict
        conflict = Mock()
        conflict.conflict_type = "CONTRADICTS"
        conflict.value_diff_pct = 0.1  # 10% différence
        conflict.fact_proposed = Mock(
            uuid="proposed-uuid",
            subject="SAP S/4HANA",
            predicate="SLA_uptime",
            value=99.5,
            unit="%"
        )
        conflict.fact_approved = Mock(
            uuid="approved-uuid",
            subject="SAP S/4HANA",
            predicate="SLA_uptime",
            value=99.7,
            unit="%"
        )

        mock_service.detect_conflicts.return_value = [conflict]

        conflicts = await detect_and_log_conflicts(
            inserted_fact_uuids=["proposed-uuid"],
            tenant_id="test_tenant",
            threshold_pct=0.05,  # 5% seuil
        )

        assert len(conflicts) == 1
        assert conflicts[0]["conflict_type"] == "CONTRADICTS"
        assert conflicts[0]["value_diff_pct"] == 0.1


class TestNotifications:
    """Tests notifications webhook conflits."""

    @pytest.mark.asyncio
    @patch("knowbase.ingestion.notifications.httpx.AsyncClient")
    async def test_notify_critical_conflicts_success(self, mock_client_class):
        """Test notification webhook envoyée."""
        from knowbase.ingestion.notifications import notify_critical_conflicts

        # Mock httpx response
        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client_class.return_value = mock_client

        conflicts = [
            {
                "conflict_type": "CONTRADICTS",
                "value_diff_pct": 0.08,  # 8%
                "fact_proposed": {
                    "uuid": "prop-123",
                    "subject": "SAP S/4HANA",
                    "predicate": "SLA",
                    "value": 99.5,
                    "unit": "%"
                },
                "fact_approved": {
                    "uuid": "app-456",
                    "subject": "SAP S/4HANA",
                    "predicate": "SLA",
                    "value": 99.7,
                    "unit": "%"
                }
            }
        ]

        result = await notify_critical_conflicts(
            conflicts=conflicts,
            webhook_url="https://hooks.slack.com/test",
            threshold_pct=0.05,
        )

        assert result is True
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_no_webhook_url(self):
        """Test skip notification si webhook URL absent."""
        from knowbase.ingestion.notifications import notify_critical_conflicts

        conflicts = [{"conflict_type": "CONTRADICTS", "value_diff_pct": 0.1}]

        result = await notify_critical_conflicts(
            conflicts=conflicts,
            webhook_url=None,  # Pas d'URL
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_notify_no_critical_conflicts(self):
        """Test skip notification si aucun conflit critique."""
        from knowbase.ingestion.notifications import notify_critical_conflicts

        # Conflits sous seuil 5%
        conflicts = [{"conflict_type": "CONTRADICTS", "value_diff_pct": 0.02}]  # 2%

        result = await notify_critical_conflicts(
            conflicts=conflicts,
            webhook_url="https://hooks.slack.com/test",
            threshold_pct=0.05,
        )

        assert result is False
