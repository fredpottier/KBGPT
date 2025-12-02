"""
Data models pour les plans d'exécution.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from .task import Subtask, TaskStatus


class RiskLevel(str, Enum):
    """Niveau de risque."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Risk(BaseModel):
    """Modèle d'un risque identifié."""

    risk_id: str = Field(..., description="Identifiant unique du risque")
    description: str = Field(..., description="Description du risque")
    probability: RiskLevel = Field(..., description="Probabilité d'occurrence")
    impact: RiskLevel = Field(..., description="Impact si le risque se réalise")
    mitigation: str = Field(..., description="Plan de mitigation")
    owner: Optional[str] = Field(
        default=None,
        description="Responsable de la mitigation"
    )


class ValidationPoint(BaseModel):
    """Modèle d'un point de validation."""

    validation_id: str = Field(..., description="Identifiant du point de validation")
    after_subtask_id: str = Field(
        ...,
        description="ID de la sous-tâche après laquelle valider"
    )
    check_description: str = Field(
        ...,
        description="Description de la vérification à effectuer"
    )
    criteria: List[str] = Field(
        default_factory=list,
        description="Critères de validation"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Statut de cette validation"
    )
    validated_at: Optional[datetime] = Field(
        default=None,
        description="Date/heure de validation"
    )
    validated_by: Optional[str] = Field(
        default=None,
        description="Agent/utilisateur ayant validé"
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Résultat de la validation"
    )


class Plan(BaseModel):
    """Modèle d'un plan d'exécution."""

    plan_id: str = Field(..., description="Identifiant unique du plan")
    task_id: str = Field(..., description="ID de la tâche associée")
    task_description: str = Field(..., description="Description de la tâche")
    subtasks: List[Subtask] = Field(
        default_factory=list,
        description="Liste des sous-tâches"
    )
    dependencies_graph: str = Field(
        default="",
        description="Représentation ASCII du graphe de dépendances"
    )
    critical_path: List[str] = Field(
        default_factory=list,
        description="Chemin critique (liste d'IDs de sous-tâches)"
    )
    estimated_total_duration_minutes: int = Field(
        default=0,
        ge=0,
        description="Durée totale estimée en minutes"
    )
    risks: List[Risk] = Field(
        default_factory=list,
        description="Risques identifiés"
    )
    validation_points: List[ValidationPoint] = Field(
        default_factory=list,
        description="Points de validation"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date/heure de création du plan"
    )
    created_by: str = Field(
        default="planning_agent",
        description="Créateur du plan"
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Version du plan (pour itérations)"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Statut global du plan"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )

    @field_validator('plan_id')
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        """Valide le format de l'ID de plan."""
        if not v.startswith('plan_'):
            raise ValueError("plan_id must start with 'plan_'")
        return v

    @field_validator('task_id')
    @classmethod
    def validate_task_id(cls, v: str) -> str:
        """Valide le format de l'ID de tâche."""
        if not v.startswith('task_'):
            raise ValueError("task_id must start with 'task_'")
        return v

    def get_subtask_by_id(self, subtask_id: str) -> Optional[Subtask]:
        """Récupère une sous-tâche par son ID."""
        for subtask in self.subtasks:
            if subtask.subtask_id == subtask_id:
                return subtask
        return None

    def get_ready_subtasks(self) -> List[Subtask]:
        """Retourne les sous-tâches prêtes à être exécutées (dépendances satisfaites)."""
        ready = []
        completed_ids = {st.subtask_id for st in self.subtasks if st.status == TaskStatus.COMPLETED}

        for subtask in self.subtasks:
            if subtask.status == TaskStatus.PENDING:
                # Vérifier si toutes les dépendances sont complétées
                if all(dep_id in completed_ids for dep_id in subtask.dependencies):
                    ready.append(subtask)

        return ready

    def get_progress_percentage(self) -> float:
        """Calcule le pourcentage de complétion du plan."""
        if not self.subtasks:
            return 0.0

        completed = sum(1 for st in self.subtasks if st.status == TaskStatus.COMPLETED)
        return (completed / len(self.subtasks)) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit le modèle en dictionnaire."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Crée un Plan depuis un dictionnaire."""
        return cls.model_validate(data)
