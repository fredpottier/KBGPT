"""Tests SSE endpoint (CH-52.6.5 / S5.5)."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.api.admission import (
    AdmissionConfig,
    AdmissionController,
    FakeTimeProvider,
)
from knowbase.runtime_v5.api.models import (
    AnswerRequest,
    EpistemicStatusAPI,
    ErrorType,
    ResponseMetrics,
    SSEEventComplete,
    SSEEventToolCall,
    SSEEventType,
)
from knowbase.runtime_v5.api.sse import (
    StreamingJobRunner,
    _format_sse,
    create_sse_router,
)


# ─── Mock streaming runner ──────────────────────────────────────────────────


class MockStreamingRunner(StreamingJobRunner):
    """Yield une liste d'events scriptés."""

    def __init__(
        self,
        events: list[tuple[SSEEventType, dict]],
        delay_per_event_s: float = 0.0,
        check_cancellation: bool = True,
        raise_after_n: Optional[int] = None,
    ):
        self.events = list(events)
        self.delay_per_event_s = delay_per_event_s
        self.check_cancellation = check_cancellation
        self.raise_after_n = raise_after_n

    async def stream(
        self,
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        cancellation_token: CancellationToken,
    ) -> AsyncIterator[tuple[SSEEventType, dict]]:
        emitted = 0
        for event_type, payload in self.events:
            if self.check_cancellation:
                cancellation_token.check()
            if self.delay_per_event_s > 0:
                await asyncio.sleep(self.delay_per_event_s)
            if self.raise_after_n is not None and emitted >= self.raise_after_n:
                raise RuntimeError("simulated runtime error")
            yield event_type, payload
            emitted += 1


# ─── _format_sse ─────────────────────────────────────────────────────────────


class TestFormatSSE:
    def test_basic_format(self):
        s = _format_sse("tool_call", {"iter": 1, "tool": "outline"})
        assert s.startswith("event: tool_call\n")
        assert 'data: {"iter": 1' in s
        assert s.endswith("\n\n")

    def test_unicode_preserved(self):
        s = _format_sse("complete", {"answer": "Réponse à é"})
        assert "Réponse" in s

    def test_no_trailing_newline_in_data(self):
        s = _format_sse("plan", {"steps": []})
        # Only 1 newline after data line (before the empty line)
        lines = s.split("\n")
        assert len(lines) == 4  # event, data, "", ""


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def admission():
    cfg = AdmissionConfig(rate_limit_per_min=10, concurrency_budget=5)
    return AdmissionController(config=cfg)


def _make_app(admission, runner):
    router = create_sse_router(admission=admission, streaming_runner=runner)
    app = FastAPI()
    app.include_router(router)
    return app


# ─── Happy path : full event stream ──────────────────────────────────────────


class TestHappyPath:
    def test_full_stream(self, admission):
        events = [
            (SSEEventType.PLAN, {"steps": [{"intent": "find", "tool": "find_in"}]}),
            (SSEEventType.TOOL_CALL, SSEEventToolCall(
                iter=1, tool="outline", args={"doc_id": "x"},
                evidence_gain=0.3,
            ).model_dump()),
            (SSEEventType.SECTION_READ, {
                "section_id": "sec_1", "title": "Intro",
                "excerpt": "alpha beta", "doc_id": "doc_x",
            }),
            (SSEEventType.DRAFT_ANSWER, {
                "text": "Provisional answer",
                "citations": [{"doc_id": "doc_x", "section_id": "sec_1"}],
            }),
            (SSEEventType.COMPLETE, SSEEventComplete(
                answer="Final answer",
                epistemic_status=EpistemicStatusAPI.SUPPORTED,
                metrics=ResponseMetrics(n_iterations=2, n_tool_calls=3),
            ).model_dump()),
        ]
        runner = MockStreamingRunner(events)
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            with cli.stream(
                "POST", "/api/runtime_v5/answer/stream",
                headers={"X-Tenant-ID": "tenant_a"},
                json={"question": "What is X?"},
            ) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                body = b"".join(resp.iter_bytes()).decode("utf-8")

        # Vérifie les events
        assert "event: plan" in body
        assert "event: tool_call" in body
        assert "event: section_read" in body
        assert "event: draft_answer" in body
        assert "event: complete" in body
        assert "Final answer" in body
        assert "X-Request-ID" in resp.headers or "x-request-id" in resp.headers


# ─── Pre-stream validation errors ────────────────────────────────────────────


class TestPreStreamValidation:
    def test_missing_tenant_returns_401_json(self, admission):
        runner = MockStreamingRunner([])
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            r = cli.post(
                "/api/runtime_v5/answer/stream",
                json={"question": "X"},
            )
            assert r.status_code == 401
            # JSON response, pas SSE
            assert r.headers["content-type"].startswith("application/json")
            assert r.json()["error"]["type"] == "unauthorized"

    def test_invalid_body_returns_422(self, admission):
        runner = MockStreamingRunner([])
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            r = cli.post(
                "/api/runtime_v5/answer/stream",
                headers={"X-Tenant-ID": "tenant_a"},
                json={"question": ""},
            )
            assert r.status_code == 422

    def test_rate_limit_returns_429_json(self, admission):
        admission.config = AdmissionConfig(
            rate_limit_per_min=2, concurrency_budget=100,
        )
        runner = MockStreamingRunner([
            (SSEEventType.COMPLETE, {"answer": "X", "epistemic_status": "supported",
                                      "citations": [], "metrics": {}}),
        ])
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            # Consomme les 2 slots rate
            for _ in range(2):
                with cli.stream(
                    "POST", "/api/runtime_v5/answer/stream",
                    headers={"X-Tenant-ID": "tenant_rate"},
                    json={"question": "X"},
                ) as resp:
                    # consume stream to complete
                    list(resp.iter_bytes())
            # 3ème → 429
            r = cli.post(
                "/api/runtime_v5/answer/stream",
                headers={"X-Tenant-ID": "tenant_rate"},
                json={"question": "X"},
            )
            assert r.status_code == 429


# ─── Error event mid-stream ──────────────────────────────────────────────────


class TestErrorMidStream:
    def test_runner_raises_emits_error_event(self, admission):
        events = [
            (SSEEventType.PLAN, {"steps": []}),
            (SSEEventType.TOOL_CALL, SSEEventToolCall(
                iter=1, tool="outline", args={}, evidence_gain=0.1,
            ).model_dump()),
            (SSEEventType.TOOL_CALL, SSEEventToolCall(
                iter=2, tool="read", args={}, evidence_gain=0.2,
            ).model_dump()),
        ]
        # raise_after_n=2 : check `emitted >= 2` BEFORE 3rd yield → 2 events émis,
        # puis raise → le router catch et yield event:error
        runner = MockStreamingRunner(events, raise_after_n=2)
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            with cli.stream(
                "POST", "/api/runtime_v5/answer/stream",
                headers={"X-Tenant-ID": "tenant_a"},
                json={"question": "X"},
            ) as resp:
                assert resp.status_code == 200  # SSE déjà ouvert
                body = b"".join(resp.iter_bytes()).decode("utf-8")
        # Plan + tool_call émis, puis error
        assert "event: plan" in body
        assert "event: tool_call" in body
        assert "event: error" in body
        assert "simulated" in body
        assert "internal_error" in body


# ─── Cancellation pre-emption ────────────────────────────────────────────────


class TestCancellationDuringStream:
    def test_runner_can_check_token(self, admission):
        """Si le token est cancelled, le runner doit voir CancellationRequested."""
        # Synthèse : pas trivial de tester un client disconnect via TestClient.
        # On vérifie au moins que le check_cancellation est appelé par le runner.

        class CancelEarlyRunner(StreamingJobRunner):
            async def stream(self, request_id, tenant_id, request, cancellation_token):
                # Cancel d'office
                cancellation_token.cancel(reason="test", source="test")
                # Le check raise CancellationRequested
                cancellation_token.check()
                yield SSEEventType.COMPLETE, {}

        runner = CancelEarlyRunner()
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            with cli.stream(
                "POST", "/api/runtime_v5/answer/stream",
                headers={"X-Tenant-ID": "tenant_a"},
                json={"question": "X"},
            ) as resp:
                body = b"".join(resp.iter_bytes()).decode("utf-8")
        assert "event: error" in body
        assert "client_cancelled" in body


# ─── Concurrency slot released ───────────────────────────────────────────────


class TestConcurrencyRelease:
    def test_slot_released_after_stream(self, admission):
        runner = MockStreamingRunner([
            (SSEEventType.COMPLETE, {
                "answer": "X", "epistemic_status": "supported",
                "citations": [], "metrics": {},
            }),
        ])
        app = _make_app(admission, runner)
        with TestClient(app) as cli:
            for _ in range(5):
                with cli.stream(
                    "POST", "/api/runtime_v5/answer/stream",
                    headers={"X-Tenant-ID": "tenant_a"},
                    json={"question": "X"},
                ) as resp:
                    list(resp.iter_bytes())  # drain
            # 5 slots utilisés mais release après chaque → snap = 0
            snap = admission.snapshot("tenant_a")
            assert snap["concurrency"]["active"] == 0
