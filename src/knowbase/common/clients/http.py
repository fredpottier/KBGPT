from __future__ import annotations

import httpx


class CustomHTTPClient(httpx.Client):
    """HTTP client that ignores system proxy settings (synchronous)."""

    def __init__(self, *args, **kwargs):
        # Enlever proxies pour éviter conflits avec proxy système
        kwargs.pop("proxies", None)
        super().__init__(*args, **kwargs, trust_env=False)


class CustomAsyncHTTPClient(httpx.AsyncClient):
    """Async HTTP client that ignores system proxy settings (asynchronous)."""

    def __init__(self, *args, **kwargs):
        # Enlever proxies pour éviter conflits avec proxy système
        kwargs.pop("proxies", None)
        super().__init__(*args, **kwargs, trust_env=False)


# Singletons séparés pour sync et async (IMPORTANT: ne jamais mélanger!)
_sync_client: CustomHTTPClient | None = None
_async_client: CustomAsyncHTTPClient | None = None


def get_http_client() -> CustomHTTPClient:
    """Retourne le client HTTP synchrone (singleton)."""
    global _sync_client
    if _sync_client is None:
        _sync_client = CustomHTTPClient()
    return _sync_client


def get_async_http_client() -> CustomAsyncHTTPClient:
    """Retourne le client HTTP asynchrone (singleton).

    IMPORTANT: Ce client est distinct du client sync et doit être utilisé
    uniquement avec AsyncOpenAI, jamais avec OpenAI sync.
    """
    global _async_client
    if _async_client is None:
        _async_client = CustomAsyncHTTPClient()
    return _async_client
