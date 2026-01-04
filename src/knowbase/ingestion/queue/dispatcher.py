"""
Dispatcher - Route les documents vers V1 ou V2 selon feature flag.

Si extraction_v2.enabled = true:
    -> ingest_document_v2_job (pipeline unifie Docling + Vision Gating)

Sinon:
    -> ingest_pptx_job / ingest_pdf_job (pipelines legacy)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import logging

from rq.job import Job
from rq.exceptions import NoSuchJobError

from knowbase.config.settings import get_settings
from knowbase.config.feature_flags import get_feature_flags
from .connection import DEFAULT_JOB_TIMEOUT, get_queue

SETTINGS = get_settings()
logger = logging.getLogger(__name__)


def _is_extraction_v2_enabled() -> bool:
    """Verifie si Extraction V2 est active."""
    try:
        flags = get_feature_flags()
        v2_config = flags.get("extraction_v2", {})
        return v2_config.get("enabled", False)
    except Exception:
        return False


def _is_format_supported_v2(file_type: str) -> bool:
    """Verifie si le format est supporte par V2."""
    try:
        flags = get_feature_flags()
        v2_config = flags.get("extraction_v2", {})
        supported = v2_config.get("supported_formats", ["pdf", "pptx", "docx", "xlsx"])
        return file_type.lower().lstrip(".") in supported
    except Exception:
        return False


def enqueue_document_v2(
    *,
    job_id: str,
    file_path: str,
    document_type_id: Optional[str] = None,
    tenant_id: str = "default",
    queue_name: Optional[str] = None,
) -> Job:
    """
    Enqueue un document pour traitement V2 (pipeline unifie).

    Args:
        job_id: ID unique du job
        file_path: Chemin du document
        document_type_id: Type de document (optionnel)
        tenant_id: Tenant ID
        queue_name: Nom de la queue (optionnel)

    Returns:
        Job RQ
    """
    file_name = Path(file_path).name
    logger.info(f"[V2] Enqueueing: {file_name}")

    job = get_queue(queue_name).enqueue_call(
        func="knowbase.ingestion.queue.jobs_v2.ingest_document_v2_job",
        kwargs={
            "file_path": file_path,
            "document_type_id": document_type_id,
            "tenant_id": tenant_id,
        },
        job_id=job_id,
        result_ttl=DEFAULT_JOB_TIMEOUT,
        failure_ttl=DEFAULT_JOB_TIMEOUT,
        description=f"[V2] Document ingestion for {file_name}",
    )
    return _register_meta(
        job,
        job_type="ingest",
        pipeline_version="v2",
        document_type=document_type_id or "default",
        source=file_path,
    )


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
    # Route vers V2 si active et format supporte
    if _is_extraction_v2_enabled() and _is_format_supported_v2("pptx"):
        logger.info(f"[Dispatcher] Routing PPTX to V2 pipeline: {Path(file_path).name}")
        return enqueue_document_v2(
            job_id=job_id,
            file_path=file_path,
            document_type_id=document_type_id,
            queue_name=queue_name,
        )

    # Pipeline V1 legacy
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
    # Route vers V2 si active et format supporte
    if _is_extraction_v2_enabled() and _is_format_supported_v2("pdf"):
        logger.info(f"[Dispatcher] Routing PDF to V2 pipeline: {Path(file_path).name}")
        return enqueue_document_v2(
            job_id=job_id,
            file_path=file_path,
            document_type_id=document_type_id,
            queue_name=queue_name,
        )

    # Pipeline V1 legacy
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
    "enqueue_document_v2",
    "fetch_job",
    "get_queue",
]



