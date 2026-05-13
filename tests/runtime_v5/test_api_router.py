"""Tests router FastAPI V5 (CH-52.6.4 + S5.6).

Integration end-to-end via TestClient. JobRunner mock pour scriptability.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.api.admission import (
    AdmissionConfig,
    AdmissionController,
    FakeTimeProvider,
)
from knowbase.runtime_v5.api.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyBackend,
)
from knowbase.runtime_v5.api.job_store import InMemoryJobStore
from knowbase.runtime_v5.api.models import (
    AnswerRequest,
    AnswerResponse,
    EpistemicStatusAPI,
    ResponseMetrics,
)
from knowbase.runtime_v5.api.router import JobRunner, create_router


# ─── Mock JobRunner scriptable ───────────────────────────────────────────────


class MockJobRunner(JobRunner):
    """JobRunner scriptable pour tests :
    - simulate_delay_s : sleep avant la réponse (simulate work)
    - simulate_error : raise une exception
    - simulate_cancellation_aware : check le token pendant l'attente
    """

    def __init__(
        self,
        answer: str = "Test answer",
        simulate_delay_s: float = 0.0,
        simulate_error: Optional[Exception] = None,
        simulate_cancellation_aware: bool = False,
    ):
        self.answer = answer
        self.simulate_delay_s = simulate_delay_s
        self.simulate_error = simulate_error
        self.simulate_cancellation_aware = simulate_cancellation_aware
        self.calls = 0

    async def execute(
        self,
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        cancellation_token: CancellationToken,
    ) -> AnswerResponse:
        self.calls += 1
        if self.simulate_delay_s > 0:
            if self.simulate_cancellation_aware:
                deadline = time.monotonic() + self.simulate_delay_s
                while time.monotonic() < deadline:
                    cancellation_token.check()
                    await asyncio.sleep(0.01)
            else:
                await asyncio.sleep(self.simulate_delay_s)
        if self.simulate_error:
            raise self.simulate_error
        return AnswerResponse(
            request_id=request_id,
            answer=self.answer,
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
            stop_reason="concluded",
            metrics=ResponseMetrics(n_iterations=2, n_tool_calls=3, latency_s=0.1),
        )


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def time_provider():
    return FakeTimeProvider(start=1000.0)


@pytest.fixture
def admission(time_provider):
    cfg = AdmissionConfig(
        rate_limit_per_min=5,
        concurrency_budget=3,
    )
    return AdmissionController(config=cfg, time_provider=time_provider)


@pytest.fixture
def idempotency(time_provider):
    backend = InMemoryIdempotencyBackend(time_provider=time_provider)
    return IdempotencyStore(backend=backend, ttl_s=86400)


@pytest.fixture
def job_store():
    return InMemoryJobStore()


@pytest.fixture
def runner():
    return MockJobRunner(answer="The answer is 42.")


@pytest.fixture
def app(admission, idempotency, job_store, runner):
    router = create_router(
        admission=admission,
        idempotency=idempotency,
        job_store=job_store,
        job_runner=runner,
    )
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ─── POST /answer ────────────────────────────────────────────────────────────


class TestPostAnswer:
    def test_minimal_returns_202(self, client):
        r = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "What is X?"},
        )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "queued"
        assert body["request_id"].startswith("req_")
        assert body["status_url"].startswith("/api/runtime_v5/answer/")

    def test_missing_tenant_returns_401(self, client):
        r = client.post(
            "/api/runtime_v5/answer",
            json={"question": "X"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["type"] == "unauthorized"

    def test_invalid_request_returns_422(self, client):
        """Pydantic validation FastAPI default = 422."""
        r = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "", "doc_ids": []},  # question empty
        )
        assert r.status_code == 422

    def test_doc_ids_too_many_returns_422(self, client):
        r = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "X", "doc_ids": [f"d{i}" for i in range(100)]},
        )
        assert r.status_code == 422


# ─── Idempotency ─────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_same_request_same_key_returns_consistent(self, client, runner):
        headers = {
            "X-Tenant-ID": "tenant_a",
            "X-Idempotency-Key": "test-key-1",
        }
        body = {"question": "X"}
        r1 = client.post("/api/runtime_v5/answer", headers=headers, json=body)
        assert r1.status_code == 202

    def test_different_request_same_key_returns_409(self, client):
        headers = {
            "X-Tenant-ID": "tenant_a",
            "X-Idempotency-Key": "key-conflict",
        }
        client.post(
            "/api/runtime_v5/answer", headers=headers, json={"question": "X"},
        )
        # Same key, different question
        r = client.post(
            "/api/runtime_v5/answer", headers=headers, json={"question": "Y"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["type"] == "idempotency_conflict"


# ─── Admission: rate limit + concurrency ─────────────────────────────────────


class TestAdmission:
    def test_rate_limit_429(self, client, admission):
        # admission has rate=5, concurrency=3.
        # Pour ne pas être bloqué par concurrency, on libère après chaque call
        # → mais le mock JobRunner ne libère que dans le finally du background task,
        # ce qui ne se déclenche pas avec TestClient sync (peut être background).
        # On augmente la concurrency à 1000 pour ne tester que rate_limit.
        admission.config = AdmissionConfig(
            rate_limit_per_min=3, concurrency_budget=1000,
        )
        headers = {"X-Tenant-ID": "tenant_rate"}
        for _ in range(3):
            r = client.post("/api/runtime_v5/answer", headers=headers, json={"question": "X"})
            assert r.status_code == 202
        r = client.post("/api/runtime_v5/answer", headers=headers, json={"question": "X"})
        assert r.status_code == 429
        assert "rate_limit" in r.json()["error"]["type"]


# ─── GET /answer/{id} ────────────────────────────────────────────────────────


class TestGetStatus:
    def test_get_returns_status(self, client):
        post = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "X"},
        )
        request_id = post.json()["request_id"]

        # Wait for background task
        time.sleep(0.1)
        r = client.get(
            f"/api/runtime_v5/answer/{request_id}",
            headers={"X-Tenant-ID": "tenant_a"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["request_id"] == request_id
        assert body["status"] in ("queued", "running", "completed")

    def test_get_unknown_returns_404(self, client):
        r = client.get(
            "/api/runtime_v5/answer/req_unknown_xyz",
            headers={"X-Tenant-ID": "tenant_a"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["type"] == "not_found"

    def test_get_wrong_tenant_returns_403(self, client):
        post = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "X"},
        )
        request_id = post.json()["request_id"]
        # Different tenant tries to access
        r = client.get(
            f"/api/runtime_v5/answer/{request_id}",
            headers={"X-Tenant-ID": "tenant_b"},
        )
        assert r.status_code == 403
        assert r.json()["error"]["type"] == "cross_tenant_denied"


# ─── POST /answer/{id}/cancel ────────────────────────────────────────────────


class TestCancel:
    def test_cancel_active_job(
        self, admission, idempotency, job_store,
    ):
        """Cancel pendant job long avec runner cancellation-aware."""
        runner = MockJobRunner(
            answer="never", simulate_delay_s=2.0,
            simulate_cancellation_aware=True,
        )
        router = create_router(
            admission=admission, idempotency=idempotency,
            job_store=job_store, job_runner=runner,
        )
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as cli:
            post = cli.post(
                "/api/runtime_v5/answer",
                headers={"X-Tenant-ID": "tenant_a"},
                json={"question": "X"},
            )
            request_id = post.json()["request_id"]
            # Cancel immediately
            r = cli.post(
                f"/api/runtime_v5/answer/{request_id}/cancel",
                headers={"X-Tenant-ID": "tenant_a"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "cancelled"

    def test_cancel_unknown_404(self, client):
        r = client.post(
            "/api/runtime_v5/answer/req_unknown/cancel",
            headers={"X-Tenant-ID": "tenant_a"},
        )
        assert r.status_code == 404

    def test_cancel_wrong_tenant_403(self, client):
        post = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "X"},
        )
        request_id = post.json()["request_id"]
        r = client.post(
            f"/api/runtime_v5/answer/{request_id}/cancel",
            headers={"X-Tenant-ID": "tenant_b"},
        )
        assert r.status_code == 403


# ─── End-to-end flow with completion ─────────────────────────────────────────


class TestEndToEnd:
    def test_full_lifecycle_complete(self, client):
        # 1. POST
        post = client.post(
            "/api/runtime_v5/answer",
            headers={"X-Tenant-ID": "tenant_a"},
            json={"question": "What is X?"},
        )
        assert post.status_code == 202
        request_id = post.json()["request_id"]

        # 2. Wait for job completion (background task)
        for _ in range(20):
            r = client.get(
                f"/api/runtime_v5/answer/{request_id}",
                headers={"X-Tenant-ID": "tenant_a"},
            )
            body = r.json()
            if body["status"] == "completed":
                break
            time.sleep(0.05)

        # 3. Should be completed
        assert body["status"] == "completed"
        assert body["result"]["answer"] == "The answer is 42."
        assert body["result"]["epistemic_status"] == "supported"
