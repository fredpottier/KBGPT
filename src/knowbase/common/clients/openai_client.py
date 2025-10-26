from __future__ import annotations

from functools import lru_cache

from openai import OpenAI, AsyncOpenAI

from knowbase.config.settings import get_settings
from .http import get_http_client


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key, http_client=get_http_client())


@lru_cache(maxsize=1)
def get_async_openai_client() -> AsyncOpenAI:
    """Retourne un client OpenAI async pour les appels parallèles."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key, http_client=get_http_client())
