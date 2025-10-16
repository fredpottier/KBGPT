from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from rq.job import Job
from rq.exceptions import NoSuchJobError

from knowbase.config.settings import get_settings
from .connection import DEFAULT_JOB_TIMEOUT, get_queue

SETTINGS = get_settings()


def _register_meta(job: Job, **meta: Any) -> Job:
    job.meta.update(meta)
    job.save()
    return job


def enqueue_pptx_ingestion(
    *,
    job_id: str,
    file_path: str,
    document_type_id: Optional[str] = None,
    meta_path: Optional[str] = None,
    use_vision: bool = True,
    queue_name: Optional[str] = None,
) -> Job:
    job = get_queue(queue_name).enqueue_call(
        func="knowbase.ingestion.queue.jobs.ingest_pptx_job",
        kwargs={
            "pptx_path": file_path,
            "document_type_id": document_type_id,
            "meta_path": meta_path,
            "use_vision": use_vision,
        },
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"PPTX ingestion for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="ingest", document_type=document_type_id or "default", source=file_path)


def enqueue_pdf_ingestion(*, job_id: str, file_path: str, document_type_id: Optional[str] = None, use_vision: bool = True, queue_name: Optional[str] = None) -> Job:
    job = get_queue(queue_name).enqueue_call(
        func="knowbase.ingestion.queue.jobs.ingest_pdf_job",
        kwargs={"pdf_path": file_path, "document_type_id": document_type_id, "use_vision": use_vision},
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"PDF ingestion for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="ingest", document_type=document_type_id or "pdf", source=file_path)


def enqueue_excel_ingestion(
    *,
    job_id: str,
    file_path: str,
    meta: Optional[dict[str, Any]] = None,
    queue_name: Optional[str] = None,
) -> Job:
    job = get_queue(queue_name).enqueue_call(
        func="knowbase.ingestion.queue.jobs.ingest_excel_job",
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
    queue_name: Optional[str] = None,
) -> Job:
    job = get_queue(queue_name).enqueue_call(
        func="knowbase.ingestion.queue.jobs.fill_excel_job",
        kwargs={"xlsx_path": file_path, "meta_path": meta_path},
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"Excel auto-fill for {Path(file_path).name}",
    )
    return _register_meta(job, job_type="fill_excel", source=file_path)


def fetch_job(job_id: str) -> Optional[Job]:
    try:
        return Job.fetch(job_id, connection=get_queue().connection)
    except NoSuchJobError:
        return None


__all__ = [
    "enqueue_pptx_ingestion",
    "enqueue_pdf_ingestion",
    "enqueue_excel_ingestion",
    "enqueue_fill_excel",
    "fetch_job",
    "get_queue",
]



