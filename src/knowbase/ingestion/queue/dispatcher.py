"""
Dispatcher - Route les documents vers le pipeline V2 unifie.

Tous les formats (PDF, PPTX, DOCX, XLSX) passent par ExtractionPipelineV2
avec Docling + Vision Gating V4.

Legacy V1 supprime - Cleanup 2025-01-05.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import logging

from rq.job import Job
from rq.exceptions import NoSuchJobError

from knowbase.config.settings import get_settings
from .connection import DEFAULT_JOB_TIMEOUT, get_queue

SETTINGS = get_settings()
logger = logging.getLogger(__name__)


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
    """Route PPTX vers pipeline V2 unifie."""
    logger.info(f"[Dispatcher] Routing PPTX to V2 pipeline: {Path(file_path).name}")
    return enqueue_document_v2(
        job_id=job_id,
        file_path=file_path,
        document_type_id=document_type_id,
        queue_name=queue_name,
    )


def enqueue_pdf_ingestion(
    *,
    job_id: str,
    file_path: str,
    document_type_id: Optional[str] = None,
    use_vision: bool = True,
    queue_name: Optional[str] = None,
) -> Job:
    """Route PDF vers pipeline V2 unifie."""
    logger.info(f"[Dispatcher] Routing PDF to V2 pipeline: {Path(file_path).name}")
    return enqueue_document_v2(
        job_id=job_id,
        file_path=file_path,
        document_type_id=document_type_id,
        queue_name=queue_name,
    )


def enqueue_excel_ingestion(
    *,
    job_id: str,
    file_path: str,
    meta: Optional[dict[str, Any]] = None,
    queue_name: Optional[str] = None,
) -> Job:
    job = get_queue(queue_name).enqueue_call(
        func="knowbase.ingestion.queue.jobs_v2.ingest_excel_job",
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
        func="knowbase.ingestion.queue.jobs_v2.fill_excel_job",
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


# ===============================================================================
# Claim-First Pipeline (Pivot Epistémique)
# ===============================================================================

def enqueue_claimfirst_process(
    doc_ids: list[str],
    tenant_id: str = "default",
    queue_name: Optional[str] = None,
    cache_dir: str = "/data/extraction_cache",
) -> Job:
    """
    Enqueue un job de traitement claim-first.

    Args:
        doc_ids: Liste des document IDs à traiter
        tenant_id: Tenant ID
        queue_name: Nom de la queue (optionnel, défaut: reprocess)
        cache_dir: Répertoire du cache d'extraction

    Returns:
        Job RQ
    """
    from uuid import uuid4

    job_id = f"claimfirst_{uuid4().hex[:8]}"
    queue_name = queue_name or "reprocess"

    logger.info(
        f"[ClaimFirst] Enqueueing {len(doc_ids)} documents for claim-first processing"
    )

    job = get_queue(queue_name).enqueue_call(
        func="knowbase.claimfirst.worker_job.claimfirst_process_job",
        kwargs={
            "doc_ids": doc_ids,
            "tenant_id": tenant_id,
            "cache_dir": cache_dir,
        },
        job_id=job_id,
        result_ttl=7200,  # 2 heures
        failure_ttl=7200,
        timeout=7200,  # 2 heures max (gros documents)
        description=f"Claim-First processing for {len(doc_ids)} documents",
    )

    return _register_meta(
        job,
        job_type="claimfirst",
        pipeline_version="claimfirst_v1",
        document_count=len(doc_ids),
    )


def get_claimfirst_status() -> dict:
    """
    Récupère l'état actuel du job claim-first.

    Returns:
        État du job depuis Redis
    """
    from knowbase.claimfirst.worker_job import get_claimfirst_status as _get_status
    return _get_status()


__all__ = [
    "enqueue_pptx_ingestion",
    "enqueue_pdf_ingestion",
    "enqueue_excel_ingestion",
    "enqueue_fill_excel",
    "enqueue_document_v2",
    "enqueue_claimfirst_process",
    "get_claimfirst_status",
    "fetch_job",
    "get_queue",
]



