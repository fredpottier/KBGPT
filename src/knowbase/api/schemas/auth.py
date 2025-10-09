"""
Schemas Pydantic pour authentification.

Phase 0 - Security Hardening
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRole(str, Enum):
    """Rôles utilisateurs (RBAC)."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class LoginRequest(BaseModel):
    """Request body pour login."""

    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., min_length=8, description="Mot de passe")


class RefreshTokenRequest(BaseModel):
    """Request body pour refresh token."""

    refresh_token: str = Field(..., description="Refresh token JWT")


class TokenResponse(BaseModel):
    """Response avec tokens JWT."""

    access_token: str = Field(..., description="Access token JWT (1h)")
    refresh_token: str = Field(..., description="Refresh token JWT (7 jours)")
    token_type: str = Field(default="bearer", description="Type de token")
    expires_in: int = Field(..., description="Durée validité access token (secondes)")


class UserCreate(BaseModel):
    """Request body pour créer un utilisateur."""

    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., min_length=8, description="Mot de passe (min 8 caractères)")
    full_name: Optional[str] = Field(None, max_length=100, description="Nom complet")
    role: UserRole = Field(default=UserRole.VIEWER, description="Rôle (default: viewer)")
    tenant_id: str = Field(..., max_length=50, description="Tenant ID")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Valide la force du mot de passe."""
        if len(v) < 8:
            raise ValueError("Mot de passe doit faire au moins 8 caractères")

        # Vérifier au moins une lettre et un chiffre
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)

        if not (has_letter and has_digit):
            raise ValueError("Mot de passe doit contenir au moins une lettre et un chiffre")

        return v


class UserUpdate(BaseModel):
    """Request body pour modifier un utilisateur."""

    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """Response avec infos utilisateur (sans password_hash)."""

    id: str = Field(..., description="UUID de l'utilisateur")
    email: EmailStr = Field(..., description="Email")
    full_name: Optional[str] = Field(None, description="Nom complet")
    role: UserRole = Field(..., description="Rôle")
    tenant_id: str = Field(..., description="Tenant ID")
    is_active: bool = Field(..., description="Utilisateur actif ou désactivé")
    created_at: datetime = Field(..., description="Date création")
    updated_at: datetime = Field(..., description="Date dernière modification")
    last_login_at: Optional[datetime] = Field(None, description="Date dernière connexion")

    model_config = {
        "from_attributes": True  # Pour conversion depuis SQLAlchemy model
    }


class CurrentUser(BaseModel):
    """Utilisateur courant extrait du JWT token."""

    user_id: str = Field(..., description="UUID de l'utilisateur")
    email: EmailStr = Field(..., description="Email")
    role: UserRole = Field(..., description="Rôle")
    tenant_id: str = Field(..., description="Tenant ID")


class AuditLogCreate(BaseModel):
    """Request body pour créer une entrée audit log."""

    user_id: str = Field(..., description="UUID de l'utilisateur")
    user_email: EmailStr = Field(..., description="Email de l'utilisateur")
    action: str = Field(..., max_length=50, description="Action (CREATE, UPDATE, DELETE, etc.)")
    resource_type: str = Field(..., max_length=50, description="Type de ressource")
    resource_id: Optional[str] = Field(None, max_length=255, description="ID de la ressource")
    tenant_id: str = Field(..., max_length=50, description="Tenant ID")
    details: Optional[dict] = Field(None, description="Détails additionnels (JSON)")


class AuditLogResponse(BaseModel):
    """Response avec infos audit log."""

    id: str = Field(..., description="UUID de l'entrée audit")
    user_id: Optional[str] = Field(None, description="UUID de l'utilisateur")
    user_email: str = Field(..., description="Email de l'utilisateur")
    action: str = Field(..., description="Action effectuée")
    resource_type: str = Field(..., description="Type de ressource")
    resource_id: Optional[str] = Field(None, description="ID de la ressource")
    tenant_id: str = Field(..., description="Tenant ID")
    details: Optional[dict] = Field(None, description="Détails (JSON)")
    timestamp: datetime = Field(..., description="Date/heure de l'action")

    model_config = {
        "from_attributes": True
    }
