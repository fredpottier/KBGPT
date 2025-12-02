"""
Models pour la gestion de projets complets.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pathlib import Path
import yaml


class ProjectStatus(str, Enum):
    """Status d'un projet."""
    PENDING = "pending"
    PARSING = "parsing"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ProjectTaskStatus(str, Enum):
    """Status d'une tache projet."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ProjectTask:
    """Une tache extraite du document projet."""

    task_id: str
    title: str
    description: str
    requirements: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # IDs des taches prerequises
    priority: str = "medium"  # low, medium, high, critical
    status: ProjectTaskStatus = ProjectTaskStatus.PENDING

    # Resultats execution
    plan_id: Optional[str] = None
    dev_reports: List[str] = field(default_factory=list)  # IDs des rapports
    control_reports: List[str] = field(default_factory=list)
    validation_passed: bool = False
    error_message: Optional[str] = None

    # Timestamps
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "requirements": self.requirements,
            "dependencies": self.dependencies,
            "priority": self.priority,
            "status": self.status.value,
            "plan_id": self.plan_id,
            "dev_reports": self.dev_reports,
            "control_reports": self.control_reports,
            "validation_passed": self.validation_passed,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectTask":
        """Cree depuis un dictionnaire."""
        data = data.copy()
        data["status"] = ProjectTaskStatus(data["status"])
        if data.get("started_at"):
            data["started_at"] = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            data["completed_at"] = datetime.fromisoformat(data["completed_at"])
        return cls(**data)


@dataclass
class ProjectPlan:
    """Plan d'un projet complet."""

    project_id: str
    title: str
    description: str
    document_path: str

    # Taches extraites
    tasks: List[ProjectTask] = field(default_factory=list)

    # Configuration Git
    git_branch: str = ""
    base_branch: str = "main"

    # Requirements globaux
    global_requirements: List[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    status: ProjectStatus = ProjectStatus.PENDING

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "document_path": self.document_path,
            "tasks": [task.to_dict() for task in self.tasks],
            "git_branch": self.git_branch,
            "base_branch": self.base_branch,
            "global_requirements": self.global_requirements,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectPlan":
        """Cree depuis un dictionnaire."""
        data = data.copy()
        data["tasks"] = [ProjectTask.from_dict(t) for t in data["tasks"]]
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["status"] = ProjectStatus(data["status"])
        return cls(**data)

    def save(self, output_path: Path) -> None:
        """Sauvegarde le plan."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load(cls, input_path: Path) -> "ProjectPlan":
        """Charge un plan."""
        with open(input_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def get_task_by_id(self, task_id: str) -> Optional[ProjectTask]:
        """Recupere une tache par ID."""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_ready_tasks(self) -> List[ProjectTask]:
        """Retourne les taches pretes a executer (dependances satisfaites)."""
        ready = []
        for task in self.tasks:
            if task.status != ProjectTaskStatus.PENDING:
                continue

            # Verifier toutes les dependances sont completes
            deps_satisfied = True
            for dep_id in task.dependencies:
                dep_task = self.get_task_by_id(dep_id)
                if not dep_task or dep_task.status != ProjectTaskStatus.COMPLETED:
                    deps_satisfied = False
                    break

            if deps_satisfied:
                ready.append(task)

        return ready

    def get_execution_order(self) -> List[ProjectTask]:
        """Retourne l'ordre d'execution des taches (topological sort)."""
        # Simple implementation: tri par dependances
        ordered = []
        remaining = self.tasks.copy()

        while remaining:
            # Trouver taches sans dependances non satisfaites
            ready = []
            for task in remaining:
                deps_satisfied = all(
                    self.get_task_by_id(dep_id) in ordered
                    for dep_id in task.dependencies
                )
                if deps_satisfied:
                    ready.append(task)

            if not ready:
                # Cycle de dependances detecte
                raise ValueError("Circular dependency detected in project tasks")

            # Trier par priorite
            priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            ready.sort(key=lambda t: priority_order.get(t.priority, 2))

            ordered.extend(ready)
            for task in ready:
                remaining.remove(task)

        return ordered


@dataclass
class ProjectState:
    """Etat d'execution d'un projet (pour checkpoint/resume)."""

    project_plan: ProjectPlan
    current_task_index: int = 0
    execution_started_at: Optional[datetime] = None
    execution_completed_at: Optional[datetime] = None

    # Logs d'execution
    execution_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "project_plan": self.project_plan.to_dict(),
            "current_task_index": self.current_task_index,
            "execution_started_at": self.execution_started_at.isoformat() if self.execution_started_at else None,
            "execution_completed_at": self.execution_completed_at.isoformat() if self.execution_completed_at else None,
            "execution_log": self.execution_log,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectState":
        """Cree depuis un dictionnaire."""
        data = data.copy()
        data["project_plan"] = ProjectPlan.from_dict(data["project_plan"])
        if data.get("execution_started_at"):
            data["execution_started_at"] = datetime.fromisoformat(data["execution_started_at"])
        if data.get("execution_completed_at"):
            data["execution_completed_at"] = datetime.fromisoformat(data["execution_completed_at"])
        return cls(**data)

    def save_checkpoint(self, checkpoint_path: Path) -> None:
        """Sauvegarde un checkpoint."""
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load_checkpoint(cls, checkpoint_path: Path) -> "ProjectState":
        """Charge un checkpoint."""
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def log_event(self, event_type: str, message: str, **kwargs) -> None:
        """Ajoute un evenement au log."""
        self.execution_log.append({
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "message": message,
            **kwargs
        })


@dataclass
class ProjectReport:
    """Rapport final d'execution d'un projet."""

    project_id: str
    project_title: str
    status: ProjectStatus

    # Statistiques
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int

    # Details des taches
    task_summaries: List[Dict[str, Any]] = field(default_factory=list)

    # Git info
    git_branch: str = ""
    git_commits: List[str] = field(default_factory=list)

    # Temps d'execution
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Logs
    execution_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "project_id": self.project_id,
            "project_title": self.project_title,
            "status": self.status.value,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "skipped_tasks": self.skipped_tasks,
            "task_summaries": self.task_summaries,
            "git_branch": self.git_branch,
            "git_commits": self.git_commits,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "execution_log": self.execution_log,
        }

    def save(self, output_path: Path) -> None:
        """Sauvegarde le rapport."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)

    def generate_markdown_report(self) -> str:
        """Genere un rapport markdown."""
        lines = [
            f"# Project Report: {self.project_title}",
            f"",
            f"**Project ID**: {self.project_id}",
            f"**Status**: {self.status.value.upper()}",
            f"**Started**: {self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else 'N/A'}",
            f"**Completed**: {self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else 'N/A'}",
            f"**Duration**: {self.duration_seconds:.1f}s",
            f"",
            f"## Summary",
            f"",
            f"- Total Tasks: {self.total_tasks}",
            f"- Completed: {self.completed_tasks}",
            f"- Failed: {self.failed_tasks}",
            f"- Skipped: {self.skipped_tasks}",
            f"",
            f"## Git Information",
            f"",
            f"- Branch: `{self.git_branch}`",
            f"- Commits: {len(self.git_commits)}",
            f"",
            f"## Task Details",
            f"",
        ]

        for task_summary in self.task_summaries:
            status_emoji = {
                "completed": "✅",
                "failed": "❌",
                "skipped": "⏭️",
                "pending": "⏳",
            }.get(task_summary.get("status", "pending"), "❓")

            lines.append(f"### {status_emoji} {task_summary['title']}")
            lines.append(f"")
            lines.append(f"- **Status**: {task_summary['status']}")
            lines.append(f"- **Task ID**: {task_summary['task_id']}")
            if task_summary.get("error_message"):
                lines.append(f"- **Error**: {task_summary['error_message']}")
            lines.append(f"")

        return "\n".join(lines)
