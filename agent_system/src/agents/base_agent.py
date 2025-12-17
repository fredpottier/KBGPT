"""
BaseAgent - Classe abstraite pour tous les agents.

Utilise Claude Code CLI avec OAuth (abonnement Pro) au lieu de l'API payante.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import yaml
import uuid
from pathlib import Path

from models import AgentState
from tools import BaseTool
from core.claude_code_wrapper import ClaudeCodeWrapper


class BaseAgent(ABC):
    """Classe abstraite pour tous les agents utilisant Claude Code CLI."""

    # Instance partagée du wrapper pour éviter de le recréer à chaque agent
    _shared_wrapper: Optional[ClaudeCodeWrapper] = None

    def __init__(
        self,
        name: str,
        model: str = "claude-sonnet-4-5-20250929",  # Ignoré, utilise Claude Code CLI
        temperature: float = 0.1,  # Ignoré, géré par Claude Code
        max_tokens: int = 8192,  # Ignoré, géré par Claude Code
        prompts_config_path: Optional[str] = None,
        working_directory: str = "/app",
    ) -> None:
        """
        Args:
            name: Nom de l'agent
            model: Modèle LLM (ignoré - Claude Code utilise le modèle configuré)
            temperature: Température (ignoré)
            max_tokens: Nombre max de tokens (ignoré)
            prompts_config_path: Chemin vers config prompts YAML
            working_directory: Répertoire de travail pour Claude Code
        """
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.working_directory = working_directory

        # Initialiser le wrapper Claude Code CLI (partagé entre agents)
        if BaseAgent._shared_wrapper is None:
            BaseAgent._shared_wrapper = ClaudeCodeWrapper(
                project_name="knowwhere-agents",
                enable_tracing=True,
                working_directory=working_directory,
            )
        self.wrapper = BaseAgent._shared_wrapper

        # Tools disponibles pour cet agent
        self.tools: List[BaseTool] = []

        # Charger les prompts
        self.prompts = {}
        if prompts_config_path:
            self._load_prompts(prompts_config_path)

    def _load_prompts(self, config_path: str) -> None:
        """Charge les prompts depuis un fichier YAML."""
        path = Path(config_path)
        if not path.exists():
            return

        with open(path, "r") as f:
            self.prompts = yaml.safe_load(f)

    def add_tool(self, tool: BaseTool) -> None:
        """Ajoute un tool à l'agent."""
        self.tools.append(tool)

    def get_prompt(self, prompt_name: str) -> Optional[str]:
        """Récupère un prompt par son nom."""
        return self.prompts.get(prompt_name)

    def format_prompt(self, prompt_name: str, **kwargs: Any) -> str:
        """Formate un prompt avec des variables."""
        template = self.get_prompt(prompt_name)
        if not template:
            raise ValueError(f"Prompt not found: {prompt_name}")

        return template.format(**kwargs)

    @abstractmethod
    def execute(self, state: AgentState) -> AgentState:
        """
        Exécute l'agent et retourne l'état mis à jour.

        Args:
            state: État actuel du graphe

        Returns:
            État mis à jour
        """
        pass

    def invoke_llm(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any
    ) -> str:
        """
        Invoque Claude via Claude Code CLI (OAuth).

        Args:
            system_prompt: Prompt système
            user_message: Message utilisateur
            **kwargs: Arguments additionnels

        Returns:
            Réponse du LLM
        """
        # VERSION LIGHT - prompt compact pour eviter "Prompt is too long"
        # Ne pas dupliquer les en-tetes, juste combiner system + user
        full_prompt = f"{system_prompt}\n\n{user_message}"

        # Générer un task_id unique
        task_id = f"{self.name}_{uuid.uuid4().hex[:8]}"

        # Exécuter via Claude Code CLI
        result = self.wrapper.execute_task(
            task_description=full_prompt,
            task_id=task_id,
            timeout_seconds=1200,  # 20 minutes par appel (tâches complexes)
        )

        if result["status"] == "success":
            return result["output"] or ""
        else:
            error_msg = result.get("error", "Unknown error")
            raise Exception(f"Claude Code CLI error: {error_msg}")

    def invoke_llm_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[BaseTool]] = None,
    ) -> Any:
        """
        Invoque Claude avec accès aux tools via Claude Code CLI.

        Note: Les tools sont disponibles nativement dans Claude Code CLI,
        donc on passe juste le prompt.

        Args:
            system_prompt: Prompt système
            user_message: Message utilisateur
            tools: Liste de tools (ignoré - Claude Code a ses propres tools)

        Returns:
            Réponse du LLM
        """
        # VERSION LIGHT - Claude Code CLI a deja acces aux tools
        # Pas besoin d'ajouter une longue note
        return self.invoke_llm(system_prompt, user_message)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', using='ClaudeCodeCLI')"
