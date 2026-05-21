"""V5 ReasoningAgent — Plan-then-execute (Sprint S4.3).

⚠️ DEPRECATED (A3.6, 2026-05-21) — Réf ADR_PARSE_EVALUATE_RUNTIME §10.2.

Ce module sera supprimé une fois :
- Bench A3.8 validé (gates GA3-5/6/7 atteints)
- Phase B cross-domain validée
- V5.1 retiré comme endpoint de référence

Remplacé par : `runtime_a3.schemas.PlanOutput` + `runtime_a3.plan.plan()`
(mapping déterministe sub_goal → tool, sans LLM dans Plan).

⚠️ NE PAS étendre. Pour nouveaux développements, voir runtime_a3/.

---

ADR V1.5 §3e : pour les shapes complexes (comparison, lifecycle, multi_hop,
causal), forcer la 1ère itération à produire un plan structuré Pydantic avant
exécution. Anthropic Deep Research et Perplexity ont prouvé qu'un plan-then-
execute économise 30-40% des tokens.

Schema :
    ExecutionPlan
        steps : list[PlanStep]
        max_iter_estimated : int (budget annoncé par l'agent au planning)
        replanning_allowed : bool (default True)
        notes : str (rationale du plan)

    PlanStep
        intent : str (description courte de l'étape, ex: "find sections about X")
        tool : str (nom du tool, doit être dans le registry)
        args : dict (params du tool call)
        expected_evidence_shape : str (description du gain attendu)
        critical : bool (si True et step fail → replan)
        optional : bool (si True et step fail → skip)

Politique d'échec :
- step optionnel échoue → skip → continue
- step critique échoue → trigger replan (1 max)
- tous échouent → abort

Charte domain-agnostic : aucun exemple corpus-spécifique dans le schema. Le
prompt LLM (rédigé en S4.5 final) restera générique.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# Warning DEPRECATED (A3.6, 2026-05-21) — émis une fois par import
if not globals().get("_DEPRECATED_WARNED", False):
    logger.warning(
        "⚠️ DEPRECATED module loaded: runtime_v5.agent.execution_plan. "
        "Replaced by runtime_a3 PlanOutput + plan() (deterministic, no LLM). "
        "Removal scheduled post-A3.8. "
        "See doc/ongoing/POST_A36_V51_SUPPRESSIONS_AUDIT_2026-05-21.md"
    )
    _DEPRECATED_WARNED = True


class PlanStatus(str, Enum):
    """État d'un plan en cours d'exécution."""
    DRAFT = "draft"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIAL = "partial"  # certains steps optionnels skippés
    REPLANNED = "replanned"
    ABORTED = "aborted"


class StepStatus(str, Enum):
    """État d'un step individuel."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# Shapes pour lesquels plan-then-execute est OBLIGATOIRE
PLAN_REQUIRED_SHAPES = frozenset({
    "comparison", "lifecycle", "multi_hop", "causal",
})


def is_plan_required(answer_shape: Optional[str]) -> bool:
    """Returns True si plan-then-execute est obligatoire pour ce shape."""
    if not answer_shape:
        return False
    return answer_shape.lower() in PLAN_REQUIRED_SHAPES


# ─── PlanStep ────────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    """Un step du plan d'exécution."""
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=False)

    intent: str = Field(
        ..., min_length=5, max_length=500,
        description="Short description of what this step achieves",
    )
    tool: str = Field(
        ..., min_length=1, max_length=64,
        description="Tool name (must exist in ToolRegistry at execution time)",
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool call arguments (validated by ToolCallSanitizer)",
    )
    expected_evidence_shape: str = Field(
        ..., min_length=3, max_length=300,
        description="What the step is expected to return (evidence type description)",
    )
    critical: bool = Field(
        default=True,
        description="If True and step fails, triggers replan; if False, can be skipped",
    )
    optional: bool = Field(
        default=False,
        description="If True, step can be skipped on failure without replan",
    )

    # Runtime state (mutated during execution)
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None
    evidence_summary: Optional[str] = Field(
        default=None,
        description="Short summary of evidence retrieved at this step (post-exec)",
    )

    @field_validator("tool")
    @classmethod
    def _validate_tool_name(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError(f"tool name must be snake_case alphanumeric: '{v}'")
        return v

    def mark_running(self) -> None:
        self.status = StepStatus.RUNNING

    def mark_succeeded(self, evidence_summary: str = "") -> None:
        self.status = StepStatus.SUCCEEDED
        self.evidence_summary = evidence_summary[:300] if evidence_summary else None

    def mark_failed(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.error = error[:500] if error else "unknown"

    def mark_skipped(self, reason: str = "") -> None:
        self.status = StepStatus.SKIPPED
        self.error = reason[:500] if reason else None


# ─── ExecutionPlan ───────────────────────────────────────────────────────────


class ExecutionPlan(BaseModel):
    """Plan d'exécution agentic (mutable runtime)."""
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=False)

    steps: list[PlanStep] = Field(..., min_length=1, max_length=20)
    max_iter_estimated: int = Field(
        ..., ge=1, le=12,
        description="LLM's own estimate of iterations required",
    )
    replanning_allowed: bool = Field(default=True)
    notes: str = Field(default="", max_length=2000)

    # Runtime state
    status: PlanStatus = PlanStatus.DRAFT
    current_step_idx: int = 0
    n_replans_used: int = 0
    max_replans: int = Field(default=1, ge=0, le=3)

    # ─── Step navigation ─────────────────────────────────────────────────────

    def get_current_step(self) -> Optional[PlanStep]:
        if self.current_step_idx >= len(self.steps):
            return None
        return self.steps[self.current_step_idx]

    def advance(self) -> Optional[PlanStep]:
        """Passe au step suivant. Returns le nouveau current_step (ou None si fini)."""
        self.current_step_idx += 1
        return self.get_current_step()

    def is_complete(self) -> bool:
        return self.current_step_idx >= len(self.steps)

    # ─── Outcome assessment ──────────────────────────────────────────────────

    def needs_replan(self) -> bool:
        """True si un step critique a failed ET replanning encore autorisé."""
        if not self.replanning_allowed or self.n_replans_used >= self.max_replans:
            return False
        for step in self.steps:
            if step.status == StepStatus.FAILED and step.critical and not step.optional:
                return True
        return False

    def all_critical_failed(self) -> bool:
        """True si tous les steps critiques ont échoué → abort."""
        critical_steps = [s for s in self.steps if s.critical and not s.optional]
        if not critical_steps:
            return False
        return all(s.status == StepStatus.FAILED for s in critical_steps)

    def n_steps_succeeded(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.SUCCEEDED)

    def n_steps_failed(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    def n_steps_skipped(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.SKIPPED)

    # ─── Finalize ────────────────────────────────────────────────────────────

    def finalize(self) -> PlanStatus:
        """Calcule le statut final du plan post-exécution."""
        if self.all_critical_failed():
            self.status = PlanStatus.ABORTED
        elif self.n_steps_failed() > 0 or self.n_steps_skipped() > 0:
            self.status = PlanStatus.PARTIAL
        else:
            self.status = PlanStatus.COMPLETED
        return self.status

    def increment_replan(self) -> None:
        """Incrémente le compteur de replans (à appeler quand on génère un nouveau plan)."""
        self.n_replans_used += 1
        self.status = PlanStatus.REPLANNED

    # ─── Summary ─────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """État compact du plan pour observability."""
        return {
            "status": self.status.value,
            "n_steps_total": len(self.steps),
            "n_steps_succeeded": self.n_steps_succeeded(),
            "n_steps_failed": self.n_steps_failed(),
            "n_steps_skipped": self.n_steps_skipped(),
            "current_step_idx": self.current_step_idx,
            "n_replans_used": self.n_replans_used,
            "max_replans": self.max_replans,
            "is_complete": self.is_complete(),
            "needs_replan": self.needs_replan(),
        }


# ─── Validation against ToolRegistry ─────────────────────────────────────────


def validate_plan_against_registry(plan: ExecutionPlan, registry) -> list[str]:
    """Valide que tous les tools référencés dans le plan existent dans le registry.

    Args:
        plan : ExecutionPlan à valider
        registry : ToolRegistry source de vérité

    Returns:
        Liste des erreurs (chaîne vide si tout est OK)
    """
    errors = []
    for i, step in enumerate(plan.steps):
        spec = registry.get(step.tool)
        if spec is None:
            errors.append(f"step[{i}].tool='{step.tool}' not in registry")
        elif spec.is_retired:
            errors.append(f"step[{i}].tool='{step.tool}' is retired: {spec.retired_reason}")
    return errors
