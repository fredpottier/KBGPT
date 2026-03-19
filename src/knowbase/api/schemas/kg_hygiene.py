"""Schemas Pydantic pour l'API KG Hygiene."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class HygieneRunRequest(BaseModel):
    """Requête pour lancer un run d'hygiène."""

    dry_run: bool = Field(default=False, description="Preview sans modification")
    layers: List[int] = Field(default=[1], description="Couches à exécuter (1, 2, ou [1,2])")
    scope: str = Field(default="tenant", description="Scope: 'tenant' ou 'document_set'")
    scope_params: Optional[Dict] = Field(
        default=None,
        description="Params du scope (ex: {doc_ids: ['xxx']})",
    )
    auto_apply_threshold: float = Field(
        default=0.9,
        description="Seuil auto-apply L2 (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )


class HygieneActionResponse(BaseModel):
    """Réponse pour une action d'hygiène."""

    action_id: str
    action_type: str
    target_node_id: str
    target_node_type: str
    before_state: dict = Field(default_factory=dict)
    after_state: dict = Field(default_factory=dict)
    layer: int
    confidence: float
    reason: str
    rule_name: str
    batch_id: str
    scope: str
    status: str
    decision_source: str
    applied_at: Optional[str] = None
    rolled_back_at: Optional[str] = None
    tenant_id: str

    class Config:
        from_attributes = True


class HygieneRunResponse(BaseModel):
    """Réponse d'un run d'hygiène."""

    batch_id: str
    total_actions: int = 0
    applied: int = 0
    proposed: int = 0
    skipped_already_suppressed: int = 0
    dry_run: bool = False
    errors: List[str] = Field(default_factory=list)
    actions: List[HygieneActionResponse] = Field(default_factory=list)


class HygieneRunStatusResponse(BaseModel):
    """Statut d'un run en cours ou terminé."""

    batch_id: str
    status: str  # "running" | "completed" | "failed"
    total_actions: int = 0
    applied: int = 0
    proposed: int = 0
    skipped_already_suppressed: int = 0
    dry_run: bool = False
    errors: List[str] = Field(default_factory=list)
    actions: List[HygieneActionResponse] = Field(default_factory=list)
    progress: Optional[str] = None  # ex: "singleton_noise (3/20 batches)"


class HygieneActionsListResponse(BaseModel):
    """Liste paginée d'actions."""

    actions: List[HygieneActionResponse]
    total: int
    limit: int
    offset: int


class HygieneStatsResponse(BaseModel):
    """Stats agrégées."""

    total: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_layer: Dict[str, int] = Field(default_factory=dict)
    by_type: Dict[str, int] = Field(default_factory=dict)


class RollbackResponse(BaseModel):
    """Réponse de rollback."""

    success: bool
    action_id: str
    relations_restored: int = 0
    relations_failed: int = 0
    failed_reasons: List[str] = Field(default_factory=list)
    partial: bool = False


class BatchRollbackResponse(BaseModel):
    """Réponse de rollback batch."""

    results: List[Dict]
    total_rolled_back: int = 0
    total_failed: int = 0
