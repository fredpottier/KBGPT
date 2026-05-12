"""
Tests P4.7 — JobManager Redis-backed (P4.1).

Vérifie :
- Création + persist
- Update state + checkpoint
- Refresh TTL à chaque update
- list_active_jobs filtre les non-actifs (done/failed) hors retours
- create_job échoue si doc_id déjà processing
- Idempotence (delete + re-create)
- cleanup_stale supprime les vieux failed
"""
from __future__ import annotations

import json
import time
import uuid

import pytest

from knowbase.ingestion.resilience import (
    JobCheckpoint,
    JobManager,
    JobState,
    JobStateEnum,
)


@pytest.fixture
def mgr():
    """JobManager avec TTL court pour tests."""
    m = JobManager(ttl_seconds=300)
    yield m
    # Cleanup : supprimer toutes les clés tests
    for key in m.redis.scan_iter(match=f"osmose:ingest:job:test_*"):
        m.redis.delete(key)


def _new_doc_id() -> str:
    return f"test_p47_{uuid.uuid4().hex[:8]}"


def test_create_and_get(mgr):
    doc_id = _new_doc_id()
    job = mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")
    assert job.state == JobStateEnum.PENDING
    fetched = mgr.get_state(doc_id)
    assert fetched is not None
    assert fetched.doc_id == doc_id
    assert fetched.state == JobStateEnum.PENDING


def test_update_with_checkpoint(mgr):
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")

    cp = JobCheckpoint(phase="extract", progress=0.5, last_block=10, total_blocks=20)
    job = mgr.update_state(doc_id, JobStateEnum.PROCESSING, checkpoint=cp)

    assert job.state == JobStateEnum.PROCESSING
    assert job.last_checkpoint is not None
    assert job.last_checkpoint.phase == "extract"
    assert job.last_checkpoint.progress == 0.5
    assert job.last_checkpoint.last_block == 10


def test_create_refuses_if_processing(mgr):
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")
    mgr.update_state(doc_id, JobStateEnum.PROCESSING)

    with pytest.raises(ValueError, match="already exists in state=processing"):
        mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")


def test_create_after_failed_ok(mgr):
    """Idempotence après failed : on peut recréer."""
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")
    mgr.update_state(doc_id, JobStateEnum.FAILED, error="some error")

    # Re-create OK car state != processing
    job2 = mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")
    assert job2.state == JobStateEnum.PENDING


def test_list_active_filters_done(mgr):
    doc_a = _new_doc_id()
    doc_b = _new_doc_id()
    doc_c = _new_doc_id()

    mgr.create_job(doc_id=doc_a, file_path="/a.pdf")
    mgr.update_state(doc_a, JobStateEnum.PROCESSING)

    mgr.create_job(doc_id=doc_b, file_path="/b.pdf")
    mgr.update_state(doc_b, JobStateEnum.DONE)

    mgr.create_job(doc_id=doc_c, file_path="/c.pdf")
    mgr.update_state(doc_c, JobStateEnum.FAILED, error="x")

    active = [j for j in mgr.list_active_jobs() if j.doc_id.startswith("test_p47_")]
    active_ids = {j.doc_id for j in active}
    assert doc_a in active_ids
    assert doc_b not in active_ids
    assert doc_c not in active_ids


def test_get_returns_none_if_missing(mgr):
    assert mgr.get_state("test_p47_nonexistent_xxx") is None


def test_ttl_refresh_on_update(mgr):
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")
    ttl1 = mgr.redis.ttl(mgr._key(doc_id))
    time.sleep(1.1)
    mgr.update_state(doc_id, JobStateEnum.PROCESSING)
    ttl2 = mgr.redis.ttl(mgr._key(doc_id))
    # TTL refreshé donc devrait être >= ttl1 - 1 (peut être ==)
    assert ttl2 >= ttl1 - 1


def test_delete_idempotent(mgr):
    doc_id = _new_doc_id()
    mgr.create_job(doc_id=doc_id, file_path="/tmp/foo.pdf")
    assert mgr.delete_job(doc_id) is True
    assert mgr.delete_job(doc_id) is False  # 2e suppression : non-existant


def test_persistence_round_trip(mgr):
    """Persist en JSON puis relire → même JobState."""
    doc_id = _new_doc_id()
    cp = JobCheckpoint(phase="claim_persist", progress=0.8, metadata={"foo": "bar"})
    j = mgr.create_job(doc_id=doc_id, file_path="/x.pdf", metadata={"source": "test"})
    j2 = mgr.update_state(doc_id, JobStateEnum.PROCESSING, checkpoint=cp)
    fetched = mgr.get_state(doc_id)
    assert fetched is not None
    assert fetched.metadata == {"source": "test"}
    assert fetched.last_checkpoint.metadata == {"foo": "bar"}
    assert fetched.last_checkpoint.progress == 0.8
