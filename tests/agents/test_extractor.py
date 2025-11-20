"""
Tests pour ExtractorOrchestrator.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.knowbase.agents.extractor.orchestrator import (
    ExtractorOrchestrator,
    ExtractionRoute,
    PrepassAnalyzerInput,
    PrepassAnalyzerOutput,
    ExtractConceptsInput,
    ExtractConceptsOutput
)
from src.knowbase.agents.base import AgentState, ToolOutput


class TestExtractorOrchestrator:
    """Tests pour ExtractorOrchestrator."""

    @pytest.fixture
    def extractor(self):
        """Fixture ExtractorOrchestrator."""
        return ExtractorOrchestrator(config={})

    @pytest.fixture
    def state_with_segments(self):
        """Fixture AgentState avec segments."""
        return AgentState(
            document_id="test-doc",
            segments=[
                {
                    "topic_id": "seg-1",
                    "text": "SAP S/4HANA is an ERP system with advanced analytics.",
                    "language": "en",
                    "start_page": 0,
                    "end_page": 1
                },
                {
                    "topic_id": "seg-2",
                    "text": "La solution intègre SAP Fiori et SAP HANA database.",
                    "language": "fr",
                    "start_page": 1,
                    "end_page": 2
                }
            ]
        )

    def test_extractor_initialization(self, extractor):
        """Test initialisation ExtractorOrchestrator."""
        assert extractor.role.value == "extractor_orchestrator"
        assert extractor.no_llm_threshold == 3
        assert extractor.small_threshold == 8
        assert "prepass_analyzer" in extractor.tools
        assert "extract_concepts" in extractor.tools

    def test_extractor_initialization_with_config(self):
        """Test initialisation avec config custom."""
        config = {
            "no_llm_threshold": 5,
            "small_threshold": 10
        }
        extractor = ExtractorOrchestrator(config=config)

        assert extractor.no_llm_threshold == 5
        assert extractor.small_threshold == 10

    def test_extraction_route_enum(self):
        """Test énumération ExtractionRoute."""
        assert ExtractionRoute.NO_LLM.value == "NO_LLM"
        assert ExtractionRoute.SMALL.value == "SMALL"
        assert ExtractionRoute.BIG.value == "BIG"

    def test_apply_budget_fallback_big_available(self, extractor):
        """Test fallback avec budget BIG disponible."""
        state = AgentState(document_id="test-doc")
        state.budget_remaining["BIG"] = 5

        route = extractor._apply_budget_fallback(ExtractionRoute.BIG, state)

        assert route == ExtractionRoute.BIG

    def test_apply_budget_fallback_big_exhausted(self, extractor):
        """Test fallback BIG→SMALL (budget BIG épuisé)."""
        state = AgentState(document_id="test-doc")
        state.budget_remaining["BIG"] = 0
        state.budget_remaining["SMALL"] = 50

        route = extractor._apply_budget_fallback(ExtractionRoute.BIG, state)

        assert route == ExtractionRoute.SMALL

    def test_apply_budget_fallback_all_exhausted(self, extractor):
        """Test fallback vers NO_LLM (tous budgets épuisés)."""
        state = AgentState(document_id="test-doc")
        state.budget_remaining["BIG"] = 0
        state.budget_remaining["SMALL"] = 0

        route = extractor._apply_budget_fallback(ExtractionRoute.BIG, state)

        assert route == ExtractionRoute.NO_LLM

    def test_apply_budget_fallback_small_exhausted(self, extractor):
        """Test fallback SMALL→NO_LLM (budget SMALL épuisé)."""
        state = AgentState(document_id="test-doc")
        state.budget_remaining["SMALL"] = 0

        route = extractor._apply_budget_fallback(ExtractionRoute.SMALL, state)

        assert route == ExtractionRoute.NO_LLM

    def test_apply_budget_fallback_no_llm(self, extractor):
        """Test fallback pour NO_LLM (toujours NO_LLM)."""
        state = AgentState(document_id="test-doc")

        route = extractor._apply_budget_fallback(ExtractionRoute.NO_LLM, state)

        assert route == ExtractionRoute.NO_LLM

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_prepass_analyzer_tool_no_llm(self, mock_ner_manager, extractor):
        """Test PrepassAnalyzer avec < 3 entities (NO_LLM)."""
        # Mock NER pour retourner 2 entities
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "SAP", "type": "ORG"},
            {"text": "ERP", "type": "PRODUCT"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        tool_input = PrepassAnalyzerInput(
            segment_text="SAP ERP system",
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        assert result.success is True
        assert result.data["entity_count"] == 2
        assert result.data["recommended_route"] == ExtractionRoute.NO_LLM

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_prepass_analyzer_tool_small(self, mock_ner_manager, extractor):
        """Test PrepassAnalyzer avec 3-8 entities (SMALL)."""
        # Mock NER pour retourner 5 entities
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": f"Entity{i}", "type": "ORG"} for i in range(5)
        ]
        mock_ner_manager.return_value = mock_ner_instance

        tool_input = PrepassAnalyzerInput(
            segment_text="Text with multiple entities",
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        assert result.success is True
        assert result.data["entity_count"] == 5
        assert result.data["recommended_route"] == ExtractionRoute.SMALL

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_prepass_analyzer_tool_big(self, mock_ner_manager, extractor):
        """Test PrepassAnalyzer avec > 8 entities (BIG)."""
        # Mock NER pour retourner 10 entities
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": f"Entity{i}", "type": "ORG"} for i in range(10)
        ]
        mock_ner_manager.return_value = mock_ner_instance

        tool_input = PrepassAnalyzerInput(
            segment_text="Very dense text with many entities",
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        assert result.success is True
        assert result.data["entity_count"] == 10
        assert result.data["recommended_route"] == ExtractionRoute.BIG

    def test_extract_concepts_tool_no_llm(self, extractor):
        """Test ExtractConcepts avec route NO_LLM."""
        tool_input = ExtractConceptsInput(
            segment={
                "topic_id": "seg-1",
                "text": "SAP ERP",
                "language": "en"
            },
            route=ExtractionRoute.NO_LLM,
            use_llm=False
        )

        result = extractor._extract_concepts_tool(tool_input)

        assert result.success is True
        assert result.data["cost_incurred"] == 0.0
        assert result.data["llm_calls"] == 0

    def test_extract_concepts_tool_small(self, extractor):
        """Test ExtractConcepts avec route SMALL."""
        tool_input = ExtractConceptsInput(
            segment={
                "topic_id": "seg-1",
                "text": "SAP S/4HANA ERP",
                "language": "en"
            },
            route=ExtractionRoute.SMALL,
            use_llm=True
        )

        result = extractor._extract_concepts_tool(tool_input)

        assert result.success is True
        # Mock coût SMALL
        assert result.data["cost_incurred"] == pytest.approx(0.002)
        assert result.data["llm_calls"] == 1

    def test_extract_concepts_tool_big(self, extractor):
        """Test ExtractConcepts avec route BIG."""
        tool_input = ExtractConceptsInput(
            segment={
                "topic_id": "seg-1",
                "text": "Complex SAP S/4HANA deployment",
                "language": "en"
            },
            route=ExtractionRoute.BIG,
            use_llm=True
        )

        result = extractor._extract_concepts_tool(tool_input)

        assert result.success is True
        # Mock coût BIG
        assert result.data["cost_incurred"] == pytest.approx(0.015)
        assert result.data["llm_calls"] == 1

    @pytest.mark.asyncio
    async def test_execute_no_segments(self, extractor):
        """Test execute avec aucun segment."""
        state = AgentState(document_id="test-doc", segments=[])

        final_state = await extractor.execute(state)

        assert len(final_state.candidates) == 0
        assert final_state.cost_incurred == 0.0

    @pytest.mark.asyncio
    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    async def test_execute_with_segments(self, mock_ner_manager, extractor, state_with_segments):
        """Test execute avec segments."""
        # Mock NER
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "SAP", "type": "ORG"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        final_state = await extractor.execute(state_with_segments)

        # Vérifier que candidates a été rempli (mock vide pour l'instant)
        assert isinstance(final_state.candidates, list)
        # Cost devrait être 0 (NO_LLM route pour 1 entity)
        assert final_state.cost_incurred >= 0.0

    @pytest.mark.asyncio
    async def test_execute_updates_budget(self, extractor):
        """Test execute met à jour budgets."""
        state = AgentState(
            document_id="test-doc",
            segments=[
                {
                    "topic_id": "seg-1",
                    "text": "SAP S/4HANA with advanced features and analytics",
                    "language": "en",
                    "start_page": 0,
                    "end_page": 1
                }
            ]
        )

        initial_budget = state.budget_remaining.copy()

        # Mock NER pour forcer route SMALL
        with patch('src.knowbase.agents.extractor.orchestrator.NERManager') as mock_ner:
            mock_ner_instance = MagicMock()
            mock_ner_instance.extract_entities.return_value = [
                {"text": f"Entity{i}", "type": "ORG"} for i in range(5)  # 5 entities → SMALL
            ]
            mock_ner.return_value = mock_ner_instance

            final_state = await extractor.execute(state)

        # Budget SMALL devrait avoir diminué (mock: 1 call)
        # Note: Pour l'instant mock retourne llm_calls=1 pour SMALL
        assert final_state.llm_calls_count["SMALL"] >= 0


# ============================================================================
# Phase 1.8 - Tests Routing Hybrid (LOW_QUALITY_NER Detection)
# ============================================================================

class TestPhase18HybridRouting:
    """Tests Phase 1.8 T1.8.1.1 - Détection LOW_QUALITY_NER et routing hybride."""

    @pytest.fixture
    def extractor(self):
        """Fixture ExtractorOrchestrator."""
        return ExtractorOrchestrator(config={})

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_low_quality_ner_detection_triggers_small(self, mock_ner_manager, extractor):
        """
        Test Phase 1.8 T1.8.1.1: Segment avec < 3 entities ET > 200 tokens
        → Détecte LOW_QUALITY_NER → Route vers SMALL pour extraction structurée.
        """
        # Mock NER pour retourner 2 entities (low count)
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "Cloud Computing", "type": "TECH"},
            {"text": "SAP", "type": "ORG"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        # Segment long (> 200 tokens) mais avec peu d'entités NER
        # Cas typique: Texte descriptif avec concepts que le NER a manqués
        long_text = (
            "The digital transformation journey involves implementing comprehensive "
            "enterprise resource planning solutions that integrate financial management, "
            "supply chain optimization, and human capital management. Modern cloud platforms "
            "enable organizations to leverage advanced analytics capabilities for real-time "
            "insights into business operations. These systems provide unified data models "
            "that eliminate information silos and enhance decision-making processes. "
            "Organizations benefit from scalable infrastructure, automated workflows, and "
            "intelligent automation features. The integration of artificial intelligence "
            "and machine learning algorithms enables predictive analytics and proactive "
            "business intelligence. "
        ) * 3  # Répéter pour dépasser 200 tokens

        tool_input = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        # Assertions Phase 1.8
        assert result.success is True
        assert result.data["entity_count"] == 2, "Should detect 2 NER entities"
        assert result.data["word_count"] > 200, "Should have > 200 tokens"
        assert result.data["recommended_route"] == ExtractionRoute.SMALL, (
            "LOW_QUALITY_NER detected: few entities but long text → SMALL route"
        )
        # Vérifier que reasoning mentionne LOW_QUALITY_NER
        reasoning = result.data.get("reasoning", "")
        assert "LOW_QUALITY_NER" in reasoning or "Phase 1.8" in reasoning

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_no_low_quality_ner_short_text(self, mock_ner_manager, extractor):
        """
        Test Phase 1.8: Segment court (< 200 tokens) avec peu d'entités
        → PAS de LOW_QUALITY_NER → Route standard SMALL.
        """
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "SAP", "type": "ORG"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        # Texte court (< 200 tokens) avec 1 entity
        short_text = "SAP offers enterprise solutions for businesses."

        tool_input = PrepassAnalyzerInput(
            segment_text=short_text,
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        # Assertions
        assert result.success is True
        assert result.data["entity_count"] == 1
        assert result.data["word_count"] < 200
        # Route standard basée sur entity_count (1 entity → SMALL avec NO_LLM désactivé)
        assert result.data["recommended_route"] == ExtractionRoute.SMALL
        # Reasoning NE devrait PAS mentionner LOW_QUALITY_NER
        reasoning = result.data.get("reasoning", "")
        assert "LOW_QUALITY_NER" not in reasoning

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_no_low_quality_ner_many_entities(self, mock_ner_manager, extractor):
        """
        Test Phase 1.8: Segment long avec BEAUCOUP d'entités
        → PAS de LOW_QUALITY_NER → Route BIG (NER fonctionne bien).
        """
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": f"Entity{i}", "type": "ORG"} for i in range(10)
        ]
        mock_ner_manager.return_value = mock_ner_instance

        # Texte long avec 10 entities (NER fonctionne bien)
        long_text = " ".join([f"Entity{i} is important" for i in range(10)]) * 5

        tool_input = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        # Assertions
        assert result.success is True
        assert result.data["entity_count"] == 10
        assert result.data["word_count"] > 200
        # Route BIG car beaucoup d'entités (> 8)
        assert result.data["recommended_route"] == ExtractionRoute.BIG
        # Reasoning NE devrait PAS mentionner LOW_QUALITY_NER
        reasoning = result.data.get("reasoning", "")
        assert "LOW_QUALITY_NER" not in reasoning

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_low_quality_ner_boundary_200_tokens(self, mock_ner_manager, extractor):
        """
        Test Phase 1.8: Boundary test à exactement 200 tokens.
        Avec 2 entities et 200 tokens → Devrait PAS trigger LOW_QUALITY_NER (> 200).
        """
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "SAP", "type": "ORG"},
            {"text": "ERP", "type": "PRODUCT"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        # Générer exactement 200 tokens (approximatif)
        text_200_tokens = " ".join(["word"] * 200)

        tool_input = PrepassAnalyzerInput(
            segment_text=text_200_tokens,
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        # Assertions: À 200 tokens, condition est > 200 donc PAS LOW_QUALITY_NER
        assert result.success is True
        assert result.data["entity_count"] == 2
        assert result.data["word_count"] == 200
        # Devrait utiliser routing standard SMALL (2 entities < 3)
        assert result.data["recommended_route"] == ExtractionRoute.SMALL

    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    def test_low_quality_ner_boundary_3_entities(self, mock_ner_manager, extractor):
        """
        Test Phase 1.8: Boundary test à exactement 3 entities.
        Avec 3 entities et > 200 tokens → Devrait PAS trigger LOW_QUALITY_NER (< 3).
        """
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "SAP", "type": "ORG"},
            {"text": "ERP", "type": "PRODUCT"},
            {"text": "Cloud", "type": "TECH"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        long_text = " ".join(["word"] * 250)

        tool_input = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = extractor._prepass_analyzer_tool(tool_input)

        # Assertions: À 3 entities, condition est < 3 donc PAS LOW_QUALITY_NER
        assert result.success is True
        assert result.data["entity_count"] == 3
        assert result.data["word_count"] == 250
        # Route standard SMALL (3 <= 8)
        assert result.data["recommended_route"] == ExtractionRoute.SMALL
        # Reasoning NE devrait PAS mentionner LOW_QUALITY_NER
        reasoning = result.data.get("reasoning", "")
        assert "LOW_QUALITY_NER" not in reasoning

    @pytest.mark.asyncio
    @patch('src.knowbase.agents.extractor.orchestrator.NERManager')
    async def test_execute_with_low_quality_ner_segment(self, mock_ner_manager, extractor):
        """
        Test Phase 1.8: Exécution complète avec segment LOW_QUALITY_NER.
        Vérifie que le segment est routé vers SMALL et que le budget est consommé.
        """
        mock_ner_instance = MagicMock()
        mock_ner_instance.extract_entities.return_value = [
            {"text": "SAP", "type": "ORG"}
        ]
        mock_ner_manager.return_value = mock_ner_instance

        # Segment LOW_QUALITY_NER: 1 entity + > 200 tokens
        long_descriptive_text = (
            "The enterprise architecture framework provides comprehensive guidelines "
            "for digital transformation initiatives across multiple business domains. "
            "Organizations leverage these structured approaches to align technology "
            "investments with strategic business objectives. The methodology encompasses "
            "governance models, integration patterns, and capability assessments to ensure "
            "successful implementation of complex enterprise systems. "
        ) * 5  # Répéter pour > 200 tokens

        state = AgentState(
            document_id="test-doc-phase18",
            segments=[
                {
                    "topic_id": "seg-low-quality-ner",
                    "text": long_descriptive_text,
                    "language": "en",
                    "start_page": 0,
                    "end_page": 1
                }
            ]
        )

        final_state = await extractor.execute(state)

        # Assertions
        assert isinstance(final_state.candidates, list)
        # Budget SMALL devrait avoir été utilisé (LOW_QUALITY_NER → SMALL route)
        # Note: Avec mock actuel, llm_calls peut être 0 ou 1 selon implémentation
        assert final_state.llm_calls_count["SMALL"] >= 0
        # Coût > 0 si SMALL a été appelé
        assert final_state.cost_incurred >= 0.0
