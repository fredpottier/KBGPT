"""
Tests extraction facts depuis slides PPTX.

Teste extraction LLM Vision, validation Pydantic, insertion Neo4j,
détection conflits.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, AsyncMock
import json

from knowbase.api.schemas.facts import FactCreate, FactType, ValueType


class TestFactsExtraction:
    """Tests extraction facts depuis slides."""

    @pytest.mark.asyncio
    @patch("knowbase.ingestion.facts_extractor.LLMRouter")
    async def test_extract_facts_from_slide_success(self, mock_llm_class):
        """Test extraction facts réussie depuis slide avec texte + image."""
        from knowbase.ingestion.facts_extractor import extract_facts_from_slide

        # Mock LLM response
        mock_llm = Mock()
        mock_llm_class.return_value = mock_llm

        llm_response = {
            "content": json.dumps({
                "facts": [
                    {
                        "subject": "SAP S/4HANA Cloud",
                        "predicate": "SLA_uptime_garantie",
                        "object": "99.7%",
                        "value": 99.7,
                        "unit": "%",
                        "value_type": "numeric",
                        "fact_type": "SERVICE_LEVEL",
                        "confidence": 0.95,
                        "valid_from": "2024-01-01",
                        "source_slide_number": 5,
                        "extraction_context": "Tableau SLA slide 5",
                        "source_type": "both"
                    }
                ]
            }),
            "model": "gpt-4-vision-preview"
        }

        mock_llm.route = AsyncMock(return_value=llm_response)

        # Données slide
        slide_data = {
            "slide_index": 5,
            "text": "SAP S/4HANA Cloud garantit 99.7% SLA",
            "notes": "SLA contractuel",
            "megaparse_content": "SAP S/4HANA Cloud | SLA: 99.7%"
        }

        # Extraction
        facts = await extract_facts_from_slide(
            slide_data=slide_data,
            slide_image_base64="fake_base64_image",
            source_document="proposal_2024.pptx",
            chunk_id="chunk-123",
            deck_summary="Présentation SAP Cloud",
            llm_router=mock_llm,
        )

        # Assertions
        assert len(facts) == 1
        fact = facts[0]

        assert fact.subject == "SAP S/4HANA Cloud"
        assert fact.predicate == "SLA_uptime_garantie"
        assert fact.value == 99.7
        assert fact.unit == "%"
        assert fact.fact_type == FactType.SERVICE_LEVEL
        assert fact.confidence == 0.95
        assert fact.source_chunk_id == "chunk-123"
        assert fact.source_document == "proposal_2024.pptx"
        assert fact.extraction_method == "llm_vision"

    @pytest.mark.asyncio
    @patch("knowbase.ingestion.facts_extractor.LLMRouter")
    async def test_extract_facts_no_facts_found(self, mock_llm_class):
        """Test slide sans facts mesurables (vague/générique)."""
        from knowbase.ingestion.facts_extractor import extract_facts_from_slide

        mock_llm = Mock()
        mock_llm_class.return_value = mock_llm

        # LLM retourne facts vides
        llm_response = {
            "content": json.dumps({"facts": []}),
            "model": "gpt-4-vision-preview"
        }

        mock_llm.route = AsyncMock(return_value=llm_response)

        slide_data = {
            "slide_index": 1,
            "text": "Introduction à SAP",
            "notes": "",
            "megaparse_content": "Titre: Introduction"
        }

        facts = await extract_facts_from_slide(
            slide_data=slide_data,
            slide_image_base64=None,
            source_document="intro.pptx",
            chunk_id="chunk-intro",
        )

        assert len(facts) == 0

    @pytest.mark.asyncio
    @patch("knowbase.ingestion.facts_extractor.LLMRouter")
    async def test_extract_facts_invalid_json(self, mock_llm_class):
        """Test gestion JSON invalide LLM."""
        from knowbase.ingestion.facts_extractor import extract_facts_from_slide

        mock_llm = Mock()
        mock_llm_class.return_value = mock_llm

        # JSON malformé
        llm_response = {
            "content": "This is not JSON",
            "model": "gpt-4-vision-preview"
        }

        mock_llm.route = AsyncMock(return_value=llm_response)

        slide_data = {
            "slide_index": 3,
            "text": "Test",
            "notes": "",
            "megaparse_content": "Test"
        }

        facts = await extract_facts_from_slide(
            slide_data=slide_data,
            slide_image_base64=None,
            source_document="test.pptx",
            chunk_id="chunk-test",
        )

        # Doit retourner liste vide en cas d'erreur
        assert len(facts) == 0

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
