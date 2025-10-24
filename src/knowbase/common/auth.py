"""
Authentication - Phase 0.5 P2.14

Protection endpoints sensibles (admin, canonicalization):
- API Key simple (header X-API-Key)
- JWT token (optionnel, pour auth avancée)
- Dependency FastAPI pour protection routes

Usage:
    from knowbase.common.auth import require_api_key

    @router.post("/admin/bootstrap", dependencies=[Depends(require_api_key)])
    async def bootstrap():
        # Endpoint protégé
        return result

Configuration (.env):
    API_KEY=your-secret-key-here  # Requis pour endpoints protégés
    JWT_SECRET=your-jwt-secret    # Optionnel pour JWT
    AUTH_ENABLED=true             # Activer auth (false en dev)
"""

import os
import logging
from typing import Optional
from fastapi import HTTPException, Header, status
from datetime import datetime, timedelta
import bcrypt

logger = logging.getLogger(__name__)

# Configuration
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
API_KEY = os.getenv("API_KEY", "dev-default-key")  # À changer en prod !
JWT_SECRET = os.getenv("JWT_SECRET", "jwt-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.getenv("JWT_EXPIRATION_MINUTES", "60"))


def require_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """
    Dependency FastAPI pour vérifier API Key

    Usage:
        @router.post("/admin/endpoint", dependencies=[Depends(require_api_key)])
        async def protected_endpoint():
            ...

    Args:
        x_api_key: Header X-API-Key

    Returns:
        API key validée

    Raises:
        HTTPException 401 si API key invalide ou manquante
    """
    if not AUTH_ENABLED:
        logger.debug("Auth disabled, allowing request")
        return "dev-mode"

    if not x_api_key:
        logger.warning("⚠️ Auth: API Key manquante")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key required (header X-API-Key)",
            headers={"WWW-Authenticate": "ApiKey"}
        )

    if x_api_key != API_KEY:
        logger.warning(f"⚠️ Auth: API Key invalide (reçue: {x_api_key[:10]}...)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "ApiKey"}
        )

    logger.debug("✅ Auth: API Key validée")
    return x_api_key


def create_jwt_token(user_id: str, metadata: Optional[dict] = None) -> str:
    """
    Créer JWT token (optionnel, pour auth avancée)

    Args:
        user_id: ID utilisateur
        metadata: Données additionnelles (tenant, roles, etc.)

    Returns:
        JWT token signé
    """
    try:
        import jwt
    except ImportError:
        logger.error("PyJWT not installed. Run: pip install pyjwt")
        raise HTTPException(
            status_code=500,
            detail="JWT not available (PyJWT not installed)"
        )

    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRATION_MINUTES),
        "iat": datetime.utcnow(),
        **(metadata or {})
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"🔑 JWT token créé pour user {user_id}")
    return token


def verify_jwt_token(token: str) -> dict:
    """
    Vérifier et décoder JWT token

    Args:
        token: JWT token

    Returns:
        Payload décodé

    Raises:
        HTTPException 401 si token invalide ou expiré
    """
    try:
        import jwt
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="JWT not available (PyJWT not installed)"
        )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logger.debug(f"✅ JWT token validé pour user {payload.get('user_id')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("⚠️ JWT token expiré")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"⚠️ JWT token invalide: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"}
        )


def require_jwt_token(authorization: Optional[str] = Header(None)) -> dict:
    """
    Dependency FastAPI pour vérifier JWT token

    Usage:
        @router.get("/user/profile")
        async def get_profile(token: dict = Depends(require_jwt_token)):
            user_id = token["user_id"]
            ...

    Args:
        authorization: Header Authorization (Bearer <token>)

    Returns:
        Payload JWT décodé

    Raises:
        HTTPException 401 si token invalide
    """
    if not AUTH_ENABLED:
        return {"user_id": "dev-user"}

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Format: "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format (expected: Bearer <token>)",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = parts[1]
    return verify_jwt_token(token)


def is_authenticated() -> bool:
    """Vérifier si auth activée"""
    return AUTH_ENABLED


def get_api_key() -> str:
    """Récupérer API key configurée (pour tests)"""
    return API_KEY


# ============================================================================
# PASSWORD HASHING (bcrypt)
# ============================================================================

def hash_password(password: str) -> str:
    """
    Hash un mot de passe avec bcrypt.

    Args:
        password: Mot de passe en clair

    Returns:
        Hash bcrypt (str)
    """
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Vérifie un mot de passe contre son hash bcrypt.

    Args:
        password: Mot de passe en clair
        password_hash: Hash bcrypt stocké en base

    Returns:
        True si le mot de passe correspond, False sinon
    """
    password_bytes = password.encode('utf-8')
    password_hash_bytes = password_hash.encode('utf-8')
    return bcrypt.checkpw(password_bytes, password_hash_bytes)
