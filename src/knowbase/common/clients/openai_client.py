from __future__ import annotations

from functools import lru_cache

from openai import OpenAI, AsyncOpenAI

from knowbase.config.settings import get_settings
from .http import get_http_client, get_async_http_client


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key, http_client=get_http_client())


@lru_cache(maxsize=1)
def get_async_openai_client() -> AsyncOpenAI:
    """Retourne un client OpenAI async pour les appels parallèles.

    Note: N'utilise plus de http_client custom car OpenAI 1.55+ valide strictement
    le type et gère nativement les proxies avec trust_env=False.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    # OpenAI 1.55+ : validation stricte du http_client, on laisse le client par défaut
    return AsyncOpenAI(api_key=settings.openai_api_key)
