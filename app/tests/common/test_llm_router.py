"""
Tests unitaires pour le système de routage LLM flexible.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import yaml

from knowbase.common.llm_router import LLMRouter, TaskType


@pytest.fixture
def mock_config():
    """Configuration mock pour les tests."""
    return {
        "version": "1.0",
        "task_models": {
            "vision": "gpt-4o",
            "metadata": "gpt-4o",
            "long_summary": "claude-3-5-sonnet-20241022",
            "enrichment": "claude-3-5-haiku-20241022",
            "classification": "gpt-4o-mini",
            "canonicalization": "gpt-4o-mini"
        },
        "providers": {
            "openai": {
                "models": ["gpt-4o", "gpt-4o-mini"]
            },
            "anthropic": {
                "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
            }
        },
        "fallback_strategy": {
            "vision": ["gpt-4o", "claude-3-5-sonnet-20241022"]
        },
        "default_model": "gpt-4o"
    }


@pytest.fixture
def mock_available_providers():
    """Mock des providers disponibles."""
    return {
        "openai": True,
        "anthropic": True
    }


class TestLLMRouter:
    """Tests pour la classe LLMRouter."""

    @patch('knowbase.common.llm_router.get_settings')
    @patch('builtins.open', new_callable=mock_open)
    @patch('yaml.safe_load')
    def test_load_config_success(self, mock_yaml, mock_file, mock_settings, mock_config):
        """Test le chargement réussi de la configuration."""
        mock_yaml.return_value = mock_config
        mock_settings.return_value = Mock()

        with patch.object(LLMRouter, '_detect_available_providers', return_value={}):
            router = LLMRouter()

        assert router._config == mock_config
        mock_file.assert_called_once()
        mock_yaml.assert_called_once()

    @patch('knowbase.common.llm_router.get_settings')
    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_load_config_fallback(self, mock_file, mock_settings):
        """Test le fallback quand le fichier de config n'existe pas."""
        mock_settings.return_value = Mock()

        with patch.object(LLMRouter, '_detect_available_providers', return_value={}):
            router = LLMRouter()

        # Doit utiliser la config par défaut
        assert "task_models" in router._config
        assert router._config["default_model"] == "gpt-4o"

    @patch('knowbase.common.llm_router.get_settings')
    @patch('knowbase.common.llm_router.get_openai_client')
    @patch('knowbase.common.llm_router.is_anthropic_available')
    def test_detect_available_providers(self, mock_anthropic, mock_openai, mock_settings):
        """Test la détection des providers disponibles."""
        mock_settings.return_value = Mock()
        mock_openai.return_value = Mock()  # Succès OpenAI
        mock_anthropic.return_value = True  # Succès Anthropic

        with patch.object(LLMRouter, '_load_config', return_value={}):
            router = LLMRouter()

        assert router._available_providers["openai"] is True
        assert router._available_providers["anthropic"] is True

    @patch('knowbase.common.llm_router.get_settings')
    def test_get_provider_for_model(self, mock_settings, mock_config):
        """Test la détection automatique du provider."""
        mock_settings.return_value = Mock()

        with patch.object(LLMRouter, '_load_config', return_value=mock_config), \
             patch.object(LLMRouter, '_detect_available_providers', return_value={}):
            router = LLMRouter()

        # Test avec modèles dans la config
        assert router._get_provider_for_model("gpt-4o") == "openai"
        assert router._get_provider_for_model("claude-3-5-sonnet-20241022") == "anthropic"

        # Test avec détection par nom
        assert router._get_provider_for_model("gpt-3.5-turbo") == "openai"
        assert router._get_provider_for_model("claude-3-opus") == "anthropic"

    @patch('knowbase.common.llm_router.get_settings')
    def test_get_model_for_task(self, mock_settings, mock_config, mock_available_providers):
        """Test la résolution du modèle pour une tâche."""
        mock_settings.return_value = Mock()

        with patch.object(LLMRouter, '_load_config', return_value=mock_config), \
             patch.object(LLMRouter, '_detect_available_providers', return_value=mock_available_providers):
            router = LLMRouter()

        # Test modèle configuré et disponible
        model = router._get_model_for_task(TaskType.VISION)
        assert model == "gpt-4o"

        # Test modèle Claude
        model = router._get_model_for_task(TaskType.LONG_TEXT_SUMMARY)
        assert model == "claude-3-5-sonnet-20241022"

    @patch('knowbase.common.llm_router.get_settings')
    def test_is_model_available(self, mock_settings, mock_config, mock_available_providers):
        """Test la vérification de disponibilité d'un modèle."""
        mock_settings.return_value = Mock()

        with patch.object(LLMRouter, '_load_config', return_value=mock_config), \
             patch.object(LLMRouter, '_detect_available_providers', return_value=mock_available_providers):
            router = LLMRouter()

        # Modèle disponible
        assert router._is_model_available("gpt-4o") is True

        # Provider indisponible
        with patch.object(router, '_available_providers', {"openai": False, "anthropic": True}):
            assert router._is_model_available("gpt-4o") is False
            assert router._is_model_available("claude-3-5-sonnet-20241022") is True

    @patch('knowbase.common.llm_router.get_settings')
    def test_complete_success(self, mock_settings, mock_config, mock_available_providers):
        """Test un appel LLM réussi."""
        mock_settings.return_value = Mock()

        with patch.object(LLMRouter, '_load_config', return_value=mock_config), \
             patch.object(LLMRouter, '_detect_available_providers', return_value=mock_available_providers), \
             patch.object(LLMRouter, '_call_openai', return_value="test response") as mock_call:
            router = LLMRouter()

            messages = [{"role": "user", "content": "test"}]
            result = router.complete(TaskType.VISION, messages)

            assert result == "test response"
            mock_call.assert_called_once_with("gpt-4o", messages, 0.2, 1024)

    @patch('knowbase.common.llm_router.get_settings')
    def test_complete_with_fallback(self, mock_settings, mock_config):
        """Test le fallback en cas d'erreur."""
        mock_settings.return_value = Mock()

        # Anthropic indisponible, doit fallback vers OpenAI
        unavailable_providers = {"openai": True, "anthropic": False}

        with patch.object(LLMRouter, '_load_config', return_value=mock_config), \
             patch.object(LLMRouter, '_detect_available_providers', return_value=unavailable_providers), \
             patch.object(LLMRouter, '_call_openai', return_value="fallback response") as mock_call:
            router = LLMRouter()

            messages = [{"role": "user", "content": "test"}]
            result = router.complete(TaskType.LONG_TEXT_SUMMARY, messages)

            # Devrait utiliser le fallback OpenAI au lieu du Claude configuré
            assert result == "fallback response"


class TestTaskType:
    """Tests pour l'enum TaskType."""

    def test_all_task_types_exist(self):
        """Vérifie que tous les types de tâches existent."""
        expected_tasks = [
            "vision",
            "metadata",
            "long_summary",
            "enrichment",
            "classification",
            "canonicalization"
        ]

        actual_tasks = [task.value for task in TaskType]

        for expected in expected_tasks:
            assert expected in actual_tasks