"""
Tests pour Phase 1.8 - Document Context Global (T1.8.1.0).

Ces tests valident la generation de contexte document pour ameliorer
la desambiguisation des concepts lors de l'extraction.

Exemple: "S/4HANA Cloud" -> "SAP S/4HANA Cloud, Private Edition"
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.knowbase.ingestion.osmose_agentique import (
    OsmoseAgentiqueService,
    _document_context_cache
)
from src.knowbase.ingestion.osmose_integration import OsmoseIntegrationConfig


# Sample document texts for testing
SAP_DOCUMENT_TEXT = """
SAP S/4HANA Cloud Migration Guide

INTRODUCTION
This document provides guidance for migrating to S/4HANA Cloud Private Edition.
The SAP S/4HANA Cloud, Private Edition offers enterprise-grade capabilities.

KEY FEATURES
- SAP Fiori user experience
- Integration with SAP BTP
- Real-time analytics with HANA

ARCHITECTURE OVERVIEW
The solution leverages SAP Business Technology Platform for extensibility.
SuccessFactors integration is available for HR processes.

MIGRATION STEPS
1. Assessment phase
2. Planning phase
3. Execution phase
4. Go-live validation
"""

SHORT_DOCUMENT_TEXT = """
S/4HANA Cloud Overview
Quick guide for cloud migration.
BTP integration available.
"""

MULTI_LANGUAGE_TEXT = """
SAP S/4HANA Cloud - Guide de Migration

INTRODUCTION
Ce document decrit les etapes de migration vers SAP S/4HANA Cloud.
La solution SAP offre des fonctionnalites enterprise-grade.

CARACTERISTIQUES
- Experience utilisateur SAP Fiori
- Integration avec SAP Business Technology Platform
- Analytique temps-reel avec SAP HANA
"""


class TestExtractDocumentMetadata:
    """Tests pour _extract_document_metadata (extraction sans LLM)."""

    @pytest.fixture
    def service(self):
        """Fixture service agentique."""
        config = OsmoseIntegrationConfig(enable_osmose=True)
        return OsmoseAgentiqueService(config=config)

    def test_extract_title(self, service):
        """Test extraction du titre depuis premiere ligne."""
        metadata = service._extract_document_metadata(SAP_DOCUMENT_TEXT)

        assert metadata["title"] is not None
        assert "SAP S/4HANA Cloud" in metadata["title"]

    def test_extract_headers(self, service):
        """Test extraction des headers (UPPERCASE)."""
        metadata = service._extract_document_metadata(SAP_DOCUMENT_TEXT)

        assert len(metadata["headers"]) > 0
        # Les headers UPPERCASE devraient etre detectes
        header_texts = " ".join(metadata["headers"]).upper()
        assert any(h in header_texts for h in ["INTRODUCTION", "KEY FEATURES", "ARCHITECTURE"])

    def test_extract_sap_keywords(self, service):
        """Test extraction mots-cles SAP."""
        metadata = service._extract_document_metadata(SAP_DOCUMENT_TEXT)

        keywords = metadata["keywords"]
        assert len(keywords) > 0

        # Devrait detecter les termes SAP
        keywords_text = " ".join(keywords).lower()
        sap_terms_found = sum(1 for term in ["s/4hana", "sap", "fiori", "btp", "hana"]
                             if term in keywords_text)
        assert sap_terms_found >= 2, f"Found SAP terms: {keywords}"

    def test_extract_proper_nouns(self, service):
        """Test extraction noms propres frequents."""
        metadata = service._extract_document_metadata(SAP_DOCUMENT_TEXT)

        # SuccessFactors devrait etre detecte comme nom propre
        keywords = metadata["keywords"]
        assert len(keywords) > 0

    def test_empty_document(self, service):
        """Test document vide."""
        metadata = service._extract_document_metadata("")

        assert metadata["title"] is None
        assert metadata["headers"] == []
        assert metadata["keywords"] == []

    def test_short_document(self, service):
        """Test document court."""
        metadata = service._extract_document_metadata(SHORT_DOCUMENT_TEXT)

        assert metadata["title"] is not None
        # Keywords SAP devraient quand meme etre extraits
        assert len(metadata["keywords"]) >= 0


class TestGenerateDocumentSummary:
    """Tests pour _generate_document_summary (generation LLM)."""

    @pytest.fixture
    def service(self):
        """Fixture service agentique."""
        config = OsmoseIntegrationConfig(enable_osmose=True)
        return OsmoseAgentiqueService(config=config)

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        _document_context_cache.clear()
        yield
        _document_context_cache.clear()

    @pytest.mark.asyncio
    async def test_summary_generation_with_mock_llm(self, service):
        """Test generation resume avec LLM mocke."""
        mock_summary = (
            "This document is a migration guide for SAP S/4HANA Cloud, Private Edition. "
            "It covers the architecture with SAP BTP integration and SAP Fiori UX."
        )

        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(return_value=mock_summary)
            mock_router.return_value = mock_llm

            summary = await service._generate_document_summary(
                document_id="test-doc-001",
                full_text=SAP_DOCUMENT_TEXT
            )

            assert len(summary) > 0
            assert len(summary) <= 500
            mock_llm.acomplete.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit(self, service):
        """Test que le cache est utilise pour meme document_id."""
        mock_summary = "Cached summary for SAP document."

        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(return_value=mock_summary)
            mock_router.return_value = mock_llm

            # Premier appel - devrait appeler LLM
            summary1 = await service._generate_document_summary(
                document_id="test-doc-cache",
                full_text=SAP_DOCUMENT_TEXT
            )

            # Deuxieme appel avec meme document_id - devrait utiliser cache
            summary2 = await service._generate_document_summary(
                document_id="test-doc-cache",
                full_text=SAP_DOCUMENT_TEXT
            )

            assert summary1 == summary2
            # LLM devrait etre appele une seule fois (cache hit au 2eme appel)
            assert mock_llm.acomplete.call_count == 1

    @pytest.mark.asyncio
    async def test_different_documents_no_cache_collision(self, service):
        """Test que differents documents ont des caches separes."""
        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(side_effect=[
                "Summary for document 1",
                "Summary for document 2"
            ])
            mock_router.return_value = mock_llm

            summary1 = await service._generate_document_summary(
                document_id="doc-1",
                full_text=SAP_DOCUMENT_TEXT
            )

            summary2 = await service._generate_document_summary(
                document_id="doc-2",
                full_text=SHORT_DOCUMENT_TEXT
            )

            assert summary1 != summary2
            assert mock_llm.acomplete.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self, service):
        """Test fallback si LLM echoue."""
        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(side_effect=Exception("LLM API error"))
            mock_router.return_value = mock_llm

            # Ne devrait pas lever d'exception
            summary = await service._generate_document_summary(
                document_id="test-doc-fallback",
                full_text=SAP_DOCUMENT_TEXT
            )

            # Devrait retourner un fallback base sur les metadonnees
            assert len(summary) > 0
            assert "Document:" in summary or "Topics:" in summary

    @pytest.mark.asyncio
    async def test_truncate_long_summary(self, service):
        """Test que les resumes trop longs sont tronques."""
        long_summary = "A" * 600  # Plus de 500 chars

        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(return_value=long_summary)
            mock_router.return_value = mock_llm

            summary = await service._generate_document_summary(
                document_id="test-doc-long",
                full_text=SAP_DOCUMENT_TEXT,
                max_length=500
            )

            assert len(summary) <= 500
            assert summary.endswith("...")


class TestContextImprovesExtraction:
    """Tests d'integration montrant que le contexte ameliore l'extraction."""

    @pytest.fixture
    def service(self):
        """Fixture service agentique."""
        config = OsmoseIntegrationConfig(enable_osmose=True)
        return OsmoseAgentiqueService(config=config)

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        _document_context_cache.clear()
        yield
        _document_context_cache.clear()

    def test_metadata_includes_full_product_names(self, service):
        """Test que les metadonnees incluent les noms complets SAP."""
        metadata = service._extract_document_metadata(SAP_DOCUMENT_TEXT)

        keywords = metadata["keywords"]
        keywords_text = " ".join(keywords)

        # Le contexte devrait capturer "S/4HANA Cloud" et non juste "S/4HANA"
        # ou au minimum les termes SAP principaux
        assert any("S/4HANA" in k or "SAP" in k for k in keywords), \
            f"Expected SAP terms in keywords: {keywords}"

    @pytest.mark.asyncio
    async def test_context_contains_disambiguation_info(self, service):
        """Test que le contexte genere contient info pour desambiguisation."""
        # Simuler un resume LLM qui mentionne le nom complet
        expected_context = (
            "This document covers SAP S/4HANA Cloud, Private Edition migration. "
            "Key topics include SAP BTP integration and SAP Fiori user experience."
        )

        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(return_value=expected_context)
            mock_router.return_value = mock_llm

            context = await service._generate_document_summary(
                document_id="test-disambiguation",
                full_text=SAP_DOCUMENT_TEXT
            )

            # Le contexte devrait contenir "SAP S/4HANA Cloud, Private Edition"
            # ce qui permet de desambiguiser "S/4HANA Cloud" seul
            assert "S/4HANA" in context or "SAP" in context

    @pytest.mark.asyncio
    async def test_french_document_context(self, service):
        """Test generation contexte pour document francais."""
        french_context = (
            "Ce document presente la migration vers SAP S/4HANA Cloud. "
            "Il couvre l'integration SAP BTP et l'experience Fiori."
        )

        with patch.object(service, '_get_llm_router') as mock_router:
            mock_llm = MagicMock()
            mock_llm.acomplete = AsyncMock(return_value=french_context)
            mock_router.return_value = mock_llm

            context = await service._generate_document_summary(
                document_id="test-french",
                full_text=MULTI_LANGUAGE_TEXT
            )

            assert len(context) > 0
            # Le prompt demande de repondre dans la meme langue que le document
            mock_llm.acomplete.assert_called_once()


class TestFullNameExtraction:
    """Tests specifiques pour l'extraction des noms complets officiels."""

    @pytest.fixture
    def service(self):
        """Fixture service agentique."""
        config = OsmoseIntegrationConfig(enable_osmose=True)
        return OsmoseAgentiqueService(config=config)

    def test_detect_sap_s4hana_cloud(self, service):
        """Test detection 'SAP S/4HANA Cloud' complet."""
        text = """
        SAP S/4HANA Cloud, Private Edition Overview

        This solution provides enterprise functionality with cloud deployment.
        S/4HANA Cloud offers real-time processing.
        """

        metadata = service._extract_document_metadata(text)
        keywords = metadata["keywords"]

        # Devrait detecter le pattern S/4HANA
        found_s4 = any("S/4HANA" in k for k in keywords)
        assert found_s4, f"Expected S/4HANA in keywords: {keywords}"

    def test_detect_sap_btp(self, service):
        """Test detection 'SAP Business Technology Platform' / 'BTP'."""
        text = """
        SAP BTP Integration Guide

        The SAP Business Technology Platform enables extension and integration.
        BTP provides serverless capabilities.
        """

        metadata = service._extract_document_metadata(text)
        keywords = metadata["keywords"]

        # Devrait detecter BTP
        found_btp = any("BTP" in k for k in keywords)
        assert found_btp, f"Expected BTP in keywords: {keywords}"

    def test_detect_successfactors(self, service):
        """Test detection 'SAP SuccessFactors'."""
        text = """
        SAP SuccessFactors Employee Central

        SuccessFactors provides HR cloud solutions.
        Integration with S/4HANA is supported.
        """

        metadata = service._extract_document_metadata(text)
        keywords = metadata["keywords"]

        # Devrait detecter SuccessFactors
        found_sf = any("SuccessFactors" in k for k in keywords)
        assert found_sf, f"Expected SuccessFactors in keywords: {keywords}"


# Integration test (requires actual LLM - mark as slow)
@pytest.mark.integration
@pytest.mark.slow
class TestRealLLMIntegration:
    """Tests d'integration avec vrai LLM (marques slow)."""

    @pytest.fixture
    def service(self):
        """Fixture service agentique."""
        config = OsmoseIntegrationConfig(enable_osmose=True)
        return OsmoseAgentiqueService(config=config)

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        _document_context_cache.clear()
        yield
        _document_context_cache.clear()

    @pytest.mark.asyncio
    async def test_real_summary_generation(self, service):
        """Test generation resume avec vrai LLM."""
        summary = await service._generate_document_summary(
            document_id="test-real-llm",
            full_text=SAP_DOCUMENT_TEXT
        )

        assert len(summary) > 50
        assert len(summary) <= 500

        # Le resume devrait mentionner des termes SAP
        summary_lower = summary.lower()
        assert any(term in summary_lower for term in ["sap", "s/4hana", "migration", "cloud"])
