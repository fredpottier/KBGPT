from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """Rôles utilisateur disponibles."""
    ADMIN = "admin"
    EXPERT = "expert"
    USER = "user"


class UserBase(BaseModel):
    """Schéma de base pour un utilisateur."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom de l'utilisateur")
    email: Optional[str] = Field(None, description="Email optionnel de l'utilisateur")
    role: UserRole = Field(default=UserRole.USER, description="Rôle de l'utilisateur")
    is_default: bool = Field(default=False, description="Indique si c'est l'utilisateur par défaut")


class UserCreate(UserBase):
    """Schéma pour la création d'un utilisateur."""
    pass


class UserUpdate(BaseModel):
    """Schéma pour la mise à jour d'un utilisateur."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_default: Optional[bool] = None

    # Extensions Knowledge Graph Phase 2
    graphiti_group_id: Optional[str] = Field(
        None,
        description="Identifiant groupe Graphiti (auto-généré: user_{user_id})"
    )
    kg_initialized: Optional[bool] = Field(
        None,
        description="Statut initialisation Knowledge Graph personnel"
    )
    kg_preferences: Optional[Dict[str, Any]] = Field(
        None,
        description="Préférences Knowledge Graph utilisateur"
    )
    kg_created_at: Optional[str] = Field(
        None,
        description="Date création Knowledge Graph personnel (ISO format)"
    )
    kg_stats: Optional[Dict[str, Any]] = Field(
        None,
        description="Statistiques Knowledge Graph personnel"
    )


class User(UserBase):
    """Schéma complet d'un utilisateur."""
    id: str = Field(..., description="Identifiant unique de l'utilisateur")
    created_at: datetime = Field(..., description="Date de création")
    last_active: datetime = Field(..., description="Dernière activité")

    # Extensions Knowledge Graph Phase 2 (optionnelles)
    graphiti_group_id: Optional[str] = Field(
        None,
        description="Identifiant groupe Graphiti personnel"
    )
    kg_initialized: Optional[bool] = Field(
        False,
        description="Statut initialisation Knowledge Graph personnel"
    )
    kg_preferences: Optional[Dict[str, Any]] = Field(
        None,
        description="Préférences Knowledge Graph utilisateur"
    )
    kg_created_at: Optional[str] = Field(
        None,
        description="Date création Knowledge Graph personnel"
    )
    kg_stats: Optional[Dict[str, Any]] = Field(
        None,
        description="Statistiques Knowledge Graph personnel"
    )

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Réponse pour la liste des utilisateurs."""
    users: list[User]
    total: int


__all__ = ["UserRole", "UserBase", "UserCreate", "UserUpdate", "User", "UserListResponse"]