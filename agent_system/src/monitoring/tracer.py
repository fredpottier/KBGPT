"""
Configuration LangSmith pour monitoring et traceability.
"""
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def load_langsmith_config(config_path: str = "agent_system/config/langsmith.yaml") -> Dict[str, Any]:
    """
    Charge la configuration LangSmith depuis le fichier YAML.

    Args:
        config_path: Chemin vers le fichier de configuration

    Returns:
        Configuration LangSmith
    """
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Configuration LangSmith non trouvee: {config_path}")

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config.get("langsmith", {})


def configure_langsmith(
    api_key: Optional[str] = None,
    project: Optional[str] = None,
    config_path: str = "agent_system/config/langsmith.yaml",
    enabled: bool = True,
) -> None:
    """
    Configure les variables d'environnement pour LangSmith.

    Args:
        api_key: Cle API LangSmith (optionnel, sinon charge depuis config)
        project: Nom du projet LangSmith (optionnel, sinon charge depuis config)
        config_path: Chemin vers le fichier de configuration
        enabled: Activer ou desactiver le tracing
    """
    try:
        config = load_langsmith_config(config_path)
    except FileNotFoundError:
        print(f"⚠️  Configuration LangSmith non trouvee: {config_path}")
        config = {}

    # API Key
    final_api_key = api_key or config.get("api_key") or os.getenv("LANGSMITH_API_KEY")
    if final_api_key:
        os.environ["LANGSMITH_API_KEY"] = final_api_key
    else:
        print("⚠️  LANGSMITH_API_KEY non definie")

    # Project
    final_project = project or config.get("project", "knowwhere-agents")
    os.environ["LANGSMITH_PROJECT"] = final_project

    # Tracing
    os.environ["LANGSMITH_TRACING"] = "true" if enabled and final_api_key else "false"

    # Endpoint (optionnel)
    if config.get("endpoint"):
        os.environ["LANGSMITH_ENDPOINT"] = config["endpoint"]

    # Informations
    if enabled and final_api_key:
        print("✅ LangSmith tracing active")
        print(f"   Project: {final_project}")
        print(f"   API Key: {'*' * (len(final_api_key) - 8)}{final_api_key[-8:]}")
    else:
        print("⚠️  LangSmith tracing desactive")


def configure_langsmith_evaluators(config_path: str = "agent_system/config/langsmith.yaml") -> Dict[str, Any]:
    """
    Charge la configuration des evaluateurs LangSmith.

    Args:
        config_path: Chemin vers le fichier de configuration

    Returns:
        Configuration des evaluateurs
    """
    try:
        config = load_langsmith_config(config_path)
        return config.get("evaluators", {})
    except FileNotFoundError:
        return {}


def get_run_url(run_id: str, project: Optional[str] = None) -> str:
    """
    Genere l'URL LangSmith pour visualiser un run.

    Args:
        run_id: ID du run LangSmith
        project: Nom du projet (optionnel)

    Returns:
        URL du run
    """
    project_name = project or os.getenv("LANGSMITH_PROJECT", "knowwhere-agents")
    return f"https://smith.langchain.com/o/default/projects/p/{project_name}/r/{run_id}"


def print_run_info(run_id: str, project: Optional[str] = None) -> None:
    """
    Affiche les informations d'un run LangSmith.

    Args:
        run_id: ID du run
        project: Nom du projet (optionnel)
    """
    url = get_run_url(run_id, project)
    print()
    print("=" * 80)
    print("🔍 LangSmith Run Info")
    print("=" * 80)
    print(f"Run ID: {run_id}")
    print(f"URL: {url}")
    print("=" * 80)
    print()
