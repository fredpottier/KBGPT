"""
Schemas Pydantic pour Document Backbone - Phase 1.

Gère les documents et leurs versions avec metadata, lineage et provenance.
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    """Statut lifecycle document."""
    DRAFT = "draft"
    ACTIVE = "active"
    OBSOLETE = "obsolete"
    ARCHIVED = "archived"


class DocumentType(str, Enum):
    """Types de documents supportés."""
    PDF = "pdf"
    PPTX = "pptx"
    DOCX = "docx"
    EXCEL = "excel"
    UNKNOWN = "unknown"


# === Document ===

class DocumentBase(BaseModel):
    """Base document (champs communs)."""
    title: str = Field(..., min_length=1, max_length=500, description="Titre du document")
    source_path: str = Field(..., description="Chemin source unique (ex: /data/docs_in/budget_2024.pdf)")
    document_type: DocumentType = Field(default=DocumentType.UNKNOWN, description="Type de document")
    tenant_id: str = Field(default="default", description="ID tenant pour isolation multi-tenant")


class DocumentCreate(DocumentBase):
    """Création nouveau document."""
    description: Optional[str] = Field(None, max_length=2000, description="Description optionnelle")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata custom")


class DocumentUpdate(BaseModel):
    """Mise à jour document (champs optionnels)."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[DocumentStatus] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentResponse(DocumentBase):
    """Response document complète."""
    document_id: str = Field(..., description="UUID unique du document")
    description: Optional[str] = None
    status: DocumentStatus = Field(default=DocumentStatus.ACTIVE)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    # Relations
    latest_version_id: Optional[str] = Field(None, description="ID de la dernière version")
    version_count: int = Field(default=0, description="Nombre total de versions")

    class Config:
        from_attributes = True


# === DocumentVersion ===

class DocumentVersionBase(BaseModel):
    """Base version document."""
    version_label: str = Field(..., description="Label version (ex: v1.0, v2.1, draft-2024-01)")
    effective_date: datetime = Field(..., description="Date effective de cette version")


class DocumentVersionCreate(DocumentVersionBase):
    """Création nouvelle version."""
    document_id: str = Field(..., description="ID du document parent")
    checksum: str = Field(..., description="SHA256 checksum du contenu (anti-duplicatas)")

    # Metadata extraction
    file_size: Optional[int] = Field(None, description="Taille fichier en bytes")
    page_count: Optional[int] = Field(None, description="Nombre de pages")

    # Provenance
    author_name: Optional[str] = Field(None, description="Nom auteur extrait (dc:creator)")
    author_email: Optional[str] = Field(None, description="Email auteur")
    reviewer_name: Optional[str] = Field(None, description="Nom reviewer/approver")

    # Lineage
    supersedes_version_id: Optional[str] = Field(None, description="ID version précédente (lineage)")

    # Metadata custom
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata custom extraite")

    @validator('checksum')
    def validate_checksum_format(cls, v):
        """Valide format SHA256 (64 hex chars)."""
        if not v or len(v) != 64:
            raise ValueError("checksum doit être SHA256 (64 caractères hexadécimaux)")
        if not all(c in '0123456789abcdef' for c in v.lower()):
            raise ValueError("checksum doit contenir uniquement des caractères hexadécimaux")
        return v.lower()


class DocumentVersionUpdate(BaseModel):
    """Mise à jour version (champs optionnels)."""
    version_label: Optional[str] = None
    effective_date: Optional[datetime] = None
    author_name: Optional[str] = None
    reviewer_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentVersionResponse(DocumentVersionBase):
    """Response version complète."""
    version_id: str = Field(..., description="UUID unique de la version")
    document_id: str
    checksum: str

    # Metadata
    file_size: Optional[int] = None
    page_count: Optional[int] = None

    # Provenance
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    reviewer_name: Optional[str] = None

    # Status
    is_latest: bool = Field(default=False, description="Est-ce la version courante ?")

    # Lineage
    supersedes_version_id: Optional[str] = None
    superseded_by_version_id: Optional[str] = Field(None, description="ID version suivante")

    # Metadata custom
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    created_at: datetime
    ingested_at: Optional[datetime] = Field(None, description="Date ingestion dans système")

    class Config:
        from_attributes = True


# === Lineage & History ===

class DocumentLineageNode(BaseModel):
    """Noeud dans le graphe de lineage."""
    version_id: str
    version_label: str
    effective_date: datetime
    author_name: Optional[str] = None
    is_latest: bool = False


class DocumentLineageResponse(BaseModel):
    """Response lineage complet d'un document."""
    document_id: str
    document_title: str
    versions: List[DocumentLineageNode] = Field(default_factory=list, description="Versions ordonnées chronologiquement")
    total_versions: int = 0


class DocumentVersionComparison(BaseModel):
    """Comparaison entre 2 versions."""
    document_id: str

    # Version 1 (ancienne)
    version_1_id: str
    version_1_label: str
    version_1_date: datetime

    # Version 2 (nouvelle)
    version_2_id: str
    version_2_label: str
    version_2_date: datetime

    # Différences
    metadata_changes: Dict[str, Any] = Field(default_factory=dict, description="Changements metadata")
    checksum_differs: bool = Field(default=False, description="Contenu différent ?")
    author_changed: bool = Field(default=False)

    # Statistiques
    days_between: int = Field(default=0, description="Jours entre les 2 versions")


# === Query Filters ===

class DocumentQueryFilters(BaseModel):
    """Filtres pour requêtes documents."""
    tenant_id: str = "default"
    status: Optional[DocumentStatus] = None
    document_type: Optional[DocumentType] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class DocumentVersionQueryFilters(BaseModel):
    """Filtres pour requêtes versions."""
    document_id: Optional[str] = None
    is_latest: Optional[bool] = None
    effective_date_from: Optional[datetime] = None
    effective_date_to: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# === Liste responses ===

class DocumentListResponse(BaseModel):
    """Response liste documents."""
    documents: List[DocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentVersionListResponse(BaseModel):
    """Response liste versions."""
    versions: List[DocumentVersionResponse]
    total: int
    limit: int
    offset: int
