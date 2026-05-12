"""Tests P4 polish — recovery logic."""
from __future__ import annotations

import uuid

import pytest

from knowbase.ingestion.resilience import (
    JobCheckpoint,
    JobManager,
    JobState,
    JobStateEnum,
)
from knowbase.ingestion.resilience.recovery import (
    determine_resume_strategy,
    list_recoverable_jobs,
)


@pytest.fixture
def mgr():
    m = JobManager(ttl_seconds=300)
    yield m
    for key in m.redis.scan_iter(match=f"osmose:ingest:job:test_*"):
        m.redis.delete(key)


def _new_doc_id() -> str:
    return f"test_recovery_{uuid.uuid4().hex[:8]}"


def test_strategy_pending_requeue():
    job = JobState(doc_id="x", file_path="/x", state=JobStateEnum.PENDING)
    assert determine_resume_strategy(job) == "requeue_initial"


def test_strategy_no_checkpoint_restart():
    job = JobState(doc_id="x", file_path="/x", state=JobStateEnum.PROCESSING)
    assert determine_resume_strategy(job) == "restart_full"


def test_strategy_extract_phase_restart():
    job = JobState(
        doc_id="x", file_path="/x", state=JobStateEnum.PROCESSING,
        last_checkpoint=JobCheckpoint(phase="extract", progress=0.4),
    )
    assert determine_resume_strategy(job) == "restart_full"


def test_strategy_post_extract_persist_only():
    job = JobState(
        doc_id="x", file_path="/x", state=JobStateEnum.PROCESSING,
        last_checkpoint=JobCheckpoint(phase="post_extract", progress=0.6),
    )
    assert determine_resume_strategy(job) == "persist_only"


def test_strategy_post_claim_persist_post_import_only():
    job = JobState(
        doc_id="x", file_path="/x", state=JobStateEnum.POST_IMPORT,
        last_checkpoint=JobCheckpoint(phase="post_claim_persist", progress=0.85),
    )
    assert determine_resume_strategy(job) == "post_import_only"


def test_strategy_done_noop():
    job = JobState(
        doc_id="x", file_path="/x", state=JobStateEnum.DONE,
        last_checkpoint=JobCheckpoint(phase="done", progress=1.0),
    )
    assert determine_resume_strategy(job) == "noop"


def test_list_recoverable_skips_max_retries(mgr):
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/x")
    mgr.update_state(doc_id, JobStateEnum.PROCESSING)
    # Simuler 3 retries
    job = mgr.get_state(doc_id)
    job.retries = 3
    mgr._persist(job)

    candidates = [j for j in list_recoverable_jobs(mgr) if j.doc_id == doc_id]
    assert candidates == []


def test_list_recoverable_includes_active(mgr):
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/x")
    mgr.update_state(doc_id, JobStateEnum.PROCESSING)

    candidates = [j for j in list_recoverable_jobs(mgr) if j.doc_id == doc_id]
    assert len(candidates) == 1
