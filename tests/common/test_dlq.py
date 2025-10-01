"""
Tests Dead Letter Queue - Phase 0.5 P2.13
"""
import pytest
import redis
from knowbase.common.dlq import DeadLetterQueue, send_to_dlq, retry_from_dlq


@pytest.fixture
def dlq():
    """Fixture DLQ avec Redis test"""
    dlq = DeadLetterQueue(redis_url="redis://redis:6379/7", max_retries=3)
    # Cleanup
    dlq.redis_client.delete("dlq:jobs")
    dlq.redis_client.delete("dlq:index")
    yield dlq
    # Cleanup après test
    dlq.redis_client.delete("dlq:jobs")
    dlq.redis_client.delete("dlq:index")


def test_send_to_dlq(dlq):
    """Test envoi job à DLQ"""
    dlq_id = dlq.send_to_dlq(
        job_type="merge",
        job_data={"canonical": "entity1", "candidates": ["cand1"]},
        error="LLM timeout",
        retry_count=0
    )

    assert dlq_id.startswith("dlq:merge:")

    # Vérifier job sauvegardé
    job = dlq.get_job(dlq_id)
    assert job is not None
    assert job.job_type == "merge"
    assert job.error == "LLM timeout"
    assert job.retry_count == 0
    assert job.max_retries == 3


def test_list_jobs(dlq):
    """Test listing jobs DLQ"""
    # Envoyer plusieurs jobs
    dlq.send_to_dlq("merge", {"data": 1}, "error1", retry_count=0)
    dlq.send_to_dlq("backfill", {"data": 2}, "error2", retry_count=1)
    dlq.send_to_dlq("merge", {"data": 3}, "error3", retry_count=2)

    # Lister tous
    jobs = dlq.list_jobs(limit=10)
    assert len(jobs) == 3

    # Filtrer par type
    merge_jobs = dlq.list_jobs(job_type="merge")
    assert len(merge_jobs) == 2


def test_retry_job(dlq):
    """Test retry job depuis DLQ"""
    dlq_id = dlq.send_to_dlq(
        job_type="test",
        job_data={"key": "value"},
        error="test error",
        retry_count=0
    )

    # Retry 1
    success = dlq.retry_job(dlq_id)
    assert success is True

    job = dlq.get_job(dlq_id)
    assert job.retry_count == 1

    # Retry 2
    success = dlq.retry_job(dlq_id)
    assert success is True
    job = dlq.get_job(dlq_id)
    assert job.retry_count == 2

    # Retry 3
    success = dlq.retry_job(dlq_id)
    assert success is True
    job = dlq.get_job(dlq_id)
    assert job.retry_count == 3

    # Retry 4 (max atteint)
    success = dlq.retry_job(dlq_id)
    assert success is False  # Max retry atteint


def test_delete_job(dlq):
    """Test suppression job DLQ"""
    dlq_id = dlq.send_to_dlq("test", {"data": 1}, "error", retry_count=0)

    # Vérifier présent
    assert dlq.get_job(dlq_id) is not None

    # Supprimer
    dlq.delete_job(dlq_id)

    # Vérifier absent
    assert dlq.get_job(dlq_id) is None


def test_get_stats(dlq):
    """Test statistiques DLQ"""
    dlq.send_to_dlq("merge", {"data": 1}, "error", retry_count=0)
    dlq.send_to_dlq("merge", {"data": 2}, "error", retry_count=1)
    dlq.send_to_dlq("backfill", {"data": 3}, "error", retry_count=2)

    stats = dlq.get_stats()

    assert stats["total"] == 3
    assert stats["by_type"]["merge"] == 2
    assert stats["by_type"]["backfill"] == 1
    assert stats["by_retry"]["0/3"] == 1
    assert stats["by_retry"]["1/3"] == 1
    assert stats["by_retry"]["2/3"] == 1


def test_helpers():
    """Test helpers send_to_dlq et retry_from_dlq"""
    # Cleanup
    r = redis.Redis.from_url("redis://redis:6379/7", decode_responses=True)
    r.delete("dlq:jobs")
    r.delete("dlq:index")

    # Test send helper
    dlq_id = send_to_dlq(
        job_type="test_helper",
        job_data={"key": "value"},
        error="helper error"
    )
    assert dlq_id.startswith("dlq:test_helper:")

    # Test retry helper
    success = retry_from_dlq(dlq_id)
    assert success is True

    # Cleanup
    r.delete("dlq:jobs")
    r.delete("dlq:index")
