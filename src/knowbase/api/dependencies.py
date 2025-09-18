from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable

from fastapi import Request

from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings


@lru_cache(maxsize=1)
def get_logger() -> logging.Logger:
    settings = get_settings()
    return logging.getLogger("knowbase.api")


def configure_logging() -> logging.Logger:
    settings = get_settings()
    from knowbase.common.logging import setup_logging

    return setup_logging(settings.logs_dir, "app_debug.log", "knowbase.api")


def warm_clients() -> None:
    ensure_qdrant_collection(
        get_settings().qdrant_collection,
        get_sentence_transformer().get_sentence_embedding_dimension() or 768,
    )
    get_openai_client()
    get_qdrant_client()


__all__ = [
    "get_settings",
    "get_logger",
    "configure_logging",
    "warm_clients",
    "get_openai_client",
    "get_qdrant_client",
    "get_sentence_transformer",
]
