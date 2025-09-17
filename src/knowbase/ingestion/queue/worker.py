from __future__ import annotations

import logging

from rq import Worker

from knowbase.common.clients import (
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)

from .connection import DEFAULT_QUEUE_NAME, get_queue, get_redis_connection


def warm_clients() -> None:
    """Preload shared heavy clients so all jobs reuse the same instances."""
    get_openai_client()
    get_qdrant_client()
    get_sentence_transformer()


def run_worker(*, queue_name: str | None = None, with_scheduler: bool = True) -> None:
    warm_clients()
    queue = get_queue(queue_name)
    worker = Worker([queue.name], connection=get_redis_connection())
    worker.work(with_scheduler=with_scheduler, logging_level=logging.INFO)


def main() -> None:
    run_worker(queue_name=DEFAULT_QUEUE_NAME)


__all__ = [
    "run_worker",
    "main",
]
