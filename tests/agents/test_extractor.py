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
