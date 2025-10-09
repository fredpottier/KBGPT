"""
Schémas Pydantic pour Entity Types Registry API.

Phase 2 - Entity Types Management
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, computed_field


# Regex validation pour type_name (sécurité Phase 1)
TYPE_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{0,49}$')
FORBIDDEN_TYPE_PREFIXES = ['_', 'SYSTEM_', 'ADMIN_', 'INTERNAL_']


class EntityTypeBase(BaseModel):
    """Base schema pour entity type."""

    type_name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Nom type (UPPERCASE, ex: INFRASTRUCTURE)"
    )
    description: Optional[str] = Field(
        default=None,
        description="Description du type (optionnel)"
    )

    @field_validator("type_name")
    @classmethod
    def validate_type_name(cls, v: str) -> str:
        """Valide et normalise le nom de type (sécurité)."""
        v = v.strip().upper()

        if not TYPE_PATTERN.match(v):
            raise ValueError(
                "type_name must be UPPERCASE, start with a letter, "
                "and contain only letters, numbers, and underscores"
            )

        if any(v.startswith(prefix) for prefix in FORBIDDEN_TYPE_PREFIXES):
            raise ValueError(
                "type_name cannot start with reserved prefixes: "
                f"{', '.join(FORBIDDEN_TYPE_PREFIXES)}"
            )

        return v


class EntityTypeCreate(EntityTypeBase):
    """Schema création entity type (admin)."""

    tenant_id: str = Field(
        default="default",
        description="Tenant ID"
    )
    discovered_by: str = Field(
        default="admin",
        description="Source découverte (llm | admin | system)"
    )


class EntityTypeResponse(EntityTypeBase):
    """Schema réponse entity type."""

    id: int = Field(..., description="ID unique dans registry")
    status: str = Field(..., description="pending | approved | rejected")

    # Metadata découverte
    first_seen: datetime = Field(..., description="Date première découverte")
    discovered_by: str = Field(..., description="Source découverte")

    # Compteurs
    entity_count: int = Field(..., description="Nombre total entités ce type")
    pending_entity_count: int = Field(..., description="Nombre entités pending")

    # Validation
    approved_by: Optional[str] = Field(None, description="Email admin approbation")
    approved_at: Optional[datetime] = Field(None, description="Date approbation")
    rejected_by: Optional[str] = Field(None, description="Email admin rejet")
    rejected_at: Optional[datetime] = Field(None, description="Date rejet")
    rejection_reason: Optional[str] = Field(None, description="Raison rejet")

    # Normalisation workflow (Phase 5B)
    normalization_status: Optional[str] = Field(None, description="Statut normalisation (generating | pending_review | None)")
    normalization_job_id: Optional[str] = Field(None, description="Job ID génération ontologie")
    normalization_started_at: Optional[datetime] = Field(None, description="Date lancement normalisation")

    # Multi-tenancy
    tenant_id: str = Field(..., description="Tenant ID")

    # Timestamps
    created_at: datetime = Field(..., description="Date création record")
    updated_at: datetime = Field(..., description="Date dernière modification")

    @computed_field  # type: ignore[misc]
    @property
    def validated_entity_count(self) -> int:
        """Nombre d'entités validées (calculé)."""
        return max(0, self.entity_count - self.pending_entity_count)

    class Config:
        from_attributes = True  # Pydantic v2 (ex orm_mode)


class EntityTypeApprove(BaseModel):
    """Schema approbation entity type."""

    admin_email: str = Field(
        ...,
        description="Email admin qui approuve"
    )


class EntityTypeReject(BaseModel):
    """Schema rejet entity type."""

    admin_email: str = Field(
        ...,
        description="Email admin qui rejette"
    )
    reason: Optional[str] = Field(
        default=None,
        description="Raison rejet (optionnel)"
    )


class EntityTypeListResponse(BaseModel):
    """Schema liste entity types."""

    types: list[EntityTypeResponse] = Field(
        ...,
        description="Liste types"
    )
    total: int = Field(
        ...,
        description="Nombre total types (sans pagination)"
    )
    status_filter: Optional[str] = Field(
        default=None,
        description="Filtre status appliqué"
    )


__all__ = [
    "EntityTypeBase",
    "EntityTypeCreate",
    "EntityTypeResponse",
    "EntityTypeApprove",
    "EntityTypeReject",
    "EntityTypeListResponse",
]
