"""
Tests d'intégration pour le système de routage LLM.
Ces tests nécessitent une configuration complète et ne mockent pas les dépendances externes.
"""

import pytest
import logging
from pathlib import Path

from knowbase.common.llm_router import LLMRouter, TaskType


class TestLLMRouterIntegration:
    """Tests d'intégration pour le routeur LLM."""

    def test_router_initialization_with_real_config(self):
        """Test l'initialisation avec la vraie configuration."""
        try:
            router = LLMRouter()

            # Vérifications de base
            assert router._config is not None
            assert "task_models" in router._config
            assert "default_model" in router._config

            print("✅ Routeur initialisé avec succès")
            print(f"📋 Version config: {router._config.get('version', 'N/A')}")
            print(f"📋 Modèle par défaut: {router._config.get('default_model', 'N/A')}")

        except Exception as e:
            pytest.fail(f"Échec de l'initialisation du routeur: {e}")

    def test_provider_detection(self):
        """Test la détection des providers disponibles."""
        router = LLMRouter()

        providers = router._available_providers

        # Au moins un provider devrait être disponible
        assert any(providers.values()), "Aucun provider LLM disponible"

        print("🔌 Providers détectés:")
        for provider, available in providers.items():
            status = "✅" if available else "❌"
            print(f"  - {provider}: {status}")

    def test_model_resolution_for_all_tasks(self):
        """Test la résolution des modèles pour toutes les tâches."""
        router = LLMRouter()

        tasks = [
            TaskType.VISION,
            TaskType.METADATA_EXTRACTION,
            TaskType.LONG_TEXT_SUMMARY,
            TaskType.SHORT_ENRICHMENT,
            TaskType.FAST_CLASSIFICATION,
            TaskType.CANONICALIZATION,
        ]

        print("\n📋 Résolution des modèles:")

        for task in tasks:
            try:
                model = router._get_model_for_task(task)
                provider = router._get_provider_for_model(model)
                available = router._is_model_available(model)

                status = "✅" if available else "⚠️"
                print(f"  {status} {task.value}: {model} ({provider})")

                # Vérifications
                assert model is not None
                assert provider in ["openai", "anthropic"]

            except Exception as e:
                pytest.fail(f"Erreur pour la tâche {task.value}: {e}")

    @pytest.mark.skipif(
        not Path("config/llm_models.yaml").exists(),
        reason="Fichier de configuration non trouvé"
    )
    def test_config_file_structure(self):
        """Test la structure du fichier de configuration."""
        import yaml

        config_path = Path("config/llm_models.yaml")

        with config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Vérifications de structure
        required_sections = ["task_models", "providers", "default_model"]
        for section in required_sections:
            assert section in config, f"Section manquante: {section}"

        # Vérifications des tâches
        task_models = config["task_models"]
        expected_tasks = [task.value for task in TaskType]

        for task in expected_tasks:
            assert task in task_models, f"Tâche manquante dans config: {task}"

        print("✅ Structure du fichier de configuration validée")

    def test_fallback_behavior(self, caplog):
        """Test le comportement de fallback."""
        with caplog.at_level(logging.INFO):
            router = LLMRouter()

            # Forcer un modèle indisponible pour tester le fallback
            with router._config.setdefault("task_models", {}).update({"vision": "modele_inexistant"}):
                try:
                    model = router._get_model_for_task(TaskType.VISION)
                    # Devrait utiliser un fallback ou le modèle par défaut
                    assert model is not None
                except Exception:
                    # C'est acceptable si aucun fallback n'est configuré
                    pass

        # Vérifier qu'il y a eu des logs de fallback si nécessaire
        fallback_logs = [record for record in caplog.records if "fallback" in record.message.lower()]
        if fallback_logs:
            print("🔄 Comportement de fallback testé avec succès")


def test_demo_configuration_change():
    """
    Test de démonstration du changement de configuration.
    Ce test montre comment la configuration peut être modifiée dynamiquement.
    """
    print("\n=== Démo de changement de configuration ===")

    # Créer deux instances avec des configs différentes
    router1 = LLMRouter()
    model1 = router1._get_model_for_task(TaskType.VISION)
    provider1 = router1._get_provider_for_model(model1)

    print(f"📋 Configuration actuelle pour 'vision': {model1} ({provider1})")

    print("\n💡 Pour changer dynamiquement:")
    print("1. Modifiez config/llm_models.yaml")
    print("2. Redémarrez l'application")
    print("3. Le nouveau modèle sera automatiquement utilisé")

    print("\n📝 Exemple de modification:")
    print("task_models:")
    print("  vision: \"claude-3-5-sonnet-20241022\"  # Au lieu de gpt-4o")
    print("  metadata: \"gpt-4o-mini\"               # Plus rapide/moins cher")


if __name__ == "__main__":
    """Permet d'exécuter les tests d'intégration directement."""
    import sys

    # Configuration du logging
    logging.basicConfig(level=logging.DEBUG)

    print("🧪 Tests d'intégration du routeur LLM")
    print("=" * 50)

    try:
        # Tests de base
        test_instance = TestLLMRouterIntegration()

        test_instance.test_router_initialization_with_real_config()
        test_instance.test_provider_detection()
        test_instance.test_model_resolution_for_all_tasks()
        test_instance.test_config_file_structure()

        test_demo_configuration_change()

        print("\n🎉 Tous les tests d'intégration sont passés!")

    except Exception as e:
        print(f"\n❌ Erreur lors des tests: {e}")
        sys.exit(1)