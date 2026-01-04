# Force 'spawn' method for CUDA compatibility with multiprocessing
import multiprocessing
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    # Already set, ignore
    pass

from .connection import (
    DEFAULT_JOB_TIMEOUT,
    DEFAULT_QUEUE_NAME,
    get_queue,
    get_redis_connection,
)
from .dispatcher import (
    enqueue_pptx_ingestion,
    enqueue_pdf_ingestion,
    enqueue_excel_ingestion,
    enqueue_fill_excel,
    enqueue_document_v2,
    fetch_job,
)
from .jobs import (
    send_worker_heartbeat,
    update_job_progress,
)
__all__ = [
    "DEFAULT_JOB_TIMEOUT",
    "DEFAULT_QUEUE_NAME",
    "get_queue",
    "get_redis_connection",
    "enqueue_pptx_ingestion",
    "enqueue_pdf_ingestion",
    "enqueue_excel_ingestion",
    "enqueue_fill_excel",
    "enqueue_document_v2",
    "fetch_job",
    "send_worker_heartbeat",
    "update_job_progress",
]
