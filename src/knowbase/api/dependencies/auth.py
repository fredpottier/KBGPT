"""
Dépendances d'authentification et autorisation.

Phase 3 - Security & RBAC

Note: Système simplifié pour Phase 3.
TODO Production: Implémenter JWT complet avec tokens signés.
"""

from fastapi import Header, HTTPException, status
from typing import Optional


def require_admin(
    x_admin_key: Optional[str] = Header(None, description="Admin API key")
) -> dict:
    """
    Vérifie que la requête provient d'un admin.

    **Phase 3 - Simplified Auth**:
    Utilise un header X-Admin-Key pour authentification basique.

    **TODO Production**:
    Remplacer par JWT avec:
    - Token signé (RS256/HS256)
    - Claims: user_id, email, role, tenant_id
    - Expiration et refresh tokens
    - Validation signature

    Args:
        x_admin_key: Clé admin dans header

    Returns:
        dict: User info avec email et role

    Raises:
        HTTPException: 401 si non authentifié, 403 si non admin
    """
    # Phase 3: Clé statique pour demo
    # TODO: Remplacer par validation JWT
    ADMIN_KEY = "admin-dev-key-change-in-production"

    if not x_admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Admin-Key header. Admin access required.",
            headers={"WWW-Authenticate": "AdminKey"},
        )

    if x_admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key. Access denied.",
        )

    # Retourner info user (simulé)
    return {
        "email": "admin@example.com",
        "role": "admin",
        "user_id": "admin-user"
    }


def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, description="Tenant ID"),
    user: dict = None
) -> str:
    """
    Récupère le tenant_id de manière sécurisée.

    **Phase 3 - Header-based**:
    Utilise header X-Tenant-ID avec validation future depuis JWT.

    **TODO Production**:
    Extraire tenant_id depuis JWT claims pour éviter manipulation:
    - JWT claim "tenant_id" = source de vérité
    - Bloquer query params tenant_id (risque manipulation)
    - Validation que user a accès au tenant

    Args:
        x_tenant_id: Tenant ID dans header
        user: User info depuis JWT (future)

    Returns:
        str: Tenant ID validé
    """
    # Phase 3: Accepter header ou défaut
    # TODO: Extraire depuis JWT claims
    if x_tenant_id:
        return x_tenant_id

    # Défaut si non spécifié
    return "default"


__all__ = ["require_admin", "get_tenant_id"]
