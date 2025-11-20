from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable

from fastapi import Request

from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


@lru_cache(maxsize=1)
def get_logger() -> logging.Logger:
    settings = get_settings()
    return logging.getLogger("knowbase.api")


def configure_logging() -> logging.Logger:
    settings = get_settings()
    from knowbase.common.logging import setup_logging

    return setup_logging(settings.logs_dir, "app_debug.log", "knowbase.api")


def warm_clients() -> None:
    ensure_qdrant_collection(
        get_settings().qdrant_collection,
        get_sentence_transformer().get_sentence_embedding_dimension() or 1024,
    )
    get_openai_client()
    get_qdrant_client()


# === Auth dependencies (Phase 0) ===

# HTTP Bearer security scheme
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Dependency pour extraire l'utilisateur courant depuis le JWT token.

    Args:
        credentials: Credentials HTTP Bearer

    Returns:
        Claims JWT (user_id, email, role, tenant_id)

    Raises:
        HTTPException: Si token invalide ou expiré
    """
    from knowbase.api.services.auth_service import get_auth_service

    auth_service = get_auth_service()
    token = credentials.credentials

    # Vérifier que c'est un access token valide
    claims = auth_service.verify_access_token(token)

    return claims


def require_role(required_role: str) -> Callable:
    """
    Factory pour créer une dependency qui vérifie le rôle utilisateur.

    Args:
        required_role: Rôle requis ("admin", "editor", "viewer")

    Returns:
        Dependency function

    Raises:
        HTTPException: Si utilisateur n'a pas le rôle requis
    """
    def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        """
        Vérifie que l'utilisateur a le rôle requis.

        Hiérarchie des rôles:
        - admin: Peut tout faire
        - editor: Peut créer/modifier (mais pas delete)
        - viewer: Peut seulement lire

        Args:
            current_user: Claims JWT de l'utilisateur courant

        Returns:
            Claims JWT si autorisé

        Raises:
            HTTPException: Si rôle insuffisant
        """
        user_role = current_user.get("role")

        # Admin peut tout faire
        if user_role == "admin":
            return current_user

        # Vérifier rôle requis
        if user_role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle insuffisant. Requis: {required_role}, actuel: {user_role}"
            )

        return current_user

    return role_checker


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency pour vérifier que l'utilisateur est admin.

    Args:
        current_user: Claims JWT de l'utilisateur courant

    Returns:
        Claims JWT si admin

    Raises:
        HTTPException: Si pas admin
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action réservée aux administrateurs"
        )
    return current_user


def require_editor(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency pour vérifier que l'utilisateur est editor ou admin.

    Args:
        current_user: Claims JWT de l'utilisateur courant

    Returns:
        Claims JWT si editor ou admin

    Raises:
        HTTPException: Si viewer
    """
    user_role = current_user.get("role")

    if user_role not in ["admin", "editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action réservée aux editors et admins"
        )

    return current_user


def get_tenant_id(current_user: dict = Depends(get_current_user)) -> str:
    """
    Dependency pour extraire le tenant_id depuis le JWT token.

    Remplace les tenant_id passés en query params (sécurité).

    Args:
        current_user: Claims JWT de l'utilisateur courant

    Returns:
        Tenant ID

    Raises:
        HTTPException: Si tenant_id manquant dans token
    """
    tenant_id = current_user.get("tenant_id")

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="tenant_id manquant dans token JWT"
        )

    return tenant_id


__all__ = [
    "get_settings",
    "get_logger",
    "configure_logging",
    "warm_clients",
    "get_openai_client",
    "get_qdrant_client",
    "get_sentence_transformer",
    # Auth dependencies (Phase 0)
    "get_current_user",
    "require_role",
    "require_admin",
    "require_editor",
    "get_tenant_id",
]
