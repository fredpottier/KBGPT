"""
Rate Limiting Middleware - Phase 0.5 P0.5

Protection DOS sur endpoints critiques avec sliding window Redis

Usage:
    from knowbase.api.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        redis_url="redis://redis:6379/7",
        rate_limit=100,  # 100 requêtes
        window_seconds=60  # Par minute
    )
"""

import redis
import time
import logging
from typing import Callable, Optional
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting avec sliding window Redis

    Endpoints critiques protégés:
    - /api/canonicalization/merge
    - /api/canonicalization/undo
    - /api/canonicalization/bootstrap
    """

    def __init__(
        self,
        app: ASGIApp,
        redis_url: str = "redis://redis:6379/7",
        rate_limit: int = 100,
        window_seconds: int = 60,
        enabled: bool = True
    ):
        super().__init__(app)
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.rate_limit = rate_limit
        self.window = window_seconds
        self.enabled = enabled

        logger.info(
            f"RateLimitMiddleware: {rate_limit} req/{window_seconds}s "
            f"(enabled={enabled})"
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Rate limit uniquement endpoints critiques
        if not self._is_rate_limited_endpoint(request.url.path):
            return await call_next(request)

        # Identifier client (IP)
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{request.url.path}:{client_ip}"

        # Sliding window check
        current_time = int(time.time())
        window_start = current_time - self.window

        # Supprimer entrées expirées
        self.redis.zremrangebyscore(key, 0, window_start)

        # Ajouter requête actuelle dans fenêtre (UUID pour éviter collision timestamp)
        import uuid
        member = f"{current_time}:{uuid.uuid4().hex[:8]}"
        self.redis.zadd(key, {member: current_time})
        self.redis.expire(key, self.window)

        # Compter requêtes dans fenêtre (incluant actuelle)
        count = self.redis.zcard(key)

        if count > self.rate_limit:
            logger.warning(
                f"⛔ Rate limit exceeded: {client_ip} "
                f"{request.method} {request.url.path} "
                f"({count}/{self.rate_limit} in {self.window}s)"
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {self.rate_limit} requests per {self.window}s"
            )

        return await call_next(request)

    def _is_rate_limited_endpoint(self, path: str) -> bool:
        """Vérifie si endpoint doit être rate-limited"""
        critical_paths = [
            "/api/canonicalization/merge",
            "/api/canonicalization/undo",
            "/api/canonicalization/bootstrap"
        ]
        return any(path.startswith(p) for p in critical_paths)
