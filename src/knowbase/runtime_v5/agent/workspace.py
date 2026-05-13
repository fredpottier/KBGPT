"""V5 ReasoningAgent — Workspace V1 schema (Sprint S4.7).

ADR V1.5 §3e : workspace Pydantic versionné, sérialisable, replay-able.

Use cases :
- **Audit** : replay une session V5 pour comprendre ce que l'agent a fait
- **Debugging** : reproduire un bug à partir d'un workspace snapshot
- **Régression bench** : sauvegarder workspaces, rejouer post-V5.2 pour comparer
- **Cache versioning §3c** : workspace replay store pinned au doc_version_snapshot

Schema strict (Pydantic V2, ConfigDict extra='forbid') :

    Workspace(version="v1", ...)
        # Identity
        request_id : str (UUID4)
        tenant_id : str
        question : str
        answer_shape : str | None (du classifier S0.5)

        # Execution state
        plan : ExecutionPlan | None
        loop_signatures : list[LoopSignatureSnapshot]
        budgets_snapshot : BudgetSnapshot
        cancellation_snapshot : dict | None

        # Evidence + tool calls
        tool_calls : list[ToolCallRecord]
        evidence_collected : list[EvidenceItem]

        # Final answer
        final_answer : str | None
        epistemic_status : Literal["complete", "partial", "abstain", "aborted"]
        stop_reason : str
        latency_s : float

        # Provenance (pinned for audit reproducibility)
        doc_version_snapshot : dict[doc_id, doc_version]
        v5_version : str (semver)
        created_at : datetime
        finalized_at : datetime | None

Domain-agnostic strict : aucun champ corpus-spécifique. evidence est typé
EvidenceType (enum existant ToolRegistry).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from knowbase.runtime_v5.agent.execution_plan import ExecutionPlan
from knowbase.runtime_v5.tools.registry import EvidenceType


WORKSPACE_SCHEMA_VERSION = "v1"


class EpistemicStatus(str, Enum):
    """État épistémique final de la réponse."""
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSTAIN = "abstain"  # agent a refusé de répondre (info absente, false_premise)
    ABORTED = "aborted"  # cancellation, budget exceeded, error


# ─── ToolCallRecord ──────────────────────────────────────────────────────────


class ToolCallRecord(BaseModel):
    """Trace d'un appel à un tool (input + output + métadonnées)."""
    model_config = ConfigDict(extra="forbid")

    iter_idx: int = Field(..., ge=0)
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = Field(default="", max_length=1000)
    result_chars: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    error: Optional[str] = Field(default=None, max_length=500)
    repair_applied: bool = Field(
        default=False,
        description="True si ToolCallSanitizer a réparé les args",
    )


# ─── EvidenceItem ────────────────────────────────────────────────────────────


class EvidenceItem(BaseModel):
    """Une pièce d'évidence collectée pendant la résolution."""
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:12]}")
    evidence_type: EvidenceType
    doc_id: str
    section_id: Optional[str] = None
    text_excerpt: str = Field(default="", max_length=2000)
    source_tool: str = Field(..., description="Tool that retrieved this evidence")
    iter_idx: int = Field(..., ge=0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# ─── Snapshots (compact serializable) ───────────────────────────────────────


class LoopSignatureSnapshot(BaseModel):
    """Snapshot compact d'une LoopSignature pour serialization workspace."""
    model_config = ConfigDict(extra="forbid")

    iter_idx: int
    tool: str
    normalized_args: str
    evidence_gain: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)


class BudgetSnapshot(BaseModel):
    """Snapshot final des budgets (post-execution)."""
    model_config = ConfigDict(extra="forbid")

    shape: Optional[str] = None
    iterations: int = 0
    tool_calls: int = 0
    retrieved_chars: int = 0
    output_tokens: int = 0
    soft_caps: dict[str, int] = Field(default_factory=dict)
    hard_caps: dict[str, int] = Field(default_factory=dict)


# ─── Workspace ───────────────────────────────────────────────────────────────


class Workspace(BaseModel):
    """V5 ReasoningAgent workspace versionné.

    Champs immutables après finalisation : `finalized_at` est set par
    `finalize()`. Toute mutation après devrait être interdite (à enforcer
    en couche API).
    """
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=False)

    # ─── Identity / versioning ───────────────────────────────────────────────
    schema_version: str = Field(default=WORKSPACE_SCHEMA_VERSION)
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:16]}")
    tenant_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1, max_length=4000)
    answer_shape: Optional[str] = Field(default=None, max_length=64)
    v5_version: str = Field(default="0.5.0", description="OSMOSIS V5 semver")

    # ─── Execution state ─────────────────────────────────────────────────────
    plan: Optional[ExecutionPlan] = None
    loop_signatures: list[LoopSignatureSnapshot] = Field(default_factory=list)
    budgets_snapshot: BudgetSnapshot = Field(default_factory=BudgetSnapshot)
    cancellation_snapshot: Optional[dict] = None

    # ─── Evidence + tool calls ───────────────────────────────────────────────
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    evidence_collected: list[EvidenceItem] = Field(default_factory=list)

    # ─── Final answer ────────────────────────────────────────────────────────
    final_answer: Optional[str] = Field(default=None, max_length=20000)
    epistemic_status: Optional[EpistemicStatus] = None
    stop_reason: str = Field(default="", max_length=300)
    latency_s: float = Field(default=0.0, ge=0.0)

    # ─── Provenance (pinned for audit reproducibility) ───────────────────────
    doc_version_snapshot: dict[str, int] = Field(
        default_factory=dict,
        description="Mapping doc_id → doc_version au début de la requête",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finalized_at: Optional[datetime] = None

    # ─── Mutations runtime ──────────────────────────────────────────────────

    def record_tool_call(
        self,
        iter_idx: int,
        tool_name: str,
        args: dict[str, Any],
        result_summary: str = "",
        result_chars: int = 0,
        latency_ms: float = 0.0,
        error: Optional[str] = None,
        repair_applied: bool = False,
    ) -> ToolCallRecord:
        rec = ToolCallRecord(
            iter_idx=iter_idx,
            tool_name=tool_name,
            args=args,
            result_summary=result_summary[:1000],
            result_chars=result_chars,
            latency_ms=latency_ms,
            error=error,
            repair_applied=repair_applied,
        )
        self.tool_calls.append(rec)
        return rec

    def add_evidence(
        self,
        evidence_type: EvidenceType,
        doc_id: str,
        source_tool: str,
        iter_idx: int,
        section_id: Optional[str] = None,
        text_excerpt: str = "",
        confidence: Optional[float] = None,
    ) -> EvidenceItem:
        ev = EvidenceItem(
            evidence_type=evidence_type,
            doc_id=doc_id,
            section_id=section_id,
            text_excerpt=text_excerpt[:2000],
            source_tool=source_tool,
            iter_idx=iter_idx,
            confidence=confidence,
        )
        self.evidence_collected.append(ev)
        return ev

    def record_loop_signature(
        self,
        iter_idx: int,
        tool: str,
        normalized_args: str,
        evidence_gain: float,
        novelty_score: float,
    ) -> LoopSignatureSnapshot:
        snap = LoopSignatureSnapshot(
            iter_idx=iter_idx,
            tool=tool,
            normalized_args=normalized_args[:500],
            evidence_gain=max(0.0, min(1.0, evidence_gain)),
            novelty_score=max(0.0, min(1.0, novelty_score)),
        )
        self.loop_signatures.append(snap)
        return snap

    def finalize(
        self,
        final_answer: str,
        epistemic_status: EpistemicStatus,
        stop_reason: str,
        latency_s: float,
    ) -> None:
        """Set état final + finalized_at."""
        self.final_answer = final_answer[:20000]
        self.epistemic_status = epistemic_status
        self.stop_reason = stop_reason[:300]
        self.latency_s = max(0.0, latency_s)
        self.finalized_at = datetime.utcnow()

    # ─── Serialization ──────────────────────────────────────────────────────

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Sérialise en JSON string (datetime ISO)."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, s: str) -> Workspace:
        """Désérialise depuis JSON string."""
        return cls.model_validate_json(s)

    @classmethod
    def from_dict(cls, d: dict) -> Workspace:
        return cls.model_validate(d)

    # ─── Summary ─────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """État compact pour observability."""
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "answer_shape": self.answer_shape,
            "n_tool_calls": len(self.tool_calls),
            "n_evidence_items": len(self.evidence_collected),
            "n_loop_signatures": len(self.loop_signatures),
            "epistemic_status": self.epistemic_status.value if self.epistemic_status else None,
            "stop_reason": self.stop_reason,
            "latency_s": self.latency_s,
            "n_repairs": sum(1 for tc in self.tool_calls if tc.repair_applied),
            "n_tool_errors": sum(1 for tc in self.tool_calls if tc.error),
            "finalized": self.finalized_at is not None,
            "plan_status": self.plan.status.value if self.plan else None,
        }
