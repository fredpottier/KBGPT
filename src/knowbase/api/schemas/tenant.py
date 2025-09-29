"""
Schémas Pydantic pour les tenants/groupes multi-tenant
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field


class TenantType(str, Enum):
    """Types de tenant disponibles."""
    ENTERPRISE = "enterprise"  # Tenant entreprise (isolation totale)
    DEPARTMENT = "department"  # Département d'une entreprise
    PROJECT = "project"       # Projet spécifique
    PERSONAL = "personal"     # Tenant personnel utilisateur


class TenantStatus(str, Enum):
    """Statuts de tenant."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class GraphitiSettings(BaseModel):
    """Configuration Graphiti pour un tenant."""
    enable_memory: bool = Field(default=True, description="Activer la mémoire conversationnelle")
    enable_facts: bool = Field(default=True, description="Activer les faits structurés")
    enable_relations: bool = Field(default=True, description="Activer les relations entre entités")
    max_memory_episodes: int = Field(default=100, ge=1, le=1000, description="Nombre max d'épisodes en mémoire")
    fact_approval_required: bool = Field(default=False, description="Approbation requise pour les faits")
    auto_extract_entities: bool = Field(default=True, description="Extraction automatique d'entités")


class TenantBase(BaseModel):
    """Schéma de base pour un tenant."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom du tenant")
    display_name: Optional[str] = Field(None, max_length=200, description="Nom d'affichage")
    description: Optional[str] = Field(None, max_length=500, description="Description du tenant")
    tenant_type: TenantType = Field(default=TenantType.PROJECT, description="Type de tenant")
    parent_tenant_id: Optional[str] = Field(None, description="ID du tenant parent (hiérarchie)")

    # Configuration Graphiti
    graphiti_settings: GraphitiSettings = Field(default_factory=GraphitiSettings, description="Configuration Graphiti")

    # Métadonnées libres
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées additionnelles")


class TenantCreate(TenantBase):
    """Schéma pour la création d'un tenant."""
    pass


class TenantUpdate(BaseModel):
    """Schéma pour la mise à jour d'un tenant."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    tenant_type: Optional[TenantType] = None
    parent_tenant_id: Optional[str] = None
    status: Optional[TenantStatus] = None
    graphiti_settings: Optional[GraphitiSettings] = None
    metadata: Optional[Dict[str, Any]] = None


class TenantStats(BaseModel):
    """Statistiques d'un tenant."""
    users_count: int = Field(default=0, description="Nombre d'utilisateurs")
    episodes_count: int = Field(default=0, description="Nombre d'épisodes Graphiti")
    facts_count: int = Field(default=0, description="Nombre de faits")
    relations_count: int = Field(default=0, description="Nombre de relations")
    documents_count: int = Field(default=0, description="Nombre de documents traités")
    last_activity: Optional[datetime] = Field(None, description="Dernière activité")
    storage_size_mb: float = Field(default=0.0, description="Taille de stockage en MB")


class Tenant(TenantBase):
    """Schéma complet d'un tenant."""
    id: str = Field(..., description="Identifiant unique du tenant")
    status: TenantStatus = Field(default=TenantStatus.ACTIVE, description="Statut du tenant")
    created_at: datetime = Field(..., description="Date de création")
    updated_at: datetime = Field(..., description="Dernière modification")
    created_by: str = Field(..., description="ID de l'utilisateur créateur")

    # Statistiques (calculées)
    stats: TenantStats = Field(default_factory=TenantStats, description="Statistiques du tenant")

    class Config:
        from_attributes = True


class TenantListResponse(BaseModel):
    """Réponse pour la liste des tenants."""
    tenants: List[Tenant]
    total: int
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class UserTenantMembership(BaseModel):
    """Association utilisateur-tenant."""
    user_id: str = Field(..., description="ID de l'utilisateur")
    tenant_id: str = Field(..., description="ID du tenant")
    role: str = Field(default="member", description="Rôle dans le tenant")
    permissions: List[str] = Field(default_factory=list, description="Permissions spécifiques")
    joined_at: datetime = Field(..., description="Date d'adhésion")
    is_default: bool = Field(default=False, description="Tenant par défaut pour cet utilisateur")


class TenantHierarchy(BaseModel):
    """Hiérarchie des tenants."""
    tenant: Tenant
    children: List['TenantHierarchy'] = Field(default_factory=list, description="Tenants enfants")
    path: List[str] = Field(default_factory=list, description="Chemin hiérarchique")
    depth: int = Field(default=0, ge=0, description="Profondeur dans la hiérarchie")


# Mise à jour pour les références circulaires
TenantHierarchy.model_rebuild()


class GraphitiTenantInfo(BaseModel):
    """Informations Graphiti pour un tenant."""
    tenant_id: str = Field(..., description="ID du tenant")
    graphiti_group_id: str = Field(..., description="ID du groupe Graphiti")
    connection_status: str = Field(default="unknown", description="Statut de connexion")
    last_sync: Optional[datetime] = Field(None, description="Dernière synchronisation")

    # Statistiques Graphiti
    memory_episodes: int = Field(default=0, description="Épisodes en mémoire")
    approved_facts: int = Field(default=0, description="Faits approuvés")
    pending_facts: int = Field(default=0, description="Faits en attente")
    extracted_entities: int = Field(default=0, description="Entités extraites")


class TenantPermission(str, Enum):
    """Permissions disponibles dans un tenant."""
    # Lecture
    READ_DOCUMENTS = "read_documents"
    READ_FACTS = "read_facts"
    READ_MEMORY = "read_memory"
    READ_STATS = "read_stats"

    # Écriture
    WRITE_DOCUMENTS = "write_documents"
    WRITE_FACTS = "write_facts"
    WRITE_MEMORY = "write_memory"

    # Administration
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    DELETE_DATA = "delete_data"

    # Super admin
    ADMIN = "admin"


__all__ = [
    "TenantType",
    "TenantStatus",
    "GraphitiSettings",
    "TenantBase",
    "TenantCreate",
    "TenantUpdate",
    "TenantStats",
    "Tenant",
    "TenantListResponse",
    "UserTenantMembership",
    "TenantHierarchy",
    "GraphitiTenantInfo",
    "TenantPermission"
]