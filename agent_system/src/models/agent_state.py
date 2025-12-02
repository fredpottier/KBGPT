"""
Data models pour l'état de l'orchestrateur LangGraph (AgentState).
"""
from typing import Any, Dict, List, Optional, TypedDict, Annotated
from datetime import datetime
import operator

from .task import Task, TaskStatus
from .plan import Plan
from .report import DevReport, ControlReport


class AgentState(TypedDict, total=False):
    """
    État partagé entre tous les nodes du graphe LangGraph.

    Cet état est passé de node en node et peut être modifié par chaque agent.
    """

    # Task et contexte initial
    task: Task
    """Tâche principale à exécuter"""

    context: Dict[str, Any]
    """Contexte additionnel pour l'exécution"""

    # Planning
    plan: Optional[Plan]
    """Plan d'exécution créé par le Planning Agent"""

    planning_iterations: Annotated[int, operator.add]
    """Nombre d'itérations de planning effectuées"""

    # Développement
    current_subtask_id: Optional[str]
    """ID de la sous-tâche actuellement en cours"""

    dev_reports: Annotated[List[DevReport], operator.add]
    """Liste des rapports du Dev Agent (un par sous-tâche)"""

    code_changes: Dict[str, Any]
    """Changements de code accumulés"""

    # Control et validation
    control_reports: Annotated[List[ControlReport], operator.add]
    """Liste des rapports du Control Agent"""

    validation_passed: bool
    """Indique si la validation finale est passée"""

    # Orchestration
    current_node: str
    """Node actuellement actif dans le graphe"""

    iteration_count: Annotated[int, operator.add]
    """Nombre d'itérations du graphe"""

    errors: Annotated[List[Dict[str, Any]], operator.add]
    """Liste des erreurs rencontrées"""

    warnings: Annotated[List[str], operator.add]
    """Liste des warnings émis"""

    # Human in the loop
    human_feedback: Optional[Dict[str, Any]]
    """Feedback humain si nécessaire"""

    requires_human_review: bool
    """Indique si une revue humaine est requise"""

    # Métadonnées
    started_at: datetime
    """Date/heure de début d'exécution"""

    metadata: Dict[str, Any]
    """Métadonnées additionnelles"""

    # Checkpointing
    task_checkpoint_id: Optional[str]
    """ID du checkpoint actuel (pour reprise)"""


def create_initial_state(
    task: Task,
    context: Optional[Dict[str, Any]] = None
) -> AgentState:
    """
    Crée l'état initial pour l'orchestrateur.

    Args:
        task: Tâche à exécuter
        context: Contexte additionnel (optionnel)

    Returns:
        État initial pour LangGraph
    """
    return AgentState(
        task=task,
        context=context or {},
        plan=None,
        planning_iterations=0,
        current_subtask_id=None,
        dev_reports=[],
        code_changes={},
        control_reports=[],
        validation_passed=False,
        current_node="planning",
        iteration_count=0,
        errors=[],
        warnings=[],
        human_feedback=None,
        requires_human_review=False,
        started_at=datetime.utcnow(),
        metadata={},
        task_checkpoint_id=None,
    )


def update_state_with_plan(state: AgentState, plan: Plan) -> AgentState:
    """Met à jour l'état avec un nouveau plan."""
    state["plan"] = plan
    state["planning_iterations"] += 1
    return state


def update_state_with_dev_report(state: AgentState, report: DevReport) -> AgentState:
    """Met à jour l'état avec un rapport Dev."""
    state["dev_reports"].append(report)

    # Marquer la sous-tâche comme complétée si succès
    if state["plan"] and report.status.value == "success":
        subtask = state["plan"].get_subtask_by_id(report.subtask_id)
        if subtask:
            subtask.status = TaskStatus.COMPLETED
            subtask.completed_at = datetime.utcnow()

    return state


def update_state_with_control_report(
    state: AgentState,
    report: ControlReport
) -> AgentState:
    """Met à jour l'état avec un rapport Control."""
    state["control_reports"].append(report)

    # Déterminer si validation passed basé sur la décision
    if report.decision.value == "approved":
        state["validation_passed"] = True
    elif report.decision.value == "rejected":
        state["validation_passed"] = False
        state["requires_human_review"] = True

    return state


def add_error_to_state(
    state: AgentState,
    error: Exception,
    context: Optional[Dict[str, Any]] = None
) -> AgentState:
    """Ajoute une erreur à l'état."""
    error_entry = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.utcnow().isoformat(),
        "context": context or {},
    }
    state["errors"].append(error_entry)
    return state


def add_warning_to_state(state: AgentState, warning: str) -> AgentState:
    """Ajoute un warning à l'état."""
    state["warnings"].append(warning)
    return state
