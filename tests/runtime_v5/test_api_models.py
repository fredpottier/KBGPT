"""Tests Pydantic models API V5 (CH-52.6.1 / S5.1)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowbase.runtime_v5.api.models import (
    ERROR_HTTP_MAP,
    MAX_DOC_IDS,
    MAX_ITER_HARD_CAP,
    MAX_QUESTION_CHARS,
    MIN_ITER,
    AnswerRequest,
    AnswerResponse,
    AsyncJobAccepted,
    AsyncJobCancelResponse,
    AsyncJobPartial,
    AsyncJobStatusResponse,
    CitationRef,
    EpistemicStatusAPI,
    ErrorDetail,
    ErrorResponse,
    ErrorType,
    JobStatus,
    RequestMode,
    ResponseMetrics,
    SSEEventComplete,
    SSEEventError,
    SSEEventPlan,
    SSEEventToolCall,
    http_status_for_error,
)


# ─── AnswerRequest validation ────────────────────────────────────────────────


class TestAnswerRequest:
    def test_minimal_valid(self):
        r = AnswerRequest(question="What is X?")
        assert r.question == "What is X?"
        assert r.doc_ids is None
        assert r.max_iter_override is None

    def test_with_doc_ids(self):
        r = AnswerRequest(question="X", doc_ids=["doc1", "doc2"])
        assert len(r.doc_ids) == 2

    def test_question_empty_rejected(self):
        with pytest.raises(ValidationError):
            AnswerRequest(question="")

    def test_question_too_long_rejected(self):
        with pytest.raises(ValidationError):
            AnswerRequest(question="x" * (MAX_QUESTION_CHARS + 1))

    def test_doc_ids_too_many_rejected(self):
        with pytest.raises(ValidationError):
            AnswerRequest(
                question="X",
                doc_ids=[f"doc_{i}" for i in range(MAX_DOC_IDS + 1)],
            )

    def test_doc_ids_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            AnswerRequest(question="X", doc_ids=["valid", ""])

    def test_doc_ids_non_string_rejected(self):
        with pytest.raises(ValidationError):
            AnswerRequest(question="X", doc_ids=["valid", 42])  # type: ignore

    def test_max_iter_clamped(self):
        with pytest.raises(ValidationError):
            AnswerRequest(question="X", max_iter_override=999)
        with pytest.raises(ValidationError):
            AnswerRequest(question="X", max_iter_override=0)

    def test_max_iter_at_boundary(self):
        r = AnswerRequest(question="X", max_iter_override=MAX_ITER_HARD_CAP)
        assert r.max_iter_override == MAX_ITER_HARD_CAP
        r = AnswerRequest(question="X", max_iter_override=MIN_ITER)
        assert r.max_iter_override == MIN_ITER

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AnswerRequest(question="X", garbage_field="oops")

    def test_doc_ids_empty_list_kept(self):
        r = AnswerRequest(question="X", doc_ids=[])
        assert r.doc_ids == []


# ─── AnswerResponse ──────────────────────────────────────────────────────────


class TestAnswerResponse:
    def test_minimal(self):
        r = AnswerResponse(
            request_id="req_123",
            answer="The answer is 42",
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
        )
        assert r.metrics.n_iterations == 0
        assert r.citations == []

    def test_with_citations_and_metrics(self):
        r = AnswerResponse(
            request_id="req_x",
            answer="Hello",
            citations=[CitationRef(doc_id="doc_a", section_id="sec_1")],
            epistemic_status=EpistemicStatusAPI.PARTIAL,
            stop_reason="budget_soft_cap_max_iterations",
            workspace_url="/admin/workspaces/req_x",
            metrics=ResponseMetrics(
                n_iterations=5, n_tool_calls=12, latency_s=23.4,
            ),
        )
        assert r.metrics.n_iterations == 5
        assert r.citations[0].doc_id == "doc_a"


# ─── AsyncJobAccepted + Status + Cancel ──────────────────────────────────────


class TestAsyncJobModels:
    def test_accepted(self):
        a = AsyncJobAccepted(
            request_id="req_y",
            status_url="/api/runtime_v5/answer/req_y",
        )
        assert a.status == JobStatus.QUEUED

    def test_status_running(self):
        s = AsyncJobStatusResponse(
            request_id="req_y",
            status=JobStatus.RUNNING,
            partial=AsyncJobPartial(
                sections_read=["sec_1"],
                n_tool_calls_so_far=3,
            ),
        )
        assert s.status == JobStatus.RUNNING
        assert s.partial.n_tool_calls_so_far == 3

    def test_status_completed_with_result(self):
        result = AnswerResponse(
            request_id="req_y",
            answer="Done",
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
        )
        s = AsyncJobStatusResponse(
            request_id="req_y",
            status=JobStatus.COMPLETED,
            result=result,
        )
        assert s.result.answer == "Done"

    def test_status_failed_with_error(self):
        err = ErrorDetail.from_type(
            ErrorType.AGENT_TIMEOUT, "exceeded 60s"
        )
        s = AsyncJobStatusResponse(
            request_id="req_y",
            status=JobStatus.FAILED,
            error=err,
        )
        assert s.error.type == ErrorType.AGENT_TIMEOUT
        assert s.error.retryable is True

    def test_cancel_response(self):
        c = AsyncJobCancelResponse(
            request_id="req_y",
            tokens_consumed=8500,
            cost_estimated=0.025,
        )
        assert c.status == JobStatus.CANCELLED


# ─── ErrorDetail.from_type ──────────────────────────────────────────────────


class TestErrorDetail:
    def test_from_type_retryable_429(self):
        err = ErrorDetail.from_type(ErrorType.RATE_LIMIT_EXCEEDED, "too many")
        assert err.retryable is True
        assert err.type == ErrorType.RATE_LIMIT_EXCEEDED

    def test_from_type_non_retryable_400(self):
        err = ErrorDetail.from_type(ErrorType.INVALID_INPUT, "doc_id missing")
        assert err.retryable is False

    def test_from_type_internal_500_retryable(self):
        err = ErrorDetail.from_type(ErrorType.INTERNAL_ERROR, "oops")
        assert err.retryable is True


# ─── http_status_for_error ───────────────────────────────────────────────────


class TestHttpStatusMapping:
    def test_invalid_input_400(self):
        assert http_status_for_error(ErrorType.INVALID_INPUT) == 400

    def test_cross_tenant_denied_403(self):
        assert http_status_for_error(ErrorType.CROSS_TENANT_DENIED) == 403

    def test_idempotency_conflict_409(self):
        assert http_status_for_error(ErrorType.IDEMPOTENCY_CONFLICT) == 409

    def test_rate_limit_429(self):
        assert http_status_for_error(ErrorType.RATE_LIMIT_EXCEEDED) == 429

    def test_cost_cap_451(self):
        assert http_status_for_error(ErrorType.COST_CAP_EXCEEDED) == 451

    def test_provider_failover_502(self):
        assert http_status_for_error(ErrorType.PROVIDER_FAILOVER_IN_PROGRESS) == 502

    def test_agent_timeout_504(self):
        assert http_status_for_error(ErrorType.AGENT_TIMEOUT) == 504

    def test_all_error_types_have_mapping(self):
        """Tous les ErrorType doivent avoir un mapping HTTP défini."""
        for et in ErrorType:
            assert et in ERROR_HTTP_MAP, f"Missing HTTP mapping for {et}"


# ─── SSE event models ───────────────────────────────────────────────────────


class TestSSEEvents:
    def test_plan_event(self):
        ev = SSEEventPlan(steps=[{"intent": "find", "tool": "find_in"}])
        assert len(ev.steps) == 1

    def test_tool_call_event(self):
        ev = SSEEventToolCall(
            iter=1, tool="outline",
            args={"doc_id": "x"}, evidence_gain=0.3,
        )
        assert ev.iter == 1
        assert ev.evidence_gain == 0.3

    def test_complete_event(self):
        ev = SSEEventComplete(
            answer="Done",
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
            metrics=ResponseMetrics(n_iterations=3, n_tool_calls=8),
        )
        assert ev.epistemic_status == EpistemicStatusAPI.SUPPORTED

    def test_error_event(self):
        ev = SSEEventError(
            type=ErrorType.AGENT_TIMEOUT,
            message="agent exceeded budget",
            retryable=True,
        )
        assert ev.retryable is True

    def test_extra_field_rejected_on_sse(self):
        with pytest.raises(ValidationError):
            SSEEventPlan(steps=[], garbage="oops")


# ─── ErrorResponse ───────────────────────────────────────────────────────────


class TestErrorResponse:
    def test_envelope(self):
        e = ErrorResponse(
            error=ErrorDetail.from_type(
                ErrorType.UNAUTHORIZED, "missing X-Tenant-ID"
            ),
            request_id="req_x",
        )
        assert e.error.type == ErrorType.UNAUTHORIZED
        assert e.error.retryable is False
