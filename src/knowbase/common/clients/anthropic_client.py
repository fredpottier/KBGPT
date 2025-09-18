from __future__ import annotations

from functools import lru_cache

from knowbase.config.settings import get_settings
from .http import get_http_client

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    Anthropic = None


@lru_cache(maxsize=1)
def get_anthropic_client() -> Anthropic:
    """Obtient un client Anthropic configuré avec la clé API."""
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError(
            "Anthropic client not available. Install with: pip install anthropic"
        )

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    return Anthropic(
        api_key=settings.anthropic_api_key,
        http_client=get_http_client()
    )


def is_anthropic_available() -> bool:
    """Vérifie si le client Anthropic est disponible et configuré."""
    try:
        get_anthropic_client()
        return True
    except RuntimeError:
        return False