"""
Endpoints d'authentification JWT.

Phase 0 - Security Hardening
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from knowbase.api.dependencies import get_current_user
from knowbase.api.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    CurrentUser,
)
from knowbase.api.services.auth_service import get_auth_service
from knowbase.db import get_db
from knowbase.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
) -> TokenResponse:
    """
    Authentifie un utilisateur et retourne des tokens JWT.

    Args:
        login_data: Email et mot de passe
        db: Session database

    Returns:
        Access token et refresh token JWT

    Raises:
        HTTPException 401: Si email ou mot de passe invalide
    """
    auth_service = get_auth_service()

    # Chercher utilisateur par email
    user = db.query(User).filter(User.email == login_data.email).first()

    if not user:
        logger.warning(f"⚠️ Tentative login avec email inexistant: {login_data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe invalide"
        )

    # Vérifier mot de passe
    if not auth_service.verify_password(login_data.password, user.password_hash):
        logger.warning(f"⚠️ Tentative login avec mot de passe invalide: {login_data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe invalide"
        )

    # Vérifier que l'utilisateur est actif
    if not user.is_active:
        logger.warning(f"⚠️ Tentative login utilisateur désactivé: {login_data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte désactivé. Contactez un administrateur."
        )

    # Générer tokens
    access_token = auth_service.generate_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id
    )

    refresh_token = auth_service.generate_refresh_token(
        user_id=user.id,
        email=user.email
    )

    # Mettre à jour last_login_at
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"✅ Login réussi: {user.email} (role: {user.role})")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600  # 1 heure en secondes
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    refresh_data: RefreshTokenRequest,
    db: Session = Depends(get_db)
) -> TokenResponse:
    """
    Génère un nouveau access token depuis un refresh token valide.

    Args:
        refresh_data: Refresh token
        db: Session database

    Returns:
        Nouveau access token et refresh token

    Raises:
        HTTPException 401: Si refresh token invalide
    """
    auth_service = get_auth_service()

    # Vérifier refresh token
    claims = auth_service.verify_refresh_token(refresh_data.refresh_token)

    user_id = claims.get("sub")
    email = claims.get("email")

    # Chercher utilisateur
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        logger.warning(f"⚠️ Refresh token pour utilisateur inexistant: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur non trouvé"
        )

    # Vérifier que l'utilisateur est actif
    if not user.is_active:
        logger.warning(f"⚠️ Refresh token pour utilisateur désactivé: {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte désactivé"
        )

    # Générer nouveaux tokens
    new_access_token = auth_service.generate_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id
    )

    new_refresh_token = auth_service.generate_refresh_token(
        user_id=user.id,
        email=user.email
    )

    logger.info(f"✅ Token refreshed pour: {user.email}")

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=3600
    )


@router.get("/me", response_model=CurrentUser)
def get_current_user_info(
    current_user: dict = Depends(get_current_user)
) -> CurrentUser:
    """
    Retourne les informations de l'utilisateur courant depuis le JWT.

    Args:
        current_user: Claims JWT

    Returns:
        Informations utilisateur
    """
    return CurrentUser(
        user_id=current_user["sub"],
        email=current_user["email"],
        role=current_user["role"],
        tenant_id=current_user["tenant_id"]
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
) -> UserResponse:
    """
    Crée un nouvel utilisateur (inscription).

    ⚠️ En production, cet endpoint devrait être protégé (admin only)
    ou désactivé selon la politique d'inscription.

    Args:
        user_data: Données utilisateur
        db: Session database

    Returns:
        Utilisateur créé

    Raises:
        HTTPException 400: Si email déjà utilisé
    """
    auth_service = get_auth_service()

    # Vérifier email unique
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Email déjà utilisé: {user_data.email}"
        )

    # Hash password
    password_hash = auth_service.hash_password(user_data.password)

    # Créer utilisateur
    new_user = User(
        email=user_data.email,
        password_hash=password_hash,
        full_name=user_data.full_name,
        role=user_data.role.value,
        tenant_id=user_data.tenant_id,
        is_active=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    logger.info(f"✅ Nouvel utilisateur créé: {new_user.email} (role: {new_user.role})")

    return UserResponse.model_validate(new_user)
