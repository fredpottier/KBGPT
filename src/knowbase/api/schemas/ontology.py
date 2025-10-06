"""
Schémas Pydantic pour gestion catalogues d'ontologies.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from knowbase.common.entity_types import EntityType


class EntityCatalogEntry(BaseModel):
    """Entrée catalogue pour une entité."""

    entity_id: str = Field(
        ...,
        description="Identifiant unique stable (ex: LOAD_BALANCER)"
    )
    canonical_name: str = Field(
        ...,
        description="Nom canonique officiel"
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="Liste des alias/variantes"
    )
    category: Optional[str] = Field(
        default=None,
        description="Catégorie (ex: Infrastructure, ERP, etc.)"
    )
    vendor: Optional[str] = Field(
        default=None,
        description="Éditeur/fournisseur (ex: SAP, Microsoft)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )


class EntityCatalogCreate(BaseModel):
    """Schéma création entité catalogue."""

    entity_type: EntityType = Field(
        ...,
        description="Type d'entité"
    )
    entity_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifiant unique (SNAKE_CASE_MAJUSCULES)"
    )
    canonical_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nom canonique officiel"
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="Liste des alias"
    )
    category: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Catégorie"
    )
    vendor: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Éditeur/fournisseur"
    )


class EntityCatalogUpdate(BaseModel):
    """Schéma mise à jour entité catalogue."""

    canonical_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200
    )
    aliases: Optional[List[str]] = Field(
        default=None,
        description="Remplace tous les aliases"
    )
    category: Optional[str] = Field(
        default=None,
        max_length=100
    )
    vendor: Optional[str] = Field(
        default=None,
        max_length=100
    )


class EntityCatalogResponse(BaseModel):
    """Schéma réponse entité catalogue."""

    entity_type: EntityType
    entity_id: str
    canonical_name: str
    aliases: List[str]
    category: Optional[str] = None
    vendor: Optional[str] = None
    usage_count: int = Field(
        default=0,
        description="Nombre d'occurrences dans Neo4j"
    )


class CatalogStatistics(BaseModel):
    """Statistiques catalogue d'ontologies."""

    entity_type: EntityType
    total_entities: int = Field(
        ...,
        description="Nombre total d'entités cataloguées"
    )
    total_aliases: int = Field(
        ...,
        description="Nombre total d'aliases"
    )
    categories: Dict[str, int] = Field(
        default_factory=dict,
        description="Répartition par catégorie"
    )
    vendors: Dict[str, int] = Field(
        default_factory=dict,
        description="Répartition par vendor"
    )


class UncatalogedEntity(BaseModel):
    """Entité non cataloguée détectée lors de l'ingestion."""

    raw_name: str = Field(
        ...,
        description="Nom brut extrait par LLM"
    )
    entity_type: EntityType = Field(
        ...,
        description="Type d'entité"
    )
    occurrences: int = Field(
        default=1,
        description="Nombre d'occurrences"
    )
    first_seen: str = Field(
        ...,
        description="Date première détection (ISO format)"
    )
    last_seen: str = Field(
        ...,
        description="Date dernière détection (ISO format)"
    )
    tenants: List[str] = Field(
        default_factory=list,
        description="Liste des tenants concernés"
    )
    suggested_entity_id: Optional[str] = Field(
        default=None,
        description="Suggestion d'entity_id (auto-généré)"
    )


class UncatalogedEntityApprove(BaseModel):
    """Schéma approbation entité non cataloguée."""

    entity_id: str = Field(
        ...,
        description="Entity ID à créer"
    )
    canonical_name: str = Field(
        ...,
        description="Nom canonique"
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="Aliases additionnels (raw_name ajouté auto)"
    )
    category: Optional[str] = None
    vendor: Optional[str] = None


class CatalogBulkImport(BaseModel):
    """Import en masse d'entités catalogue."""

    entity_type: EntityType
    entities: List[EntityCatalogCreate] = Field(
        ...,
        description="Liste d'entités à importer"
    )
    overwrite_existing: bool = Field(
        default=False,
        description="Écraser entités existantes si conflit"
    )


class CatalogBulkImportResult(BaseModel):
    """Résultat import en masse."""

    entity_type: EntityType
    total_processed: int
    created: int
    updated: int
    skipped: int
    errors: List[str] = Field(
        default_factory=list,
        description="Messages d'erreur"
    )


__all__ = [
    "EntityCatalogEntry",
    "EntityCatalogCreate",
    "EntityCatalogUpdate",
    "EntityCatalogResponse",
    "CatalogStatistics",
    "UncatalogedEntity",
    "UncatalogedEntityApprove",
    "CatalogBulkImport",
    "CatalogBulkImportResult",
]
