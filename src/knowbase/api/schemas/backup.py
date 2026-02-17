"""
Schemas Pydantic pour Backup & Restore API.

Permet la sauvegarde et restauration complète du système OSMOSE.
"""

from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ComponentStatus(BaseModel):
    """Statut d'un composant dans le backup."""
    status: str = Field(..., description="success / error / skipped")
    size_bytes: int = Field(default=0)
    error: Optional[str] = None


class Neo4jComponentStatus(ComponentStatus):
    """Statut Neo4j avec détails."""
    node_counts: Dict[str, int] = Field(default_factory=dict)
    relationship_counts: Dict[str, int] = Field(default_factory=dict)
    total_nodes: int = 0
    total_relationships: int = 0


class QdrantCollectionInfo(BaseModel):
    """Info d'une collection Qdrant."""
    point_count: int = 0
    vector_size: int = 0


class QdrantComponentStatus(ComponentStatus):
    """Statut Qdrant avec détails."""
    collections: Dict[str, QdrantCollectionInfo] = Field(default_factory=dict)


class PostgresComponentStatus(ComponentStatus):
    """Statut PostgreSQL avec détails."""
    table_counts: Dict[str, int] = Field(default_factory=dict)


class ExtractionCacheStatus(ComponentStatus):
    """Statut extraction cache."""
    file_count: int = 0


class BackupComponents(BaseModel):
    """Ensemble des composants du backup."""
    neo4j: Neo4jComponentStatus = Field(default_factory=lambda: Neo4jComponentStatus(status="pending"))
    qdrant: QdrantComponentStatus = Field(default_factory=lambda: QdrantComponentStatus(status="pending"))
    postgresql: PostgresComponentStatus = Field(default_factory=lambda: PostgresComponentStatus(status="pending"))
    redis: ComponentStatus = Field(default_factory=lambda: ComponentStatus(status="pending"))
    extraction_cache: ExtractionCacheStatus = Field(default_factory=lambda: ExtractionCacheStatus(status="pending"))


class ImportedDocumentInfo(BaseModel):
    """Info résumée d'un document importé."""
    doc_id: str
    primary_subject: Optional[str] = None


class DomainContextInfo(BaseModel):
    """Info résumée du domain context."""
    industry: str = ""
    domain_summary: str = ""


class BackupManifest(BaseModel):
    """Manifest complet d'un backup."""
    backup_id: str
    name: str
    created_at: str
    duration_seconds: float = 0
    size_bytes: int = 0
    tenant_id: str = "default"
    osmose_version: str = "1.0"
    domain_context: DomainContextInfo = Field(default_factory=DomainContextInfo)
    components: BackupComponents = Field(default_factory=BackupComponents)
    imported_documents: List[ImportedDocumentInfo] = Field(default_factory=list)


class BackupSummary(BaseModel):
    """Résumé d'un backup pour la liste."""
    name: str
    created_at: str
    size_bytes: int = 0
    size_human: str = ""
    industry: str = ""
    domain_summary: str = ""
    neo4j_nodes: int = 0
    qdrant_points: int = 0
    documents_count: int = 0
    components_ok: int = 0
    components_total: int = 5


class BackupListResponse(BaseModel):
    """Réponse liste des backups."""
    backups: List[BackupSummary]
    total: int
    backups_dir: str


class CurrentSystemStats(BaseModel):
    """Stats du système actuel."""
    neo4j_nodes: int = 0
    neo4j_relationships: int = 0
    neo4j_node_counts: Dict[str, int] = Field(default_factory=dict)
    qdrant_collections: Dict[str, int] = Field(default_factory=dict)
    qdrant_total_points: int = 0
    postgres_sessions: int = 0
    postgres_messages: int = 0
    postgres_users: int = 0
    postgres_table_counts: Dict[str, int] = Field(default_factory=dict)
    redis_keys: int = 0
    extraction_cache_files: int = 0
    extraction_cache_size_bytes: int = 0
    domain_context: Optional[DomainContextInfo] = None
    imported_documents: List[ImportedDocumentInfo] = Field(default_factory=list)


class BackupCreateRequest(BaseModel):
    """Requête de création de backup."""
    name: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$')
    include_cache: bool = Field(default=True, description="Inclure le cache d'extraction")


class BackupRestoreRequest(BaseModel):
    """Requête de restauration."""
    name: str = Field(..., min_length=1)
    auto_backup: bool = Field(default=False, description="Sauvegarder l'état actuel avant restauration")


class BackupJobStatus(BaseModel):
    """Statut d'une opération backup/restore en cours."""
    job_id: str
    operation: str  # "backup" ou "restore"
    status: str  # "running" / "completed" / "failed"
    name: str
    started_at: str
    progress: str = ""
    error: Optional[str] = None
    log_lines: List[str] = Field(default_factory=list)
