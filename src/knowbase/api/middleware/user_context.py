"""
Middleware de contexte utilisateur pour Knowledge Graph multi-tenant
Gère la conversion X-User-ID → group_id et l'injection du contexte utilisateur
"""

import logging
from typing import Optional, Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time

from knowbase.api.services.user import UserService

logger = logging.getLogger(__name__)

# Service utilisateur initialisé de manière lazy pour éviter race condition
_user_service = None

def get_user_service():
    """Lazy initialization du UserService"""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service

class UserContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware FastAPI pour gestion du contexte utilisateur

    Fonctionnalités:
    - Interception header X-User-ID
    - Mapping vers group_user_{id}
    - Validation existence utilisateur
    - Injection contexte dans request.state
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Traitement middleware pour chaque requête

        Args:
            request: Requête FastAPI entrante
            call_next: Fonction suivante dans la chaîne

        Returns:
            Response avec contexte utilisateur injecté
        """
        start_time = time.time()

        # Initialiser le contexte par défaut
        request.state.user_id = None
        request.state.group_id = "corporate"  # Défaut: groupe corporate
        request.state.is_personal_kg = False

        # Vérifier si la route concerne le Knowledge Graph
        is_kg_route = "/knowledge-graph" in str(request.url.path)

        if is_kg_route:
            # Extraire le header X-User-ID
            user_id = request.headers.get("X-User-ID")

            if user_id:
                try:
                    # Valider que l'utilisateur existe
                    user_service = get_user_service()
                    user = user_service.get_user(user_id)

                    if user:
                        # Mapping user_id → group_id
                        group_id = f"user_{user_id}"

                        # Injecter dans le contexte de la requête
                        request.state.user_id = user_id
                        request.state.group_id = group_id
                        request.state.is_personal_kg = True
                        request.state.user_data = user

                        logger.info(f"Contexte utilisateur injecté: {user_id} → {group_id}")

                    else:
                        # Utilisateur non trouvé - retourner erreur
                        logger.warning(f"Utilisateur non trouvé: {user_id}")
                        return JSONResponse(
                            status_code=404,
                            content={
                                "detail": f"Utilisateur {user_id} non trouvé",
                                "error_code": "USER_NOT_FOUND"
                            }
                        )

                except Exception as e:
                    logger.error(f"Erreur validation utilisateur {user_id}: {e}")
                    # En cas d'erreur, continuer en mode corporate plutôt que crash
                    logger.warning(f"Utilisation mode corporate pour {user_id} après erreur validation")
                    request.state.user_id = None
                    request.state.group_id = "corporate"
                    request.state.is_personal_kg = False
            else:
                # Pas de X-User-ID → utiliser groupe corporate par défaut
                logger.debug("Pas de X-User-ID, utilisation groupe corporate")

        # Continuer la chaîne de traitement
        try:
            response = await call_next(request)

            # Ajouter métriques de performance
            duration_ms = (time.time() - start_time) * 1000

            # Ajouter headers de contexte dans la réponse
            if is_kg_route:
                response.headers["X-Context-Group-ID"] = request.state.group_id
                response.headers["X-Context-Personal"] = str(request.state.is_personal_kg).lower()
                response.headers["X-Middleware-Duration"] = f"{duration_ms:.2f}ms"

                # Logging performance
                if duration_ms > 50:  # Target: < 50ms
                    logger.warning(f"Middleware lent: {duration_ms:.2f}ms > 50ms")
                else:
                    logger.debug(f"Middleware performance: {duration_ms:.2f}ms")

            return response

        except Exception as e:
            logger.error(f"Erreur middleware: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Erreur interne middleware",
                    "error_code": "MIDDLEWARE_ERROR"
                }
            )


def get_user_context(request: Request) -> dict:
    """
    Utilitaire pour extraire le contexte utilisateur de la requête

    Args:
        request: Requête FastAPI

    Returns:
        Dictionnaire avec contexte utilisateur
    """
    return {
        "user_id": getattr(request.state, "user_id", None),
        "group_id": getattr(request.state, "group_id", "corporate"),
        "is_personal_kg": getattr(request.state, "is_personal_kg", False),
        "user_data": getattr(request.state, "user_data", None)
    }


def require_user_context(request: Request) -> dict:
    """
    Utilitaire pour forcer la présence d'un contexte utilisateur

    Args:
        request: Requête FastAPI

    Returns:
        Contexte utilisateur valide

    Raises:
        HTTPException: Si pas de contexte utilisateur
    """
    context = get_user_context(request)

    if not context["user_id"]:
        raise HTTPException(
            status_code=401,
            detail="Header X-User-ID requis pour cette opération",
            headers={"WWW-Authenticate": "X-User-ID"}
        )

    return context