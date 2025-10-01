"""
Middleware Idempotence pour garantir rejouabilité opérations sans effets de bord
Stocke résultats dans Redis avec TTL 24h pour replay avec Idempotency-Key
"""

import json
import hashlib
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import redis

logger = logging.getLogger(__name__)

# Endpoints nécessitant idempotence
IDEMPOTENT_ENDPOINTS = [
    "/api/canonicalization/merge",
    "/api/canonicalization/create-new",
]


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware garantissant idempotence des opérations critiques

    Fonctionnement:
    1. Vérifie présence header Idempotency-Key sur endpoints critiques
    2. Check cache Redis avec clé = Idempotency-Key
    3. Si présent dans cache → retourne résultat mis en cache
    4. Sinon → exécute requête, stocke résultat en cache (TTL 24h)

    Garanties:
    - Replay avec même Idempotency-Key → résultat identique (bit-à-bit)
    - TTL 24h permet rejouabilité pendant période critique
    - Audit trail dans logs avec Idempotency-Key
    """

    def __init__(self, app, redis_url: str = "redis://redis:6379/2"):
        """
        Initialize idempotency middleware

        Args:
            app: FastAPI application
            redis_url: Redis connection URL (DB 2 pour idempotence)
        """
        super().__init__(app)
        self.redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = 24 * 60 * 60  # 24h

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request avec idempotence check

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response (cached ou fresh)
        """
        # Check si endpoint nécessite idempotence
        if not self._requires_idempotency(request):
            return await call_next(request)

        # Vérifier présence Idempotency-Key
        idempotency_key = request.headers.get("Idempotency-Key")

        if not idempotency_key:
            logger.error(
                f"Idempotency-Key manquant sur {request.url.path} "
                f"(méthode: {request.method})"
            )
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "Header 'Idempotency-Key' obligatoire pour cet endpoint",
                    "idempotent_endpoint": True,
                    "path": str(request.url.path)
                }
            )

        # Lire body de la requête pour validation
        body_bytes = await request.body()
        request_body_hash = self._compute_body_hash(body_bytes)

        # Générer clé Redis unique
        cache_key = self._generate_cache_key(request, idempotency_key)

        # Check cache Redis
        cached_response = self._get_cached_response(cache_key)

        if cached_response:
            # Vérifier que le body est identique (standard RFC 9110)
            cached_body_hash = cached_response.get("request_body_hash")

            if cached_body_hash and cached_body_hash != request_body_hash:
                logger.warning(
                    f"Idempotence CONFLICT: {request.url.path} "
                    f"[key={idempotency_key[:12]}...] "
                    f"Même Idempotency-Key mais body différent "
                    f"(cached_hash={cached_body_hash[:12]}... vs current_hash={request_body_hash[:12]}...)"
                )
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "IdempotencyKeyConflict",
                        "detail": "Idempotency-Key déjà utilisée avec un payload différent",
                        "idempotency_key": idempotency_key[:12] + "...",
                        "suggestion": "Utilisez une nouvelle Idempotency-Key ou vérifiez votre payload"
                    }
                )

            logger.info(
                f"Idempotence HIT: {request.url.path} "
                f"[key={idempotency_key[:12]}...] (replay détecté, body identique)"
            )
            return JSONResponse(
                status_code=cached_response["status_code"],
                content=cached_response["body"],
                headers={
                    **cached_response.get("headers", {}),
                    "X-Idempotency-Replay": "true"
                }
            )

        # Exécuter requête
        logger.info(
            f"Idempotence MISS: {request.url.path} "
            f"[key={idempotency_key[:12]}...] (première exécution)"
        )

        response = await call_next(request)

        # Stocker résultat en cache (uniquement si succès 2xx)
        if 200 <= response.status_code < 300:
            await self._cache_response(cache_key, response, idempotency_key, request, request_body_hash)

        return response

    def _requires_idempotency(self, request: Request) -> bool:
        """
        Check si endpoint nécessite idempotence

        Args:
            request: FastAPI request

        Returns:
            True si endpoint nécessite Idempotency-Key
        """
        # Seulement POST/PUT sur endpoints critiques
        if request.method not in ["POST", "PUT"]:
            return False

        # Check path exact
        path = str(request.url.path)
        return any(path.startswith(endpoint) for endpoint in IDEMPOTENT_ENDPOINTS)

    def _compute_body_hash(self, body_bytes: bytes) -> str:
        """
        Calcule hash SHA256 du body de la requête

        Args:
            body_bytes: Body bytes de la requête

        Returns:
            Hash SHA256 (hex string)
        """
        if not body_bytes:
            return "empty"
        return hashlib.sha256(body_bytes).hexdigest()

    def _generate_cache_key(self, request: Request, idempotency_key: str) -> str:
        """
        Génère clé Redis unique pour cette requête

        Format: idempotence:{endpoint}:{idempotency_key}

        Note: Le hash du body n'est PAS inclus dans la clé cache.
        Au lieu de cela, le hash est stocké avec la réponse et validé
        lors du replay pour détecter les conflits (409 Conflict).

        Args:
            request: FastAPI request
            idempotency_key: Header Idempotency-Key value

        Returns:
            Clé Redis unique
        """
        endpoint = str(request.url.path).replace("/", "_")
        return f"idempotence:{endpoint}:{idempotency_key}"

    def _get_cached_response(self, cache_key: str) -> dict | None:
        """
        Récupère réponse mise en cache depuis Redis

        Args:
            cache_key: Clé Redis

        Returns:
            Dict avec status_code, body, headers ou None si absent
        """
        try:
            cached_data = self.redis_client.get(cache_key)

            if cached_data:
                return json.loads(cached_data)

            return None

        except Exception as e:
            logger.error(f"Erreur lecture cache idempotence: {e}", exc_info=True)
            return None

    async def _cache_response(
        self,
        cache_key: str,
        response: Response,
        idempotency_key: str,
        request: Request,
        request_body_hash: str
    ) -> None:
        """
        Stocke réponse en cache Redis avec TTL 24h

        Args:
            cache_key: Clé Redis
            response: Response à mettre en cache
            idempotency_key: Header Idempotency-Key value
            request: Request originale
            request_body_hash: Hash SHA256 du body de la requête
        """
        try:
            # Lire body de la response
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            # Parser JSON body
            try:
                body_json = json.loads(body_bytes.decode())
            except json.JSONDecodeError:
                body_json = {"raw": body_bytes.decode()}

            # Préparer données cache (inclure hash du request body pour validation)
            cache_data = {
                "status_code": response.status_code,
                "body": body_json,
                "headers": dict(response.headers),
                "cached_at": json.dumps({"timestamp": "now"}),  # Simplifié
                "idempotency_key": idempotency_key,
                "endpoint": str(request.url.path),
                "method": request.method,
                "request_body_hash": request_body_hash  # ✅ AJOUTÉ: Stocké pour validation 409
            }

            # Stocker en Redis avec TTL 24h
            self.redis_client.setex(
                cache_key,
                self.ttl_seconds,
                json.dumps(cache_data)
            )

            logger.info(
                f"Idempotence CACHE: {request.url.path} "
                f"[key={idempotency_key[:12]}...] [body_hash={request_body_hash[:12]}...] "
                f"(TTL {self.ttl_seconds}s)"
            )

            # Recréer body iterator pour response
            async def new_body_iterator():
                yield body_bytes

            response.body_iterator = new_body_iterator()

        except Exception as e:
            logger.error(
                f"Erreur stockage cache idempotence: {e}",
                exc_info=True
            )
