"""V5 API — Pydantic models (request, response, SSE events, structured errors).

ADR V1.5 §3h : 2 modes (SSE streaming + async job), 13 codes erreur structurés.

Charte domain-agnostic : aucun champ corpus-spécifique.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Limits (ADR §3h validation) ─────────────────────────────────────────────

MAX_QUESTION_CHARS = 4000
MAX_DOC_IDS = 50
MAX_ITER_HARD_CAP = 12
MIN_ITER = 1


# ─── Enums ───────────────────────────────────────────────────────────────────


class RequestMode(str, Enum):
    SYNC = "sync"  # default sync (full response, no streaming)
    STREAM = "stream"  # SSE
    ASYNC = "async"  # background job


class JobStatus(str, Enum):
    """Status d'un job async."""
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class EpistemicStatusAPI(str, Enum):
    """Statut épistémique exposé en API (cohérent Workspace.EpistemicStatus)."""
    SUPPORTED = "supported"  # complete, evidence-grounded
    PARTIAL = "partial"
    LOW_CONFIDENCE = "low_confidence"
    UNANSWERABLE = "unanswerable"


# Structured errors (ADR §3h Table)
class ErrorType(str, Enum):
    INVALID_INPUT = "invalid_input"
    UNAUTHORIZED = "unauthorized"
    CROSS_TENANT_DENIED = "cross_tenant_denied"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    UNANSWERABLE_VALIDATED = "unanswerable_validated"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CONCURRENCY_BUDGET_EXCEEDED = "concurrency_budget_exceeded"
    COST_CAP_EXCEEDED = "cost_cap_exceeded"
    CLIENT_CANCELLED = "client_cancelled"
    INTERNAL_ERROR = "internal_error"
    PROVIDER_FAILOVER_IN_PROGRESS = "provider_failover_in_progress"
    VERIFIER_UNAVAILABLE = "verifier_unavailable"
    AGENT_TIMEOUT = "agent_timeout"
    NOT_FOUND = "not_found"


# Map ErrorType → (http_status, retryable)
ERROR_HTTP_MAP: dict[ErrorType, tuple[int, bool]] = {
    ErrorType.INVALID_INPUT: (400, False),
    ErrorType.UNAUTHORIZED: (401, False),
    ErrorType.CROSS_TENANT_DENIED: (403, False),
    ErrorType.NOT_FOUND: (404, False),
    ErrorType.IDEMPOTENCY_CONFLICT: (409, False),
    ErrorType.UNANSWERABLE_VALIDATED: (422, False),
    ErrorType.RATE_LIMIT_EXCEEDED: (429, True),
    ErrorType.CONCURRENCY_BUDGET_EXCEEDED: (429, True),
    ErrorType.COST_CAP_EXCEEDED: (451, False),
    ErrorType.CLIENT_CANCELLED: (499, False),
    ErrorType.INTERNAL_ERROR: (500, True),
    ErrorType.PROVIDER_FAILOVER_IN_PROGRESS: (502, True),
    ErrorType.VERIFIER_UNAVAILABLE: (503, True),
    ErrorType.AGENT_TIMEOUT: (504, True),
}


# ─── Request ─────────────────────────────────────────────────────────────────


class AnswerRequest(BaseModel):
    """POST /api/runtime_v5/answer body."""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)
    doc_ids: Optional[list[str]] = Field(
        default=None,
        description="If None, tenant default scope. If empty list, also tenant scope.",
    )
    answer_shape_hint: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional hint from upstream classifier (S0.5 DeBERTa)",
    )
    max_iter_override: Optional[int] = Field(
        default=None,
        ge=MIN_ITER,
        le=MAX_ITER_HARD_CAP,
        description="Override default budget max_iter (clamped 1..12)",
    )

    @field_validator("doc_ids")
    @classmethod
    def _validate_doc_ids(cls, v):
        if v is None:
            return v
        if len(v) > MAX_DOC_IDS:
            raise ValueError(
                f"too many doc_ids: {len(v)} > max {MAX_DOC_IDS}"
            )
        # check that each id is a string non-vide
        for i, did in enumerate(v):
            if not isinstance(did, str) or not did.strip():
                raise ValueError(f"doc_ids[{i}] must be a non-empty string")
        return v


# ─── Citation, Workspace metrics for response ───────────────────────────────


class CitationRef(BaseModel):
    """Une citation dans la réponse finale."""
    model_config = ConfigDict(extra="forbid")
    doc_id: str
    section_id: Optional[str] = None
    section_path: Optional[str] = None


class ResponseMetrics(BaseModel):
    """Métriques agrégées du run (subset workspace.budgets_snapshot)."""
    model_config = ConfigDict(extra="forbid")
    n_iterations: int = 0
    n_tool_calls: int = 0
    n_evidence_items: int = 0
    n_repairs: int = 0
    retrieved_chars: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


# ─── Synchronous response (mode=sync, default) ──────────────────────────────


class AnswerResponse(BaseModel):
    """Response payload pour mode sync / async completed."""
    model_config = ConfigDict(extra="forbid")
    request_id: str
    answer: str
    citations: list[CitationRef] = Field(default_factory=list)
    epistemic_status: EpistemicStatusAPI
    stop_reason: str = ""
    workspace_url: Optional[str] = None
    metrics: ResponseMetrics = Field(default_factory=ResponseMetrics)


# ─── Async job (mode=async) ──────────────────────────────────────────────────


class AsyncJobAccepted(BaseModel):
    """202 réponse à POST /answer?async=true."""
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: JobStatus = JobStatus.QUEUED
    status_url: str


class AsyncJobPartial(BaseModel):
    """Détail partial exposé en cours d'exécution."""
    model_config = ConfigDict(extra="forbid")
    plan: Optional[dict] = None
    sections_read: list[str] = Field(default_factory=list)
    provisional_citations: list[CitationRef] = Field(default_factory=list)
    n_tool_calls_so_far: int = 0


class AsyncJobStatusResponse(BaseModel):
    """GET /api/runtime_v5/answer/{request_id}."""
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: JobStatus
    partial: Optional[AsyncJobPartial] = None
    result: Optional[AnswerResponse] = None
    error: Optional["ErrorDetail"] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AsyncJobCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: JobStatus = JobStatus.CANCELLED
    tokens_consumed: int = 0
    cost_estimated: float = 0.0


# ─── Error envelope ──────────────────────────────────────────────────────────


class ErrorDetail(BaseModel):
    """Detail typed structuré (ADR §3h)."""
    model_config = ConfigDict(extra="forbid")
    type: ErrorType
    message: str
    retryable: bool
    details: Optional[dict] = None

    @classmethod
    def from_type(
        cls,
        error_type: ErrorType,
        message: str,
        details: Optional[dict] = None,
    ) -> ErrorDetail:
        _, retryable = ERROR_HTTP_MAP.get(error_type, (500, True))
        return cls(
            type=error_type,
            message=message,
            retryable=retryable,
            details=details,
        )


class ErrorResponse(BaseModel):
    """Body retourné en cas d'erreur (toute HTTP status >= 400)."""
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail
    request_id: Optional[str] = None


# Forward refs resolution
AsyncJobStatusResponse.model_rebuild()


# ─── SSE Event payloads ──────────────────────────────────────────────────────


class SSEEventType(str, Enum):
    """Types d'événements SSE émis par mode A."""
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    SECTION_READ = "section_read"
    DRAFT_ANSWER = "draft_answer"
    VERIFIER_PENDING = "verifier_pending"
    COMPLETE = "complete"
    ERROR = "error"


class SSEEventPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[dict]


class SSEEventToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iter: int
    tool: str
    args: dict
    evidence_gain: float


class SSEEventSectionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str
    title: str
    excerpt: str
    doc_id: Optional[str] = None


class SSEEventDraftAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    citations: list[CitationRef] = Field(default_factory=list)


class SSEEventVerifierPending(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Empty payload (signal-only)


class SSEEventComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    citations: list[CitationRef] = Field(default_factory=list)
    epistemic_status: EpistemicStatusAPI
    workspace_url: Optional[str] = None
    metrics: ResponseMetrics = Field(default_factory=ResponseMetrics)


class SSEEventError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ErrorType
    message: str
    retryable: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────


def http_status_for_error(error_type: ErrorType) -> int:
    """Retourne HTTP status code pour un ErrorType."""
    status, _ = ERROR_HTTP_MAP.get(error_type, (500, True))
    return status
