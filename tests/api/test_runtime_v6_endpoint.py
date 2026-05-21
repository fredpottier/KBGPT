"""Tests endpoint /api/runtime_v6/answer (Phase A3.7).

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1-§2.5.

Stratégie :
    - Mock Orchestrator via reset_orchestrator() + injection custom singleton
    - Tester endpoint sync POST /answer + /health
    - Valider mapping OrchestratorResult → RuntimeV6Response
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowbase.api.routers import runtime_v6
from knowbase.runtime_a3.orchestrator import (
    IterationTrace,
    OrchestratorResult,
)
from knowbase.runtime_a3.schemas import (
    CitedClaim,
    EvaluateOutput,
    ExecuteOutput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    SynthesizeOutput,
    ToolResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def app_client():
    """Crée une app FastAPI minimale avec le router runtime_v6 monté."""
    app = FastAPI()
    app.include_router(runtime_v6.router, prefix="/api")
    return TestClient(app)


def _make_orchestrator_result(
    answer="Test answer",
    mode="REASONED",
    n_iterations=1,
    terminated_reason="verdict_correct",
    cited_claims=None,
) -> OrchestratorResult:
    """Construit un OrchestratorResult réaliste."""
    po = ParseOutput(
        sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
        entities=[],
        language="en",
        raw_question="test",
        parse_confidence=0.9,
        parse_warnings=[],
        schema_version="a3.0",
    )
    plo = PlanOutput(tool_calls=[], unmappable_sub_goals=[])
    eo_exec = ExecuteOutput(results=[], total_duration_s=0.05)
    eo_eval = EvaluateOutput(
        verdict="CORRECT",
        covered_sub_goals=[0],
        uncovered_sub_goals=[],
        re_plan_hint="none",
        confidence=0.9,
        reasoning="ok",
        schema_version="a3.0",
    )
    iter_traces = [
        IterationTrace(
            iteration=i,
            parse_output=po,
            plan_output=plo,
            execute_output=eo_exec,
            evaluate_output=eo_eval,
            duration_s=0.1,
        )
        for i in range(n_iterations)
    ]
    so = SynthesizeOutput(
        answer_text=answer,
        cited_claims=cited_claims or [],
        uncovered_sub_goals_warning=None,
        conflict_pending_warning=None,
        mode=mode,
        synthesize_warnings=[],
        citation_coverage_rate=1.0,
        schema_version="a3.0",
    )
    return OrchestratorResult(
        synthesize_output=so,
        iterations=iter_traces,
        total_duration_s=0.15,
        terminated_reason=terminated_reason,
    )


@pytest.fixture
def mock_orchestrator():
    """Patch le singleton Orchestrator du router pour injecter un mock."""
    mock = MagicMock()
    with patch.object(runtime_v6, "_orchestrator_instance", mock):
        yield mock
    runtime_v6.reset_orchestrator()


# ============================================================================
# Endpoint /health
# ============================================================================


class TestHealth:
    def test_health_returns_ok(self, app_client):
        resp = app_client.get("/api/runtime_v6/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["runtime_version"] == "a3.0"
        assert body["max_iterations"] == 2
        assert body["max_wall_clock_s"] == 60.0


# ============================================================================
# Endpoint /answer happy path
# ============================================================================


class TestAnswerHappyPath:
    def test_answer_basic(self, app_client, mock_orchestrator):
        mock_orchestrator.run.return_value = _make_orchestrator_result(
            answer="Product X supports 500 users [claim_id=c1]."
        )
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "How many users for Product X?",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "Product X supports 500 users" in body["answer_text"]
        assert body["mode"] == "REASONED"
        assert body["n_iterations"] == 1
        assert body["terminated_reason"] == "verdict_correct"
        assert body["runtime_version"] == "a3.0"

    def test_answer_with_cited_claims(self, app_client, mock_orchestrator):
        cited = [CitedClaim(claim_id="c_001", claim_verbatim="500 users limit",
                            doc_title="Doc A", section_id="sec_3", page=12)]
        mock_orchestrator.run.return_value = _make_orchestrator_result(
            cited_claims=cited,
        )
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "test",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["cited_claims"]) == 1
        assert body["cited_claims"][0]["claim_id"] == "c_001"
        assert body["cited_claims"][0]["doc_title"] == "Doc A"

    def test_answer_with_trace_default_true(self, app_client, mock_orchestrator):
        mock_orchestrator.run.return_value = _make_orchestrator_result(n_iterations=2)
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "test",
        })
        assert resp.status_code == 200
        body = resp.json()
        # include_trace default=True → trace présente
        assert body["iterations_trace"] is not None
        assert len(body["iterations_trace"]) == 2

    def test_answer_with_trace_disabled(self, app_client, mock_orchestrator):
        mock_orchestrator.run.return_value = _make_orchestrator_result(n_iterations=2)
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "test",
            "include_trace": False,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["iterations_trace"] is None


# ============================================================================
# Endpoint /answer validation
# ============================================================================


class TestAnswerValidation:
    def test_missing_question_rejected(self, app_client):
        resp = app_client.post("/api/runtime_v6/answer", json={})
        assert resp.status_code == 422

    def test_empty_question_rejected(self, app_client):
        resp = app_client.post("/api/runtime_v6/answer", json={"question": ""})
        assert resp.status_code == 422

    def test_question_too_long_rejected(self, app_client):
        long_q = "X " * 3000  # > 5000 chars
        resp = app_client.post("/api/runtime_v6/answer", json={"question": long_q})
        assert resp.status_code == 422

    def test_invalid_response_mode_rejected(self, app_client):
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "test",
            "response_mode": "bogus_mode",
        })
        assert resp.status_code == 422

    def test_extra_field_rejected(self, app_client):
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "test",
            "extra_unknown_field": "boom",
        })
        assert resp.status_code == 422


# ============================================================================
# Endpoint /answer error handling
# ============================================================================


class TestAnswerErrors:
    def test_orchestrator_exception_returns_500(self, app_client, mock_orchestrator):
        mock_orchestrator.run.side_effect = Exception("Internal boom")
        resp = app_client.post("/api/runtime_v6/answer", json={
            "question": "test",
        })
        assert resp.status_code == 500
        assert "Internal boom" in resp.json()["detail"]


# ============================================================================
# Modes terminaux
# ============================================================================


class TestTerminalModes:
    @pytest.mark.parametrize("mode", ["REASONED", "ANCHORED", "TEXT_ONLY", "ABSTENTION"])
    def test_each_mode_propagates(self, app_client, mock_orchestrator, mode):
        mock_orchestrator.run.return_value = _make_orchestrator_result(mode=mode)
        resp = app_client.post("/api/runtime_v6/answer", json={"question": "test"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == mode


# ============================================================================
# Trace structure
# ============================================================================


class TestTraceStructure:
    def test_trace_contains_iteration_metadata(self, app_client, mock_orchestrator):
        mock_orchestrator.run.return_value = _make_orchestrator_result(n_iterations=2)
        resp = app_client.post("/api/runtime_v6/answer", json={"question": "test"})
        body = resp.json()
        for trace in body["iterations_trace"]:
            assert "iteration" in trace
            assert "duration_s" in trace
            assert "n_sub_goals" in trace
            assert "verdict" in trace
            assert "re_plan_hint" in trace
