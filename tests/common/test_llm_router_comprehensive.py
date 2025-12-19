"""Tests complets pour LLMRouter.

Tests unitaires couvrant:
- TaskType enum
- Routage des modèles selon les tâches
- Détection des providers disponibles
- Fallback en cas d'erreur
- Formatage des prompts pour différents providers
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import tempfile
import yaml

from knowbase.common.llm_router import (
    TaskType,
    LLMRouter,
    get_llm_router,
)


@pytest.fixture
def sample_config():
    """Configuration LLM de test."""
    return {
        "task_models": {
            "vision": "gpt-4o",
            "metadata": "gpt-4o-mini",
            "long_summary": "claude-3-opus-20240229",
            "enrichment": "gpt-4o-mini",
            "classification": "gpt-4o-mini",
            "canonicalization": "gpt-4o-mini",
        },
        "default_model": "gpt-4o",
        "providers": {
            "openai": {
                "models": ["gpt-4o", "gpt-4o-mini", "o1-preview"],
            },
            "anthropic": {
                "models": ["claude-3-opus-20240229", "claude-3-sonnet-20240229"],
            },
            "google": {
                "models": ["gemini-1.5-pro", "gemini-1.5-flash"],
            },
        },
        "fallback_strategy": {
            "vision": ["gpt-4o-mini"],
            "long_summary": ["gpt-4o", "gpt-4o-mini"],
        },
        "task_parameters": {
            "vision": {"temperature": 0.2, "max_tokens": 4000},
            "metadata": {"temperature": 0.1, "max_tokens": 2000},
        },
    }


@pytest.fixture
def temp_config_file(sample_config):
    """Crée un fichier de configuration temporaire."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_config, f)
        yield Path(f.name)


class TestTaskTypeEnum:
    """Tests pour l'enum TaskType."""

    def test_task_type_values(self) -> None:
        """Test que tous les types de tâches sont définis."""
        assert TaskType.VISION.value == "vision"
        assert TaskType.METADATA_EXTRACTION.value == "metadata"
        assert TaskType.LONG_TEXT_SUMMARY.value == "long_summary"
        assert TaskType.SHORT_ENRICHMENT.value == "enrichment"
        assert TaskType.FAST_CLASSIFICATION.value == "classification"
        assert TaskType.CANONICALIZATION.value == "canonicalization"
        assert TaskType.RFP_QUESTION_ANALYSIS.value == "rfp_question_analysis"
        assert TaskType.TRANSLATION.value == "translation"
        assert TaskType.KNOWLEDGE_EXTRACTION.value == "knowledge_extraction"

    def test_task_type_is_string_enum(self) -> None:
        """Test que TaskType hérite de str."""
        assert isinstance(TaskType.VISION, str)
        assert TaskType.VISION == "vision"


class TestLLMRouterConfig:
    """Tests pour le chargement de configuration."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_load_config_from_file(
        self,
        mock_gemini,
        mock_anthropic,
        mock_openai,
        temp_config_file: Path,
    ) -> None:
        """Test chargement configuration depuis fichier."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        assert router._config["default_model"] == "gpt-4o"
        assert "vision" in router._config["task_models"]

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_load_config_fallback_default(
        self, mock_gemini, mock_anthropic, mock_openai
    ) -> None:
        """Test configuration par défaut si fichier manquant."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        # Fichier inexistant
        router = LLMRouter(config_path=Path("/nonexistent/config.yaml"))

        # Devrait utiliser config par défaut
        assert router._config["default_model"] == "gpt-4o"


class TestLLMRouterProviderDetection:
    """Tests pour la détection des providers."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_detect_openai_available(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test détection OpenAI disponible."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        assert router._available_providers["openai"] is True
        assert router._available_providers["anthropic"] is False

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_detect_all_providers(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test détection de tous les providers disponibles."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = True
        mock_gemini.return_value = True

        router = LLMRouter(config_path=temp_config_file)

        assert router._available_providers["openai"] is True
        assert router._available_providers["anthropic"] is True
        assert router._available_providers["google"] is True


class TestLLMRouterModelSelection:
    """Tests pour la sélection de modèle."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_get_provider_for_openai_model(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test détection provider pour modèle OpenAI."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        assert router._get_provider_for_model("gpt-4o") == "openai"
        assert router._get_provider_for_model("gpt-4o-mini") == "openai"
        assert router._get_provider_for_model("o1-preview") == "openai"

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_get_provider_for_anthropic_model(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test détection provider pour modèle Anthropic."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = True
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        assert router._get_provider_for_model("claude-3-opus-20240229") == "anthropic"
        assert router._get_provider_for_model("claude-3-sonnet-20240229") == "anthropic"

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_get_provider_for_gemini_model(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test détection provider pour modèle Gemini."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = True

        router = LLMRouter(config_path=temp_config_file)

        assert router._get_provider_for_model("gemini-1.5-pro") == "google"

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_get_model_for_task(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test sélection modèle selon la tâche."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        # Vision devrait retourner gpt-4o
        model = router._get_model_for_task(TaskType.VISION)
        assert model == "gpt-4o"

        # Metadata devrait retourner gpt-4o-mini
        model = router._get_model_for_task(TaskType.METADATA_EXTRACTION)
        assert model == "gpt-4o-mini"


class TestLLMRouterPromptFormatting:
    """Tests pour le formatage des prompts."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_format_llama_prompt(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test formatage prompt pour Llama."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

        formatted = router._format_llama_prompt(messages)

        assert "<<SYS>>" in formatted
        assert "You are helpful." in formatted
        assert "[INST]" in formatted
        assert "Hello" in formatted

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_format_qwen_prompt(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test formatage prompt pour Qwen."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

        formatted = router._format_qwen_prompt(messages)

        assert "<|im_start|>system" in formatted
        assert "<|im_start|>user" in formatted
        assert "<|im_end|>" in formatted

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_format_llava_prompt(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test formatage prompt pour LLaVA."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        messages = [
            {"role": "user", "content": "Describe this image."},
        ]

        formatted = router._format_llava_prompt(messages)

        assert "USER:" in formatted
        assert "ASSISTANT:" in formatted


class TestLLMRouterComplete:
    """Tests pour la méthode complete."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    @patch("knowbase.common.llm_router.track_tokens")
    def test_complete_openai_success(
        self,
        mock_track,
        mock_gemini,
        mock_anthropic,
        mock_openai,
        temp_config_file: Path,
    ) -> None:
        """Test appel complet vers OpenAI."""
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
        mock_response.usage = MagicMock(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        messages = [{"role": "user", "content": "Hello"}]
        result = router.complete(TaskType.VISION, messages)

        assert result == "Test response"
        mock_track.assert_called_once()


class TestLLMRouterFallback:
    """Tests pour le mécanisme de fallback."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_fallback_to_default_model(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test fallback vers modèle par défaut si configuré indisponible."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False  # Anthropic indisponible
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        # long_summary est configuré pour claude-3-opus mais Anthropic indisponible
        model = router._get_model_for_task(TaskType.LONG_TEXT_SUMMARY)

        # Devrait fallback vers gpt-4o (premier fallback disponible)
        assert model in ["gpt-4o", "gpt-4o-mini"]


class TestLLMRouterTokenEstimation:
    """Tests pour l'estimation des tokens."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_estimate_tokens(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test estimation grossière des tokens."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        # 40 caractères ≈ 10 tokens
        text = "a" * 40
        estimated = router._estimate_tokens(text)

        assert estimated == 10

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_estimate_tokens_minimum(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test estimation minimum de 1 token."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        # Texte très court
        estimated = router._estimate_tokens("ab")

        assert estimated >= 1


class TestLLMRouterSingleton:
    """Tests pour le pattern singleton."""

    def test_get_llm_router_returns_same_instance(self) -> None:
        """Test que get_llm_router retourne la même instance."""
        # Reset singleton pour test isolé
        import knowbase.common.llm_router as module
        module._router_instance = None

        with patch("knowbase.common.llm_router.get_openai_client") as mock_openai:
            with patch("knowbase.common.llm_router.is_anthropic_available") as mock_anthropic:
                with patch("knowbase.common.llm_router.is_gemini_available") as mock_gemini:
                    mock_openai.return_value = MagicMock()
                    mock_anthropic.return_value = False
                    mock_gemini.return_value = False

                    router1 = get_llm_router()
                    router2 = get_llm_router()

                    assert router1 is router2

        # Cleanup
        module._router_instance = None


class TestLLMRouterModelAvailability:
    """Tests pour la vérification de disponibilité des modèles."""

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_model_available_when_provider_available(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test qu'un modèle est disponible si son provider l'est."""
        mock_openai.return_value = MagicMock()
        mock_anthropic.return_value = True
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        assert router._is_model_available("gpt-4o") is True
        assert router._is_model_available("claude-3-opus-20240229") is True
        assert router._is_model_available("gemini-1.5-pro") is False

    @patch("knowbase.common.llm_router.get_openai_client")
    @patch("knowbase.common.llm_router.is_anthropic_available")
    @patch("knowbase.common.llm_router.is_gemini_available")
    def test_model_unavailable_when_provider_unavailable(
        self, mock_gemini, mock_anthropic, mock_openai, temp_config_file: Path
    ) -> None:
        """Test qu'un modèle est indisponible si son provider l'est."""
        mock_openai.side_effect = Exception("No API key")
        mock_anthropic.return_value = False
        mock_gemini.return_value = False

        router = LLMRouter(config_path=temp_config_file)

        assert router._is_model_available("gpt-4o") is False
        assert router._is_model_available("claude-3-opus-20240229") is False
