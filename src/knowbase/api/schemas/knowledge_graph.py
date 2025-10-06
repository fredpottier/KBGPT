"""
Schémas Pydantic pour Knowledge Graph (Entities, Relations, Episodes).

Phase 3 - Knowledge Graph Neo4j Native
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from knowbase.common.entity_types import EntityType, RelationType

# Validation stricte types pour sécurité (éviter injection/pollution)
# Pattern: UPPERCASE, alphanumeric + underscore, 1-50 chars
TYPE_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{0,49}$')
FORBIDDEN_TYPE_PREFIXES = ['_', 'SYSTEM_', 'ADMIN_', 'INTERNAL_']

# Statuts validation entités
ENTITY_STATUS_PENDING = "pending"
ENTITY_STATUS_VALIDATED = "validated"
ENTITY_STATUS_REJECTED = "rejected"
VALID_ENTITY_STATUSES = {ENTITY_STATUS_PENDING, ENTITY_STATUS_VALIDATED, ENTITY_STATUS_REJECTED}


class EntityCreate(BaseModel):
    """Schéma création entité Knowledge Graph."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom de l'entité (canonique si solution SAP)"
    )
    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type d'entité (UPPERCASE alphanumérique, ex: SOLUTION, INFRASTRUCTURE)"
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Description de l'entité (contexte slide)"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confiance extraction (0.0-1.0)"
    )
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Attributs additionnels (version, vendor, category, etc.)"
    )

    # Métadonnées traçabilité
    source_slide_number: Optional[int] = Field(
        default=None,
        description="Numéro slide source"
    )
    source_document: Optional[str] = Field(
        default=None,
        description="Document source"
    )
    source_chunk_id: Optional[str] = Field(
        default=None,
        description="ID chunk Qdrant associé"
    )
    tenant_id: str = Field(
        default="default",
        description="Tenant ID (multi-tenancy)"
    )

    # Champs gestion validation entités (Phase 1)
    status: str = Field(
        default="pending",
        description="Statut validation (pending|validated|rejected)"
    )
    is_cataloged: bool = Field(
        default=False,
        description="True si entité trouvée dans catalogue ontologie YAML"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Valide et normalise le nom de l'entité."""
        # Trim whitespace
        v = v.strip()
        if not v:
            raise ValueError("Entity name cannot be empty")

        # Sécurité : Interdire caractères dangereux (XSS, injection)
        forbidden_chars = ['<', '>', '"', "'", '`', '\0', '\n', '\r', '\t']
        if any(char in v for char in forbidden_chars):
            raise ValueError(
                f"Entity name contains forbidden characters: {forbidden_chars}"
            )

        # Sécurité : Interdire path traversal
        if '..' in v or v.startswith('/') or '\\' in v:
            raise ValueError("Entity name cannot contain path traversal patterns")

        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Valide que status est dans les valeurs autorisées."""
        if v not in VALID_ENTITY_STATUSES:
            raise ValueError(
                f"status must be one of {VALID_ENTITY_STATUSES}, got '{v}'"
            )
        return v

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        """Valide format entity_type (sécurité injection/pollution)."""
        v = v.strip().upper()  # Normaliser en UPPERCASE

        # Vérifier pattern UPPERCASE alphanumérique + underscore
        if not TYPE_PATTERN.match(v):
            raise ValueError(
                "entity_type must be UPPERCASE alphanumeric + underscore "
                "(1-50 chars, ex: SOLUTION, INFRASTRUCTURE, LOAD_BALANCER)"
            )

        # Blacklist préfixes système
        if any(v.startswith(prefix) for prefix in FORBIDDEN_TYPE_PREFIXES):
            raise ValueError(
                f"entity_type cannot start with reserved prefixes: {FORBIDDEN_TYPE_PREFIXES}"
            )

        return v


class EntityResponse(EntityCreate):
    """Schéma réponse entité (avec UUID)."""

    uuid: str = Field(
        ...,
        description="UUID unique de l'entité dans Neo4j"
    )
    canonical_name: Optional[str] = Field(
        default=None,
        description="Nom canonique après normalisation"
    )
    created_at: datetime = Field(
        ...,
        description="Date création"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Date dernière modification"
    )


class RelationCreate(BaseModel):
    """Schéma création relation Knowledge Graph."""

    source: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom entité source (doit exister dans entities)"
    )
    target: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom entité cible (doit exister dans entities)"
    )
    relation_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type de relation (UPPERCASE alphanumérique, ex: USES, INTEGRATES_WITH)"
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=300,
        description="Description de la relation"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confiance extraction (0.0-1.0)"
    )

    # Métadonnées traçabilité
    source_slide_number: Optional[int] = Field(
        default=None,
        description="Numéro slide source"
    )
    source_document: Optional[str] = Field(
        default=None,
        description="Document source"
    )
    source_chunk_id: Optional[str] = Field(
        default=None,
        description="ID chunk Qdrant associé"
    )
    tenant_id: str = Field(
        default="default",
        description="Tenant ID (multi-tenancy)"
    )

    @field_validator("source", "target")
    @classmethod
    def validate_entity_name(cls, v: str) -> str:
        """Valide les noms d'entités."""
        v = v.strip()
        if not v:
            raise ValueError("Entity name cannot be empty")

        # Sécurité : Interdire caractères dangereux
        forbidden_chars = ['<', '>', '"', "'", '`', '\0', '\n', '\r', '\t']
        if any(char in v for char in forbidden_chars):
            raise ValueError(
                f"Entity name contains forbidden characters: {forbidden_chars}"
            )

        return v

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """Valide format relation_type (sécurité injection/pollution)."""
        v = v.strip().upper()  # Normaliser en UPPERCASE

        # Vérifier pattern UPPERCASE alphanumérique + underscore
        if not TYPE_PATTERN.match(v):
            raise ValueError(
                "relation_type must be UPPERCASE alphanumeric + underscore "
                "(1-50 chars, ex: USES, INTEGRATES_WITH, PART_OF)"
            )

        # Blacklist préfixes système
        if any(v.startswith(prefix) for prefix in FORBIDDEN_TYPE_PREFIXES):
            raise ValueError(
                f"relation_type cannot start with reserved prefixes: {FORBIDDEN_TYPE_PREFIXES}"
            )

        return v


class RelationResponse(RelationCreate):
    """Schéma réponse relation (avec UUID)."""

    uuid: str = Field(
        ...,
        description="UUID unique de la relation dans Neo4j"
    )
    source_uuid: str = Field(
        ...,
        description="UUID entité source"
    )
    target_uuid: str = Field(
        ...,
        description="UUID entité cible"
    )
    created_at: datetime = Field(
        ...,
        description="Date création"
    )


class EpisodeCreate(BaseModel):
    """Schéma création épisode (unité de connaissance liée à un document/slide)."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom épisode (ex: 'proposal_2024_slide_5')"
    )
    source_document: str = Field(
        ...,
        description="Document source (ex: 'proposal_2024.pptx')"
    )
    source_type: str = Field(
        default="pptx",
        description="Type de source (pptx, pdf, etc.)"
    )
    content_summary: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Résumé du contenu de l'épisode"
    )

    # Liaisons Qdrant
    chunk_ids: List[str] = Field(
        default_factory=list,
        description="Liste des chunk IDs Qdrant liés à cet épisode"
    )

    # Liaisons Neo4j KG
    entity_uuids: List[str] = Field(
        default_factory=list,
        description="Liste des UUIDs entités extraites dans cet épisode"
    )
    relation_uuids: List[str] = Field(
        default_factory=list,
        description="Liste des UUIDs relations extraites dans cet épisode"
    )
    fact_uuids: List[str] = Field(
        default_factory=list,
        description="Liste des UUIDs facts extraits dans cet épisode"
    )

    # Métadonnées
    slide_number: Optional[int] = Field(
        default=None,
        description="Numéro slide (si épisode = slide)"
    )
    tenant_id: str = Field(
        default="default",
        description="Tenant ID (multi-tenancy)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )


class EpisodeResponse(EpisodeCreate):
    """Schéma réponse épisode (avec UUID)."""

    uuid: str = Field(
        ...,
        description="UUID unique de l'épisode dans Neo4j"
    )
    created_at: datetime = Field(
        ...,
        description="Date création"
    )


__all__ = [
    "EntityType",
    "RelationType",
    "EntityCreate",
    "EntityResponse",
    "RelationCreate",
    "RelationResponse",
    "EpisodeCreate",
    "EpisodeResponse",
]
