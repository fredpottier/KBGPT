"""Entry-point for the ingestion worker process."""

from __future__ import annotations

import logging
from rq import Worker

from ingestion import INGESTION_QUEUE
from ingestion.job_queue import get_redis_connection
from utils.shared_clients import (
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)


def warm_clients() -> None:
    """Load heavy shared clients so they are reused by all jobs."""
    get_openai_client()
    get_qdrant_client()
    get_sentence_transformer()


def main() -> None:
    warm_clients()
    worker = Worker([INGESTION_QUEUE], connection=get_redis_connection())
    worker.work(with_scheduler=True, logging_level=logging.INFO)


if __name__ == "__main__":
    main()
