"""Compatibility layer exposing queue helpers from knowbase package."""

from __future__ import annotations

from typing import Any, Optional

from knowbase.ingestion.queue import (
    DEFAULT_JOB_TIMEOUT,
    DEFAULT_QUEUE_NAME,
    enqueue_excel_ingestion,
    enqueue_fill_excel,
    enqueue_pdf_ingestion,
    enqueue_pptx_ingestion,
    fetch_job,
    get_queue,
    get_redis_connection,
)

__all__ = [
    "DEFAULT_JOB_TIMEOUT",
    "DEFAULT_QUEUE_NAME",
    "enqueue_pptx_ingestion",
    "enqueue_pdf_ingestion",
    "enqueue_excel_ingestion",
    "enqueue_fill_excel",
    "fetch_job",
    "get_queue",
    "get_redis_connection",
]
