"""Utilities for enqueuing ingestion jobs and interacting with Redis/RQ."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from . import DEFAULT_JOB_TIMEOUT, INGESTION_QUEUE


@lru_cache(maxsize=1)
def get_redis_connection() -> redis.Redis:
    """Return a cached Redis connection used by the ingestion queue."""
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return redis.from_url(url)


def get_queue(name: Optional[str] = None) -> Queue:
    """Return the RQ queue used for ingestion jobs."""
    queue_name = name or INGESTION_QUEUE
    return Queue(queue_name, connection=get_redis_connection(), default_timeout=DEFAULT_JOB_TIMEOUT)


def _register_meta(job: Job, **meta: Any) -> Job:
    job.meta.update(meta)
    job.save()
    return job


def enqueue_pptx_ingestion(
    *,
    job_id: str,
    file_path: str,
    document_type: str = "default",
    meta_path: Optional[str] = None,
) -> Job:
    job = get_queue().enqueue_call(
        func="ingestion.jobs.ingest_pptx_job",
        kwargs={
            "pptx_path": file_path,
            "document_type": document_type,
            "meta_path": meta_path,
        },
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"PPTX ingestion for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="ingest", document_type=document_type, source=file_path)


def enqueue_pdf_ingestion(*, job_id: str, file_path: str) -> Job:
    job = get_queue().enqueue_call(
        func="ingestion.jobs.ingest_pdf_job",
        kwargs={"pdf_path": file_path},
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"PDF ingestion for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="ingest", document_type="pdf", source=file_path)


def enqueue_excel_ingestion(
    *,
    job_id: str,
    file_path: str,
    meta: Optional[dict[str, Any]] = None,
) -> Job:
    job = get_queue().enqueue_call(
        func="ingestion.jobs.ingest_excel_job",
        kwargs={"xlsx_path": file_path, "meta": meta or {}},
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"Excel ingestion for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="ingest", document_type="xlsx", source=file_path)


def enqueue_fill_excel(
    *,
    job_id: str,
    file_path: str,
    meta_path: str,
) -> Job:
    job = get_queue().enqueue_call(
        func="ingestion.jobs.fill_excel_job",
        kwargs={"xlsx_path": file_path, "meta_path": meta_path},
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"Excel auto-fill for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="fill_excel", source=file_path)


def fetch_job(job_id: str) -> Optional[Job]:
    try:
        return Job.fetch(job_id, connection=get_redis_connection())
    except NoSuchJobError:
        return None
