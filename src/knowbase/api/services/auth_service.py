"""
Service d'authentification JWT RS256.

Phase 0 - Security Hardening
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

import jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Context pour hashing passwords (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configuration JWT
# TODO: Charger depuis variables d'environnement
JWT_ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 heure
REFRESH_TOKEN_EXPIRE_DAYS = 1  # 24 heures (réduit de 7j pour sécurité)


class AuthService:
    """
    Service d'authentification avec JWT RS256.

    Gère la génération et validation de tokens JWT,
    ainsi que le hashing de mots de passe.
    """

    def __init__(self):
        """Initialise le service auth avec les clés RSA."""
        self.private_key = self._load_private_key()
        self.public_key = self._load_public_key()

    def _load_private_key(self) -> str:
        """
        Charge la clé privée RSA depuis fichier ou variable d'environnement.

        Returns:
            Clé privée RSA au format PEM

        Raises:
            FileNotFoundError: Si clé privée non trouvée
        """
        # Essayer depuis variable d'environnement
        private_key_env = os.getenv("JWT_PRIVATE_KEY")
        if private_key_env:
            logger.info("✅ Clé privée JWT chargée depuis variable d'environnement")
            return private_key_env

        # Sinon, essayer depuis fichier
        private_key_path = os.getenv("JWT_PRIVATE_KEY_PATH", "config/keys/jwt_private.pem")

        try:
            with open(private_key_path, "r") as f:
                private_key = f.read()
            logger.info(f"✅ Clé privée JWT chargée depuis {private_key_path}")
            return private_key
        except FileNotFoundError:
            logger.error(f"❌ Clé privée JWT non trouvée à {private_key_path}")
            logger.error("💡 Génère les clés avec: openssl genrsa -out jwt_private.pem 2048")
            raise FileNotFoundError(
                f"Clé privée JWT non trouvée. "
                f"Génère les clés avec: openssl genrsa -out {private_key_path} 2048"
            )

    def _load_public_key(self) -> str:
        """
        Charge la clé publique RSA depuis fichier ou variable d'environnement.

        Returns:
            Clé publique RSA au format PEM

        Raises:
            FileNotFoundError: Si clé publique non trouvée
        """
        # Essayer depuis variable d'environnement
        public_key_env = os.getenv("JWT_PUBLIC_KEY")
        if public_key_env:
            logger.info("✅ Clé publique JWT chargée depuis variable d'environnement")
            return public_key_env

        # Sinon, essayer depuis fichier
        public_key_path = os.getenv("JWT_PUBLIC_KEY_PATH", "config/keys/jwt_public.pem")

        try:
            with open(public_key_path, "r") as f:
                public_key = f.read()
            logger.info(f"✅ Clé publique JWT chargée depuis {public_key_path}")
            return public_key
        except FileNotFoundError:
            logger.error(f"❌ Clé publique JWT non trouvée à {public_key_path}")
            logger.error("💡 Extrait la clé publique avec: openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem")
            raise FileNotFoundError(
                f"Clé publique JWT non trouvée. "
                f"Extrait la clé publique avec: openssl rsa -in jwt_private.pem -pubout -out {public_key_path}"
            )

    def hash_password(self, password: str) -> str:
        """
        Hash un mot de passe avec bcrypt.

        Args:
            password: Mot de passe en clair

        Returns:
            Hash bcrypt du mot de passe
        """
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Vérifie qu'un mot de passe correspond au hash.

        Args:
            plain_password: Mot de passe en clair
            hashed_password: Hash bcrypt à comparer

        Returns:
            True si le mot de passe correspond
        """
        return pwd_context.verify(plain_password, hashed_password)

    def generate_access_token(
        self,
        user_id: str,
        email: str,
        role: str,
        tenant_id: str,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Génère un access token JWT.

        Args:
            user_id: UUID de l'utilisateur
            email: Email de l'utilisateur
            role: Rôle (admin, editor, viewer)
            tenant_id: Tenant ID
            expires_delta: Durée de validité custom (default: 1h)

        Returns:
            Token JWT signé
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        expire = datetime.now(timezone.utc) + expires_delta

        # Claims JWT
        claims = {
            "sub": user_id,  # Subject (user_id)
            "email": email,
            "role": role,
            "tenant_id": tenant_id,
            "type": "access",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }

        # Signer avec clé privée
        token = jwt.encode(claims, self.private_key, algorithm=JWT_ALGORITHM)

        logger.info(f"🔑 Access token généré pour {email} (expire: {expire})")
        return token

    def generate_refresh_token(
        self,
        user_id: str,
        email: str,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Génère un refresh token JWT.

        Args:
            user_id: UUID de l'utilisateur
            email: Email de l'utilisateur
            expires_delta: Durée de validité custom (default: 7 jours)

        Returns:
            Refresh token JWT signé
        """
        if expires_delta is None:
            expires_delta = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        expire = datetime.now(timezone.utc) + expires_delta

        # Claims JWT (refresh token a moins de claims)
        claims = {
            "sub": user_id,
            "email": email,
            "type": "refresh",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }

        # Signer avec clé privée
        token = jwt.encode(claims, self.private_key, algorithm=JWT_ALGORITHM)

        logger.info(f"🔄 Refresh token généré pour {email} (expire: {expire})")
        return token

    def verify_token(self, token: str) -> dict:
        """
        Vérifie et décode un token JWT.

        Args:
            token: Token JWT à vérifier

        Returns:
            Claims décodés

        Raises:
            HTTPException: Si token invalide ou expiré
        """
        try:
            # Décoder et vérifier avec clé publique
            claims = jwt.decode(
                token,
                self.public_key,
                algorithms=[JWT_ALGORITHM]
            )

            logger.debug(f"✅ Token vérifié pour {claims.get('email')}")
            return claims

        except jwt.ExpiredSignatureError:
            logger.warning("⚠️ Token expiré")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expiré",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"⚠️ Token invalide: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def verify_access_token(self, token: str) -> dict:
        """
        Vérifie qu'un token est un access token valide.

        Args:
            token: Token JWT à vérifier

        Returns:
            Claims décodés

        Raises:
            HTTPException: Si pas un access token ou invalide
        """
        claims = self.verify_token(token)

        if claims.get("type") != "access":
            logger.warning("⚠️ Token n'est pas un access token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide (type incorrect)",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return claims

    def verify_refresh_token(self, token: str) -> dict:
        """
        Vérifie qu'un token est un refresh token valide.

        Args:
            token: Token JWT à vérifier

        Returns:
            Claims décodés

        Raises:
            HTTPException: Si pas un refresh token ou invalide
        """
        claims = self.verify_token(token)

        if claims.get("type") != "refresh":
            logger.warning("⚠️ Token n'est pas un refresh token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide (type incorrect)",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return claims


# Singleton global
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """
    Récupère l'instance singleton du service auth.

    Returns:
        Instance AuthService
    """
    global _auth_service

    if _auth_service is None:
        _auth_service = AuthService()

    return _auth_service
