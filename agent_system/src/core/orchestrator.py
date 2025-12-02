"""
Agent Orchestrator - Orchestrateur principal base sur LangGraph.
"""
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from langgraph.graph import StateGraph, END

from models import Task, AgentState, create_initial_state
from agents import PlanningAgent, DevAgent, ControlAgent
from tools import (
    FilesystemTool,
    ShellTool,
    GitTool,
    TestingTool,
    CodeAnalysisTool,
    DockerTool,
    load_filesystem_tool_from_config,
    load_shell_tool_from_config,
    load_git_tool_from_config,
    load_docker_tool_from_config,
)


class AgentOrchestrator:
    """Orchestrateur principal du systeme d'agents."""

    def __init__(
        self,
        config_path: str = "agent_system/config/",
        tools_config_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            config_path: Chemin vers le dossier de configuration
            tools_config_path: Chemin vers la config tools (optionnel)
        """
        self.config_path = Path(config_path)
        self.tools_config_path = tools_config_path or str(
            self.config_path / "tools_permissions.yaml"
        )

        # Charger la configuration
        self.config = self._load_config()

        # Initialiser les tools
        self.tools = self._initialize_tools()

        # Initialiser les agents
        self.planning_agent = self._initialize_planning_agent()
        self.dev_agent = self._initialize_dev_agent()
        self.control_agent = self._initialize_control_agent()

        # Construire le graphe LangGraph
        self.graph = self._build_graph()

    def _load_config(self) -> Dict[str, Any]:
        """Charge la configuration depuis agents_settings.yaml."""
        config_file = self.config_path / "agents_settings.yaml"
        with open(config_file, "r") as f:
            return yaml.safe_load(f)

    def _initialize_tools(self) -> Dict[str, Any]:
        """Initialise tous les tools."""
        tools = {}

        # Filesystem Tool
        tools["filesystem"] = load_filesystem_tool_from_config(self.tools_config_path)

        # Shell Tool
        tools["shell"] = load_shell_tool_from_config(self.tools_config_path)

        # Git Tool
        tools["git"] = load_git_tool_from_config(self.tools_config_path)

        # Testing Tool
        tools["testing"] = TestingTool()

        # Code Analysis Tool
        tools["code_analysis"] = CodeAnalysisTool()

        # Docker Tool
        tools["docker"] = load_docker_tool_from_config(self.tools_config_path)

        return tools

    def _initialize_planning_agent(self) -> PlanningAgent:
        """Initialise le Planning Agent."""
        agent = PlanningAgent(
            prompts_config_path=str(self.config_path / "prompts/planning.yaml"),
        )

        # Ajouter les tools pertinents
        agent.add_tool(self.tools["filesystem"])
        agent.add_tool(self.tools["git"])
        agent.add_tool(self.tools["code_analysis"])

        return agent

    def _initialize_dev_agent(self) -> DevAgent:
        """Initialise le Dev Agent."""
        agent = DevAgent(
            prompts_config_path=str(self.config_path / "prompts/dev.yaml"),
        )

        # Ajouter tous les tools
        for tool in self.tools.values():
            agent.add_tool(tool)

        return agent

    def _initialize_control_agent(self) -> ControlAgent:
        """Initialise le Control Agent."""
        agent = ControlAgent(
            prompts_config_path=str(self.config_path / "prompts/control.yaml"),
            conformity_threshold=self.config.get("agents", {}).get("control", {}).get("conformity_threshold", 0.85),
        )

        # Ajouter les tools d'analyse
        agent.add_tool(self.tools["code_analysis"])
        agent.add_tool(self.tools["testing"])
        agent.add_tool(self.tools["git"])

        return agent

    def _build_graph(self) -> StateGraph:
        """Construit le graphe LangGraph."""
        graph = StateGraph(AgentState)

        # Ajouter les nodes
        graph.add_node("planning", self._planning_node)
        graph.add_node("dev", self._dev_node)
        graph.add_node("control", self._control_node)

        # Definir le point d'entree
        graph.set_entry_point("planning")

        # Ajouter les transitions
        graph.add_edge("planning", "dev")
        graph.add_edge("dev", "control")

        # Condition de sortie depuis control
        graph.add_conditional_edges(
            "control",
            self._should_end,
            {
                "end": END,
                "replan": "planning",
            }
        )

        return graph.compile()

    def _planning_node(self, state: AgentState) -> AgentState:
        """Node Planning Agent."""
        return self.planning_agent.execute(state)

    def _dev_node(self, state: AgentState) -> AgentState:
        """Node Dev Agent."""
        # Selectionner la premiere sous-tache prete
        ready_subtasks = state["plan"].get_ready_subtasks()
        if ready_subtasks:
            state["current_subtask_id"] = ready_subtasks[0].subtask_id

        return self.dev_agent.execute(state)

    def _control_node(self, state: AgentState) -> AgentState:
        """Node Control Agent."""
        return self.control_agent.execute(state)

    def _should_end(self, state: AgentState) -> str:
        """Determine si le workflow doit se terminer."""
        if state.get("validation_passed", False):
            return "end"

        # Si trop d'iterations, terminer
        if state.get("iteration_count", 0) >= 10:
            return "end"

        # Sinon, replanner
        return "replan"

    def run(self, task: Task, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute l'orchestration complete.

        Args:
            task: Tache a executer
            context: Contexte additionnel

        Returns:
            Resultat de l'orchestration
        """
        # Creer l'etat initial
        state = create_initial_state(task, context)

        # Executer le graphe
        final_state = self.graph.invoke(state)

        # Retourner le resultat
        return {
            "status": "success" if final_state.get("validation_passed") else "failed",
            "task_id": task.task_id,
            "plan_id": final_state["plan"].plan_id if final_state.get("plan") else None,
            "dev_reports": [r.model_dump() for r in final_state.get("dev_reports", [])],
            "control_reports": [r.model_dump() for r in final_state.get("control_reports", [])],
            "validation_passed": final_state.get("validation_passed", False),
            "iterations": final_state.get("iteration_count", 0),
        }
