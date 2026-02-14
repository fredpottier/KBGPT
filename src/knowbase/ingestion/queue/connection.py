from __future__ import annotations

import os
from functools import lru_cache

import redis
from rq import Queue

from knowbase.config.settings import get_settings

DEFAULT_QUEUE_NAME = os.getenv("INGESTION_QUEUE", "ingestion")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def get_default_job_timeout() -> int:
    """
    Retourne le timeout RQ job par défaut.
    Utilise settings.ingestion_job_timeout qui calcule automatiquement depuis
    MAX_DOCUMENT_PROCESSING_TIME (ou utilise INGESTION_JOB_TIMEOUT si fourni).
    """
    settings = get_settings()
    return settings.ingestion_job_timeout


# Legacy: DEFAULT_JOB_TIMEOUT pour backward compatibility
DEFAULT_JOB_TIMEOUT = get_default_job_timeout()


@lru_cache(maxsize=1)
def get_redis_connection() -> redis.Redis:
    """Return a cached Redis connection for the ingestion queue.

    Configure socket_keepalive et health_check_interval pour éviter
    les déconnexions TCP idle (Docker Desktop Windows coupe après ~5 min).
    """
    return redis.from_url(
        REDIS_URL,
        socket_keepalive=True,
        socket_timeout=300,
        socket_connect_timeout=10,
        health_check_interval=60,
        retry_on_timeout=True,
    )


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
