"""
Request ID Middleware - Phase 0.5 P0.4

Ajoute request_id unique à chaque requête HTTP pour traçabilité distribuée:
- Génère UUID unique par requête
- Propage dans tous les logs via contextvars
- Retourne request_id dans response headers (X-Request-ID)
- Permet debugging multi-services (corrélation logs)

Usage:
    from knowbase.api.middleware.request_id import RequestIDMiddleware, get_request_id

    app.add_middleware(RequestIDMiddleware)

    # Dans n'importe quel code:
    request_id = get_request_id()
    logger.info(f"Processing {request_id}")  # Automatiquement ajouté aux logs
"""

import uuid
import logging
import contextvars
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ContextVar pour stocker request_id thread-safe
_request_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="no-request-id"
)


def get_request_id() -> str:
    """
    Récupérer request_id actuel depuis context

    Returns:
        Request ID actuel (UUID) ou "no-request-id" si hors requête HTTP
    """
    return _request_id_ctx_var.get()


def set_request_id(request_id: str) -> None:
    """
    Définir request_id dans context (usage interne middleware)

    Args:
        request_id: UUID unique de la requête
    """
    _request_id_ctx_var.set(request_id)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware FastAPI pour injection request_id

    Fonctionnement:
    1. Génère UUID unique pour chaque requête
    2. Stocke dans contextvars (accessible partout)
    3. Ajoute header X-Request-ID dans response
    4. Configure LoggerAdapter pour injection auto dans logs

    Note: Utilise contextvars (thread-safe) pour async compatibility
    """

    def __init__(self, app: ASGIApp):
        """
        Initialize middleware

        Args:
            app: Application ASGI FastAPI
        """
        super().__init__(app)
        logger.info("RequestIDMiddleware initialized")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request avec request_id injection

        Args:
            request: Requête HTTP entrante
            call_next: Next middleware/handler dans chaîne

        Returns:
            Response avec header X-Request-ID
        """
        # Générer request_id unique
        # Accepter X-Request-ID du client si fourni (propagation multi-services)
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Stocker dans context
        set_request_id(request_id)

        # Logger début requête avec request_id
        logger.info(
            f"→ {request.method} {request.url.path} "
            f"[req_id={request_id[:12]}...]"
        )

        try:
            # Exécuter requête
            response = await call_next(request)

            # Ajouter request_id dans response headers
            response.headers["X-Request-ID"] = request_id

            # Logger fin requête
            logger.info(
                f"← {request.method} {request.url.path} "
                f"status={response.status_code} "
                f"[req_id={request_id[:12]}...]"
            )

            return response

        except Exception as e:
            # Logger erreur avec request_id
            logger.error(
                f"✗ {request.method} {request.url.path} "
                f"error={type(e).__name__}: {str(e)[:50]} "
                f"[req_id={request_id[:12]}...]",
                exc_info=True
            )
            raise


class RequestIDLogFilter(logging.Filter):
    """
    Filter pour injecter request_id dans tous les logs

    Usage:
        handler = logging.StreamHandler()
        handler.addFilter(RequestIDLogFilter())
        logger.addHandler(handler)

    Résultat logs:
        INFO [req_id=abc123...] Processing merge canonical=xyz...
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Inject request_id dans LogRecord

        Args:
            record: Log record à enrichir

        Returns:
            True (toujours accepter le log)
        """
        # Récupérer request_id depuis context
        request_id = get_request_id()

        # Ajouter comme attribut du LogRecord
        record.request_id = request_id[:12] if request_id != "no-request-id" else "------"

        return True


def configure_request_id_logging():
    """
    Configure logging global pour injection request_id automatique

    Ajoute RequestIDLogFilter à tous les handlers existants

    À appeler au démarrage app:
        from knowbase.api.middleware.request_id import configure_request_id_logging
        configure_request_id_logging()
    """
    # Récupérer root logger
    root_logger = logging.getLogger()

    # Ajouter filter à tous les handlers
    for handler in root_logger.handlers:
        handler.addFilter(RequestIDLogFilter())

    # Modifier format pour inclure request_id
    for handler in root_logger.handlers:
        if handler.formatter:
            # Garder format existant et ajouter request_id
            current_format = handler.formatter._fmt
            if "request_id" not in current_format:
                # Insérer request_id après timestamp/level
                new_format = current_format.replace(
                    "%(levelname)s:",
                    "%(levelname)s: [req=%(request_id)s]"
                )
                handler.setFormatter(logging.Formatter(new_format))

    logger.info("✅ Request ID logging configured (filter added to all handlers)")


def get_request_context() -> dict:
    """
    Récupérer contexte complet de la requête actuelle

    Returns:
        Dict avec request_id et autres métadonnées contextuelles

    Usage:
        ctx = get_request_context()
        logger.info(f"Processing with context: {ctx}")
    """
    return {
        "request_id": get_request_id(),
        # Extensible: ajouter user_id, tenant_id, etc.
    }
