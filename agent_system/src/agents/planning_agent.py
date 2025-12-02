"""
Planning Agent - Décompose les tâches complexes en sous-tâches.
"""
from datetime import datetime
from typing import Any, Dict
import yaml

from .base_agent import BaseAgent
from models import (
    AgentState,
    Plan,
    Subtask,
    Risk,
    RiskLevel,
    ValidationPoint,
    TaskStatus,
    TaskComplexity,
)
from tools import FilesystemTool, GitTool, CodeAnalysisTool


class PlanningAgent(BaseAgent):
    """Agent spécialisé dans la planification et décomposition de tâches."""

    def __init__(
        self,
        prompts_config_path: str = "agent_system/config/prompts/planning.yaml",
        **kwargs: Any
    ) -> None:
        super().__init__(
            name="planning_agent",
            prompts_config_path=prompts_config_path,
            **kwargs
        )

    def execute(self, state: AgentState) -> AgentState:
        """
        Exécute le planning: décompose la tâche en sous-tâches.

        Args:
            state: État actuel

        Returns:
            État mis à jour avec le plan
        """
        task = state["task"]

        # 1. Analyser le contexte du projet
        context_analysis = self._analyze_project_context(state)

        # 2. Décomposer la tâche
        plan = self._create_plan(task, context_analysis)

        # 3. Valider le plan (réflexion)
        if self.prompts.get("reflection_prompt"):
            plan = self._validate_and_improve_plan(plan)

        # 4. Mettre à jour l'état
        state["plan"] = plan
        state["planning_iterations"] += 1

        return state

    def _analyze_project_context(self, state: AgentState) -> Dict[str, Any]:
        """Analyse le contexte du projet pour mieux planifier."""
        context = {}

        # Analyser la structure du projet si GitTool disponible
        for tool in self.tools:
            if isinstance(tool, GitTool):
                status_result = tool.execute(operation="status")
                if status_result.is_success:
                    context["git_status"] = status_result.output

        return context

    def _create_plan(self, task: Any, context: Dict[str, Any]) -> Plan:
        """Crée le plan de décomposition."""
        system_prompt = self.get_prompt("system_prompt")

        if not system_prompt:
            system_prompt = "Tu es un Planning Agent expert en décomposition de tâches."

        decomposition_prompt = self.format_prompt(
            "task_decomposition_prompt",
            task_description=task.description,
            requirements="\n".join(task.requirements),
            context=str(context),
            min_subtasks=2,
            max_subtasks=10,
        )

        # Invoquer le LLM
        response = self.invoke_llm(system_prompt, decomposition_prompt)

        # Parser la réponse YAML
        try:
            plan_data = yaml.safe_load(response)
        except yaml.YAMLError:
            # Fallback: créer un plan minimal
            plan_data = self._create_fallback_plan(task)

        # Construire l'objet Plan
        plan = self._build_plan_from_data(task, plan_data)

        return plan

    def _build_plan_from_data(self, task: Any, plan_data: Dict[str, Any]) -> Plan:
        """Construit un objet Plan depuis les données parsées."""
        subtasks = []
        for st_data in plan_data.get("subtasks", []):
            subtask = Subtask(
                subtask_id=st_data.get("subtask_id"),
                title=st_data.get("title"),
                description=st_data.get("description"),
                complexity=TaskComplexity[st_data.get("complexity", "medium").upper()],
                estimated_duration_minutes=st_data.get("estimated_duration_minutes", 60),
                dependencies=st_data.get("dependencies", []),
                validation_criteria=st_data.get("validation_criteria", ""),
                files_impacted=st_data.get("files_impacted", []),
            )
            subtasks.append(subtask)

        # Risks
        risks = []
        for risk_data in plan_data.get("risks", []):
            risk = Risk(
                risk_id=f"risk_{len(risks)+1:03d}",
                description=risk_data.get("risk", ""),
                probability=RiskLevel[risk_data.get("probability", "medium").upper()],
                impact=RiskLevel[risk_data.get("probability", "medium").upper()],
                mitigation=risk_data.get("mitigation", ""),
            )
            risks.append(risk)

        # Validation points
        validation_points = []
        for vp_data in plan_data.get("validation_points", []):
            vp = ValidationPoint(
                validation_id=f"vp_{len(validation_points)+1:03d}",
                after_subtask_id=vp_data.get("after", ""),
                check_description=vp_data.get("check", ""),
            )
            validation_points.append(vp)

        plan = Plan(
            plan_id=plan_data.get("plan_id", f"plan_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"),
            task_id=task.task_id,
            task_description=task.description,
            subtasks=subtasks,
            dependencies_graph=plan_data.get("dependencies_graph", ""),
            critical_path=plan_data.get("critical_path", []),
            estimated_total_duration_minutes=plan_data.get("estimated_total_duration_minutes", 0),
            risks=risks,
            validation_points=validation_points,
        )

        return plan

    def _create_fallback_plan(self, task: Any) -> Dict[str, Any]:
        """Crée un plan fallback minimal si le LLM échoue."""
        return {
            "plan_id": f"plan_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            "task_id": task.task_id,
            "subtasks": [
                {
                    "subtask_id": "subtask_001",
                    "title": "Analyze requirements",
                    "description": "Analyze and understand the task requirements",
                    "complexity": "low",
                    "estimated_duration_minutes": 30,
                    "dependencies": [],
                    "validation_criteria": "Requirements documented",
                    "files_impacted": [],
                },
                {
                    "subtask_id": "subtask_002",
                    "title": "Implement solution",
                    "description": task.description,
                    "complexity": "medium",
                    "estimated_duration_minutes": 120,
                    "dependencies": ["subtask_001"],
                    "validation_criteria": "Tests pass",
                    "files_impacted": [],
                },
            ],
            "estimated_total_duration_minutes": 150,
        }

    def _validate_and_improve_plan(self, plan: Plan) -> Plan:
        """Valide et améliore le plan via réflexion."""
        reflection_prompt = self.format_prompt(
            "reflection_prompt",
            current_plan=plan.model_dump_json(indent=2),
        )

        system_prompt = self.get_prompt("system_prompt")
        if not system_prompt:
            system_prompt = "Tu es un Planning Agent expert."

        response = self.invoke_llm(system_prompt, reflection_prompt)

        # Parser l'évaluation
        try:
            evaluation = yaml.safe_load(response)
            overall_score = evaluation.get("evaluation", {}).get("overall_score", 0.0)

            if overall_score < 0.75:
                # Plan needs improvement - log warning
                print(f"[WARNING] Plan quality score: {overall_score}")

        except yaml.YAMLError:
            pass

        return plan
