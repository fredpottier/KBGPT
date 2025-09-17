from __future__ import annotations

import httpx


class CustomHTTPClient(httpx.Client):
    """HTTP client that ignores system proxy settings."""

    def __init__(self, *args, **kwargs):
        kwargs.pop("proxies", None)
        super().__init__(*args, **kwargs, trust_env=False)


_client: CustomHTTPClient | None = None


def get_http_client() -> CustomHTTPClient:
    global _client
    if _client is None:
        _client = CustomHTTPClient()
    return _client
