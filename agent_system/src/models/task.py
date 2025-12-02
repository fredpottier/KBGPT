"""
Data models pour les tâches (Task, Subtask).
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TaskPriority(str, Enum):
    """Priorité d'une tâche."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    """Statut d'une tâche."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskComplexity(str, Enum):
    """Complexité d'une tâche."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Subtask(BaseModel):
    """Modèle d'une sous-tâche."""

    subtask_id: str = Field(..., description="Identifiant unique de la sous-tâche")
    title: str = Field(..., description="Titre court de la sous-tâche")
    description: str = Field(..., description="Description détaillée de la sous-tâche")
    complexity: TaskComplexity = Field(
        default=TaskComplexity.MEDIUM,
        description="Complexité de la sous-tâche"
    )
    estimated_duration_minutes: int = Field(
        default=60,
        ge=1,
        description="Durée estimée en minutes"
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="Liste des IDs de sous-tâches dont celle-ci dépend"
    )
    validation_criteria: str = Field(
        ...,
        description="Critères pour valider que la sous-tâche est terminée"
    )
    files_impacted: List[str] = Field(
        default_factory=list,
        description="Liste des fichiers impactés par cette sous-tâche"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Statut actuel de la sous-tâche"
    )
    assigned_agent: Optional[str] = Field(
        default=None,
        description="Agent assigné à cette sous-tâche"
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Date/heure de début d'exécution"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Date/heure de complétion"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Message d'erreur si la sous-tâche a échoué"
    )

    @field_validator('subtask_id')
    @classmethod
    def validate_subtask_id(cls, v: str) -> str:
        """Valide le format de l'ID de sous-tâche."""
        if not v.startswith('subtask_'):
            raise ValueError("subtask_id must start with 'subtask_'")
        return v


class Task(BaseModel):
    """Modèle d'une tâche principale."""

    task_id: str = Field(..., description="Identifiant unique de la tâche")
    title: str = Field(..., description="Titre de la tâche")
    description: str = Field(..., description="Description détaillée de la tâche")
    requirements: List[str] = Field(
        default_factory=list,
        description="Liste des requirements de la tâche"
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Contexte additionnel pour la tâche"
    )
    priority: TaskPriority = Field(
        default=TaskPriority.MEDIUM,
        description="Priorité de la tâche"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Statut actuel de la tâche"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date/heure de création"
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Date/heure de début d'exécution"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Date/heure de complétion"
    )
    created_by: str = Field(
        default="user",
        description="Créateur de la tâche"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )

    @field_validator('task_id')
    @classmethod
    def validate_task_id(cls, v: str) -> str:
        """Valide le format de l'ID de tâche."""
        if not v.startswith('task_'):
            raise ValueError("task_id must start with 'task_'")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convertit le modèle en dictionnaire."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Crée une Task depuis un dictionnaire."""
        return cls.model_validate(data)
