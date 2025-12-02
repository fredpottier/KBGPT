"""
BaseAgent - Classe abstraite pour tous les agents.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import yaml
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from models import AgentState
from tools import BaseTool


class BaseAgent(ABC):
    """Classe abstraite pour tous les agents."""

    def __init__(
        self,
        name: str,
        model: str = "claude-sonnet-4-5-20250929",
        temperature: float = 0.1,
        max_tokens: int = 8192,
        prompts_config_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            name: Nom de l'agent
            model: Modèle LLM à utiliser
            temperature: Température pour génération
            max_tokens: Nombre max de tokens
            prompts_config_path: Chemin vers config prompts YAML
        """
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Initialiser le LLM
        self.llm = ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

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
        Invoque le LLM avec un system prompt et un message utilisateur.

        Args:
            system_prompt: Prompt système
            user_message: Message utilisateur
            **kwargs: Arguments additionnels

        Returns:
            Réponse du LLM
        """
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        response = self.llm.invoke(messages)
        return response.content

    def invoke_llm_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[BaseTool]] = None,
    ) -> Any:
        """
        Invoque le LLM avec accès aux tools.

        Args:
            system_prompt: Prompt système
            user_message: Message utilisateur
            tools: Liste de tools à utiliser

        Returns:
            Réponse du LLM
        """
        # Pour LangChain tools, on devrait bind les tools au LLM
        # Ici version simplifiée sans binding
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        response = self.llm.invoke(messages)
        return response.content

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', model='{self.model}')"
