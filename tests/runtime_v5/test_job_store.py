"""Tests InMemoryJobStore (CH-52.6.4 / S5.4 part 1)."""
from __future__ import annotations

import time

import pytest

from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.api.job_store import (
    CrossTenantAccessError,
    InMemoryJobStore,
    JobNotFoundError,
    get_default_job_store,
    reset_default_job_store,
)
from knowbase.runtime_v5.api.models import (
    AnswerResponse,
    AsyncJobPartial,
    CitationRef,
    EpistemicStatusAPI,
    ErrorDetail,
    ErrorType,
    JobStatus,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_default_job_store()
    yield
    reset_default_job_store()


@pytest.fixture
def store():
    return InMemoryJobStore()


# ─── Create + get ────────────────────────────────────────────────────────────


class TestCreateGet:
    def test_create_returns_record(self, store):
        job = store.create("tenant_a")
        assert job.request_id.startswith("req_")
        assert job.tenant_id == "tenant_a"
        assert job.status == JobStatus.QUEUED

    def test_get_existing(self, store):
        job = store.create("tenant_a")
        retrieved = store.get(job.request_id, "tenant_a")
        assert retrieved.request_id == job.request_id

    def test_get_nonexistent_raises(self, store):
        with pytest.raises(JobNotFoundError):
            store.get("req_inexistent", "tenant_a")

    def test_get_wrong_tenant_raises(self, store):
        job = store.create("tenant_a")
        with pytest.raises(CrossTenantAccessError):
            store.get(job.request_id, "tenant_b")


# ─── Update lifecycle ────────────────────────────────────────────────────────


class TestLifecycle:
    def test_running_then_completed(self, store):
        job = store.create("tenant_a")
        store.update_status(job.request_id, JobStatus.RUNNING)
        assert store.get(job.request_id, "tenant_a").status == JobStatus.RUNNING

        result = AnswerResponse(
            request_id=job.request_id, answer="Done",
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
        )
        store.complete(job.request_id, result)
        updated = store.get(job.request_id, "tenant_a")
        assert updated.status == JobStatus.COMPLETED
        assert updated.result.answer == "Done"

    def test_failed(self, store):
        job = store.create("tenant_a")
        store.update_status(job.request_id, JobStatus.RUNNING)
        err = ErrorDetail.from_type(ErrorType.AGENT_TIMEOUT, "exceeded 60s")
        store.fail(job.request_id, err)
        updated = store.get(job.request_id, "tenant_a")
        assert updated.status == JobStatus.FAILED
        assert updated.error.type == ErrorType.AGENT_TIMEOUT

    def test_partial_update(self, store):
        job = store.create("tenant_a")
        partial = AsyncJobPartial(
            sections_read=["sec_1", "sec_2"],
            n_tool_calls_so_far=3,
            provisional_citations=[CitationRef(doc_id="doc_x")],
        )
        store.update_partial(job.request_id, partial)
        updated = store.get(job.request_id, "tenant_a")
        assert len(updated.partial.sections_read) == 2
        assert updated.partial.n_tool_calls_so_far == 3


# ─── Cancel ──────────────────────────────────────────────────────────────────


class TestCancel:
    def test_cancel_active_job(self, store):
        token = CancellationToken()
        job = store.create("tenant_a", cancellation_token=token)
        store.update_status(job.request_id, JobStatus.RUNNING)
        cancelled = store.cancel(job.request_id, "tenant_a", reason="user_close")
        assert cancelled.status == JobStatus.CANCELLED
        # Token a été cancel
        assert token.is_cancelled()

    def test_cancel_already_completed_no_change(self, store):
        job = store.create("tenant_a")
        result = AnswerResponse(
            request_id=job.request_id, answer="Done",
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
        )
        store.complete(job.request_id, result)
        token = job.cancellation_token
        # Cancel après completed → status reste COMPLETED
        cancelled = store.cancel(job.request_id, "tenant_a")
        assert cancelled.status == JobStatus.COMPLETED
        assert not token.is_cancelled()

    def test_cancel_wrong_tenant_raises(self, store):
        job = store.create("tenant_a")
        with pytest.raises(CrossTenantAccessError):
            store.cancel(job.request_id, "tenant_b")


# ─── list_for_tenant ─────────────────────────────────────────────────────────


class TestListForTenant:
    def test_list_returns_tenant_jobs_only(self, store):
        store.create("tenant_a")
        store.create("tenant_a")
        store.create("tenant_b")
        a_jobs = store.list_for_tenant("tenant_a")
        b_jobs = store.list_for_tenant("tenant_b")
        assert len(a_jobs) == 2
        assert len(b_jobs) == 1


# ─── purge_old ───────────────────────────────────────────────────────────────


class TestPurge:
    def test_purge_completed_old(self, store):
        job = store.create("tenant_a")
        result = AnswerResponse(
            request_id=job.request_id, answer="X",
            epistemic_status=EpistemicStatusAPI.SUPPORTED,
        )
        store.complete(job.request_id, result)
        # Hack : force updated_at très ancien
        from datetime import datetime, timedelta
        with store._lock:
            store._jobs[job.request_id].updated_at = datetime.utcnow() - timedelta(days=2)
        n = store.purge_old(max_age_s=86400)
        assert n == 1

    def test_purge_does_not_touch_active(self, store):
        store.create("tenant_a")  # status QUEUED
        n = store.purge_old(max_age_s=0)
        assert n == 0


# ─── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_counts(self, store):
        store.create("t1")
        j2 = store.create("t1")
        store.update_status(j2.request_id, JobStatus.RUNNING)
        s = store.stats()
        assert s["n_jobs_total"] == 2
        assert s["by_status"]["queued"] == 1
        assert s["by_status"]["running"] == 1


# ─── Singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton(self):
        s1 = get_default_job_store()
        s2 = get_default_job_store()
        assert s1 is s2

    def test_reset(self):
        s1 = get_default_job_store()
        reset_default_job_store()
        s2 = get_default_job_store()
        assert s1 is not s2
