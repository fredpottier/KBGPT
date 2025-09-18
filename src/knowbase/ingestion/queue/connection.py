from __future__ import annotations

import os
from functools import lru_cache

import redis
from rq import Queue

DEFAULT_QUEUE_NAME = os.getenv("INGESTION_QUEUE", "ingestion")
DEFAULT_JOB_TIMEOUT = int(os.getenv("INGESTION_JOB_TIMEOUT", "7200"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


@lru_cache(maxsize=1)
def get_redis_connection() -> redis.Redis:
    """Return a cached Redis connection for the ingestion queue."""
    return redis.from_url(REDIS_URL)


def get_queue(name: str | None = None, *, timeout: int | None = None) -> Queue:
    """Return an RQ queue configured for ingestion jobs."""
    queue_name = name or DEFAULT_QUEUE_NAME
    queue_timeout = timeout or DEFAULT_JOB_TIMEOUT
    return Queue(queue_name, connection=get_redis_connection(), default_timeout=queue_timeout)


__all__ = [
    "DEFAULT_QUEUE_NAME",
    "DEFAULT_JOB_TIMEOUT",
    "get_redis_connection",
    "get_queue",
]
