"""
Token manager partage pour les runners de benchmark.

Gere automatiquement le refresh du JWT OSMOSIS avant expiration,
pour les runs longs (> 1h) qui depassent le TTL du token.
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)


class TokenManager:
    """Cache un token JWT et le rafraichit automatiquement avant expiration.

    Usage:
        tm = TokenManager("http://app:8000")
        headers = {"Authorization": f"Bearer {tm.get()}"}

    Le token est renouvele automatiquement 60s avant son expiration.
    """

    def __init__(
        self,
        api_base: str,
        email: str = "admin@example.com",
        password: str = "admin123",
        refresh_margin_s: int = 60,
    ):
        self.api_base = api_base.rstrip("/")
        self.email = email
        self.password = password
        self.refresh_margin_s = refresh_margin_s
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str:
        """Retourne un token valide, en le rafraichissant si necessaire."""
        now = time.time()
        if self._token is None or now >= self._expires_at - self.refresh_margin_s:
            self._refresh()
        return self._token  # type: ignore[return-value]

    def _refresh(self) -> None:
        resp = requests.post(
            f"{self.api_base}/api/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"[BENCH:AUTH] Login failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        data = resp.json()
        self._token = data.get("access_token")
        if not self._token:
            raise RuntimeError("[BENCH:AUTH] Login OK but no access_token in response")
        expires_in = data.get("expires_in", 3600)
        self._expires_at = time.time() + expires_in
        logger.info(
            f"[BENCH:AUTH] Token refreshed (TTL={expires_in}s, "
            f"next refresh in {expires_in - self.refresh_margin_s}s)"
        )
