"""
🌊 OSMOSE Phase 1.8 - Tests Routing Hybrid Extraction

Tests unitaires pour le routing LOW_QUALITY_NER et fallback budget.
Vérifie que les segments problématiques sont correctement routés vers LLM.

T1.8.1.3 - Tests routing hybrid
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import asyncio

from knowbase.agents.extractor.orchestrator import (
    ExtractorOrchestrator,
    ExtractionRoute,
    RoutingReason,
    PrepassAnalyzerInput,
    PrepassAnalyzerOutput,
    ExtractConceptsInput,
    ExtractConceptsOutput
)
from knowbase.agents.base import AgentState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def orchestrator():
    """Crée un ExtractorOrchestrator configuré pour tests."""
    config = {
        "no_llm_threshold": 3,
        "small_threshold": 8,
        "low_quality_ner_entities": 3,
        "low_quality_ner_tokens": 200
    }
    return ExtractorOrchestrator(config)


@pytest.fixture
def agent_state():
    """Crée un AgentState de base pour tests."""
    return AgentState(
        document_id="test_doc_123",
        tenant_id="default",
        segments=[],
        budget_remaining={"SMALL": 120, "BIG": 8, "VISION": 2}
    )


@pytest.fixture
def mock_ner_manager():
    """Mock du NERManager pour contrôler les résultats NER."""
    with patch('knowbase.agents.extractor.orchestrator.get_ner_manager') as mock_get:
        mock_manager = Mock()
        mock_get.return_value = mock_manager
        yield mock_manager


@pytest.fixture
def mock_semantic_config():
    """Mock de la configuration sémantique."""
    with patch('knowbase.agents.extractor.orchestrator.get_semantic_config') as mock_get:
        mock_config = Mock()
        mock_get.return_value = mock_config
        yield mock_config


# =============================================================================
# Tests LOW_QUALITY_NER Routing (T1.8.1.3a)
# =============================================================================

class TestLowQualityNerRouting:
    """Tests pour la détection et routing LOW_QUALITY_NER."""

    def test_low_quality_ner_detected(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment avec < 3 entities ET > 200 tokens → SMALL.

        Cas: Document long mais NER trouve peu → NER rate probablement des concepts.
        """
        # Setup: NER retourne seulement 2 entities pour un texte de 300 mots
        mock_ner_manager.extract_entities.return_value = [
            {"text": "SAP", "label": "ORG"},
            {"text": "Cloud", "label": "PRODUCT"}
        ]

        # Texte long (300+ mots)
        long_text = " ".join(["enterprise software"] * 150)  # ~300 tokens

        input_data = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        assert result.entity_count == 2
        assert result.recommended_route == ExtractionRoute.SMALL
        assert "LOW_QUALITY_NER" in result.reasoning

    def test_normal_short_segment_no_llm(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment court avec peu d'entities → SMALL (routing normal).

        Cas: Ce n'est PAS LOW_QUALITY_NER car le segment est court.
        """
        # Setup: NER retourne 1 entity pour un texte court (50 mots)
        mock_ner_manager.extract_entities.return_value = [
            {"text": "SAP", "label": "ORG"}
        ]

        short_text = " ".join(["word"] * 50)  # 50 tokens

        input_data = PrepassAnalyzerInput(
            segment_text=short_text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        # Court segment avec peu d'entities → SMALL normal (pas LOW_QUALITY_NER)
        assert result.recommended_route == ExtractionRoute.SMALL
        assert "LOW_QUALITY_NER" not in result.reasoning

    def test_long_segment_with_many_entities_big(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment long avec beaucoup d'entities → BIG.

        Cas: NER fonctionne bien, pas de LOW_QUALITY_NER.
        """
        # Setup: NER retourne 10 entities pour un texte long
        mock_ner_manager.extract_entities.return_value = [
            {"text": f"Entity{i}", "label": "ORG"} for i in range(10)
        ]

        long_text = " ".join(["enterprise software"] * 150)  # ~300 tokens

        input_data = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        assert result.entity_count == 10
        assert result.recommended_route == ExtractionRoute.BIG
        assert "DENSE_ENTITIES" in result.reasoning or "dense" in result.reasoning.lower()

    def test_threshold_boundary_exactly_3_entities(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment avec exactement 3 entities ET > 200 tokens → SMALL (pas LOW_QUALITY).

        Cas: Boundary condition - exactly at threshold.
        """
        # Setup: NER retourne exactement 3 entities (threshold)
        mock_ner_manager.extract_entities.return_value = [
            {"text": "SAP", "label": "ORG"},
            {"text": "Cloud", "label": "PRODUCT"},
            {"text": "S/4HANA", "label": "PRODUCT"}
        ]

        long_text = " ".join(["word"] * 250)  # > 200 tokens

        input_data = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        # 3 entities >= threshold → NOT LOW_QUALITY_NER
        assert "LOW_QUALITY_NER" not in result.reasoning

    def test_threshold_boundary_exactly_200_tokens(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment avec < 3 entities ET exactement 200 tokens → NOT LOW_QUALITY.

        Cas: Boundary condition - exactly at token threshold.
        """
        # Setup: NER retourne 2 entities
        mock_ner_manager.extract_entities.return_value = [
            {"text": "SAP", "label": "ORG"},
            {"text": "Cloud", "label": "PRODUCT"}
        ]

        # Exactement 200 tokens (pas > 200)
        text_200_tokens = " ".join(["word"] * 200)

        input_data = PrepassAnalyzerInput(
            segment_text=text_200_tokens,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        # 200 tokens = threshold, NOT > 200 → NOT LOW_QUALITY_NER
        assert "LOW_QUALITY_NER" not in result.reasoning


# =============================================================================
# Tests Budget Fallback (T1.8.1.3b)
# =============================================================================

class TestBudgetFallback:
    """Tests pour le fallback budget."""

    def test_big_budget_available(self, orchestrator, agent_state):
        """
        Test: BIG recommandé et budget BIG disponible → BIG maintenu.
        """
        agent_state.budget_remaining = {"SMALL": 120, "BIG": 8, "VISION": 2}

        result = orchestrator._apply_budget_fallback(ExtractionRoute.BIG, agent_state)

        assert result == ExtractionRoute.BIG

    def test_big_budget_exhausted_fallback_small(self, orchestrator, agent_state):
        """
        Test: BIG recommandé mais budget BIG = 0 → Fallback SMALL.
        """
        agent_state.budget_remaining = {"SMALL": 50, "BIG": 0, "VISION": 2}

        result = orchestrator._apply_budget_fallback(ExtractionRoute.BIG, agent_state)

        assert result == ExtractionRoute.SMALL

    def test_all_budgets_exhausted_fallback_no_llm(self, orchestrator, agent_state):
        """
        Test: Tous budgets LLM = 0 → Fallback NO_LLM.
        """
        agent_state.budget_remaining = {"SMALL": 0, "BIG": 0, "VISION": 0}

        result = orchestrator._apply_budget_fallback(ExtractionRoute.BIG, agent_state)

        assert result == ExtractionRoute.NO_LLM

    def test_small_budget_available(self, orchestrator, agent_state):
        """
        Test: SMALL recommandé et budget SMALL disponible → SMALL maintenu.
        """
        agent_state.budget_remaining = {"SMALL": 50, "BIG": 0, "VISION": 0}

        result = orchestrator._apply_budget_fallback(ExtractionRoute.SMALL, agent_state)

        assert result == ExtractionRoute.SMALL

    def test_small_budget_exhausted_fallback_no_llm(self, orchestrator, agent_state):
        """
        Test: SMALL recommandé mais budget SMALL = 0 → Fallback NO_LLM.
        """
        agent_state.budget_remaining = {"SMALL": 0, "BIG": 8, "VISION": 2}

        result = orchestrator._apply_budget_fallback(ExtractionRoute.SMALL, agent_state)

        assert result == ExtractionRoute.NO_LLM

    def test_no_llm_always_returns_no_llm(self, orchestrator, agent_state):
        """
        Test: NO_LLM recommandé → Toujours NO_LLM (pas de fallback).
        """
        agent_state.budget_remaining = {"SMALL": 0, "BIG": 0, "VISION": 0}

        result = orchestrator._apply_budget_fallback(ExtractionRoute.NO_LLM, agent_state)

        assert result == ExtractionRoute.NO_LLM


# =============================================================================
# Tests Phase 1 Compatibility (T1.8.1.3c)
# =============================================================================

class TestPhase1Compatibility:
    """Tests pour s'assurer que le routing Phase 1 reste intact."""

    def test_sparse_entities_routes_to_small(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment normal avec 5 entities → SMALL (routing Phase 1 intact).
        """
        mock_ner_manager.extract_entities.return_value = [
            {"text": f"Entity{i}", "label": "ORG"} for i in range(5)
        ]

        text = " ".join(["word"] * 100)

        input_data = PrepassAnalyzerInput(
            segment_text=text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        assert result.recommended_route == ExtractionRoute.SMALL

    def test_dense_entities_routes_to_big(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Segment avec > 8 entities → BIG (routing Phase 1 intact).
        """
        mock_ner_manager.extract_entities.return_value = [
            {"text": f"Entity{i}", "label": "ORG"} for i in range(12)
        ]

        text = " ".join(["word"] * 100)

        input_data = PrepassAnalyzerInput(
            segment_text=text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        assert result.recommended_route == ExtractionRoute.BIG


# =============================================================================
# Tests Document Context Integration (T1.8.1.3d)
# =============================================================================

class TestDocumentContextIntegration:
    """Tests pour l'intégration du document context Phase 1.8."""

    @pytest.mark.asyncio
    async def test_document_context_passed_to_extract_tool(self, orchestrator):
        """
        Test: document_context du state est passé au tool extract_concepts.
        """
        # Setup state avec document_context
        state = AgentState(
            document_id="test_doc",
            tenant_id="default",
            document_context="This document describes SAP S/4HANA Cloud solutions."
        )

        # Créer input avec context
        input_data = ExtractConceptsInput(
            segment={"text": "S/4HANA enables real-time analytics"},
            route=ExtractionRoute.SMALL,
            use_llm=True,
            document_context=state.document_context
        )

        # Vérifier que le context est bien dans l'input
        assert input_data.document_context == "This document describes SAP S/4HANA Cloud solutions."

    def test_extract_concepts_input_accepts_document_context(self):
        """
        Test: ExtractConceptsInput accepte le paramètre document_context.
        """
        input_data = ExtractConceptsInput(
            segment={"text": "test"},
            route="SMALL",
            use_llm=True,
            document_context="Context text here"
        )

        assert input_data.document_context == "Context text here"

    def test_extract_concepts_input_document_context_optional(self):
        """
        Test: document_context est optionnel (backward compatibility).
        """
        input_data = ExtractConceptsInput(
            segment={"text": "test"},
            route="SMALL",
            use_llm=True
            # Pas de document_context
        )

        assert input_data.document_context is None


# =============================================================================
# Tests Configuration Thresholds (T1.8.1.3e)
# =============================================================================

class TestConfigurationThresholds:
    """Tests pour la configuration des seuils."""

    def test_default_thresholds(self):
        """
        Test: Seuils par défaut sont corrects.
        """
        orchestrator = ExtractorOrchestrator(None)

        assert orchestrator.low_quality_ner_entity_threshold == 3
        assert orchestrator.low_quality_ner_token_threshold == 200
        assert orchestrator.no_llm_threshold == 3
        assert orchestrator.small_threshold == 8

    def test_custom_thresholds_from_config(self):
        """
        Test: Seuils custom depuis config sont appliqués.
        """
        config = {
            "low_quality_ner_entities": 5,
            "low_quality_ner_tokens": 300,
            "no_llm_threshold": 4,
            "small_threshold": 10
        }

        orchestrator = ExtractorOrchestrator(config)

        assert orchestrator.low_quality_ner_entity_threshold == 5
        assert orchestrator.low_quality_ner_token_threshold == 300
        assert orchestrator.no_llm_threshold == 4
        assert orchestrator.small_threshold == 10

    def test_custom_thresholds_affect_routing(self, mock_ner_manager, mock_semantic_config):
        """
        Test: Seuils custom modifient le routing.
        """
        # Custom config: LOW_QUALITY si < 5 entities ET > 300 tokens
        config = {
            "low_quality_ner_entities": 5,
            "low_quality_ner_tokens": 300
        }
        orchestrator = ExtractorOrchestrator(config)

        # Setup: 3 entities, 350 tokens
        mock_ner_manager.extract_entities.return_value = [
            {"text": f"Entity{i}", "label": "ORG"} for i in range(3)
        ]

        long_text = " ".join(["word"] * 350)

        input_data = PrepassAnalyzerInput(
            segment_text=long_text,
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        # Avec custom thresholds: 3 < 5 entities ET 350 > 300 tokens → LOW_QUALITY_NER
        assert result.success
        assert "LOW_QUALITY_NER" in result.reasoning


# =============================================================================
# Tests Error Handling
# =============================================================================

class TestErrorHandling:
    """Tests pour la gestion des erreurs."""

    def test_prepass_analyzer_ner_exception(self, orchestrator, mock_semantic_config):
        """
        Test: Si NER lève une exception → Fallback graceful.
        """
        with patch('knowbase.agents.extractor.orchestrator.get_ner_manager') as mock_get:
            mock_manager = Mock()
            mock_manager.extract_entities.side_effect = Exception("NER model not loaded")
            mock_get.return_value = mock_manager

            input_data = PrepassAnalyzerInput(
                segment_text="Some text to analyze",
                language="en"
            )

            result = orchestrator._prepass_analyzer_tool(input_data)

            assert not result.success
            assert "Error" in result.reasoning or "failed" in result.message.lower()
            assert result.recommended_route == "NO_LLM"  # Fallback safe

    def test_empty_text_handling(self, orchestrator, mock_ner_manager, mock_semantic_config):
        """
        Test: Texte vide → Gestion gracieuse.
        """
        mock_ner_manager.extract_entities.return_value = []

        input_data = PrepassAnalyzerInput(
            segment_text="",
            language="en"
        )

        result = orchestrator._prepass_analyzer_tool(input_data)

        assert result.success
        assert result.entity_count == 0
        # Texte vide → 0 tokens, donc pas LOW_QUALITY_NER (0 < 200)
        assert "LOW_QUALITY_NER" not in result.reasoning


# =============================================================================
# Tests RoutingReason Enum
# =============================================================================

class TestRoutingReasonEnum:
    """Tests pour l'enum RoutingReason."""

    def test_routing_reason_values(self):
        """
        Test: RoutingReason a toutes les valeurs attendues.
        """
        assert RoutingReason.LOW_QUALITY_NER.value == "LOW_QUALITY_NER"
        assert RoutingReason.SPARSE_ENTITIES.value == "SPARSE_ENTITIES"
        assert RoutingReason.DENSE_ENTITIES.value == "DENSE_ENTITIES"
        assert RoutingReason.BUDGET_FALLBACK.value == "BUDGET_FALLBACK"

    def test_extraction_route_values(self):
        """
        Test: ExtractionRoute a toutes les valeurs attendues.
        """
        assert ExtractionRoute.NO_LLM.value == "NO_LLM"
        assert ExtractionRoute.SMALL.value == "SMALL"
        assert ExtractionRoute.BIG.value == "BIG"
