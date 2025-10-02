"""
Schémas Pydantic pour tracking imports et déduplication

Phase 1 - Critère 1.5
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from knowbase.ingestion.deduplication import DuplicateStatus


class ImportMetadata(BaseModel):
    """Metadata tracking import document"""

    import_id: str = Field(..., description="UUID unique import")
    tenant_id: str = Field(..., description="ID tenant propriétaire")
    filename: str = Field(..., description="Nom fichier source")
    file_hash: Optional[str] = Field(None, description="SHA256 fichier brut (format: sha256:...)")
    content_hash: Optional[str] = Field(None, description="SHA256 contenu normalisé (format: sha256:...)")
    episode_uuid: Optional[str] = Field(None, description="UUID episode Graphiti associé")
    chunk_count: int = Field(0, description="Nombre chunks Qdrant créés")
    entities_count: int = Field(0, description="Nombre entities extraites")
    relations_count: int = Field(0, description="Nombre relations extraites")
    imported_at: str = Field(..., description="Timestamp import (ISO 8601)")
    import_status: str = Field(
        default="completed",
        description="Statut import: completed, duplicate_rejected, failed"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "import_id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "corporate",
                "filename": "Group_Reporting_Overview.pptx",
                "file_hash": "sha256:abc123def456...",
                "content_hash": "sha256:789ghi012jkl...",
                "episode_uuid": "ep_abc123",
                "chunk_count": 42,
                "entities_count": 76,
                "relations_count": 62,
                "imported_at": "2025-10-02T14:30:00Z",
                "import_status": "completed"
            }
        }


class CheckDuplicateRequest(BaseModel):
    """Request check duplicate avant upload"""

    file_hash: Optional[str] = Field(
        None,
        description="SHA256 fichier brut (optionnel si upload pas encore fait)"
    )
    content_hash: Optional[str] = Field(
        None,
        description="SHA256 contenu normalisé (optionnel, calculé post-extraction)"
    )
    filename: str = Field(..., description="Nom fichier à importer")
    tenant_id: str = Field(..., description="ID tenant")

    class Config:
        json_schema_extra = {
            "example": {
                "file_hash": "sha256:abc123def456...",
                "content_hash": "sha256:789ghi012jkl...",
                "filename": "my_document.pptx",
                "tenant_id": "corporate"
            }
        }


class CheckDuplicateResponse(BaseModel):
    """Response check duplicate"""

    status: DuplicateStatus = Field(..., description="Statut déduplication")
    is_duplicate: bool = Field(..., description="True si exact duplicate (rejet)")
    existing_import: Optional[ImportMetadata] = Field(
        None,
        description="Metadata import existant si duplicate trouvé"
    )
    message: str = Field(..., description="Message explicatif")
    allow_upload: bool = Field(True, description="True si upload autorisé")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "exact_duplicate",
                "is_duplicate": True,
                "existing_import": {
                    "import_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tenant_id": "corporate",
                    "filename": "Group_Reporting_Overview.pptx",
                    "chunk_count": 42,
                    "imported_at": "2025-10-01T10:00:00Z"
                },
                "message": "Document déjà importé le 2025-10-01T10:00:00Z (fichier: Group_Reporting_Overview.pptx, 42 chunks)",
                "allow_upload": False
            }
        }


class ImportHistoryResponse(BaseModel):
    """Response historique imports"""

    imports: list[ImportMetadata] = Field(..., description="Liste imports")
    total: int = Field(..., description="Nombre total imports (avant pagination)")
    limit: int = Field(..., description="Limite pagination")
    offset: int = Field(..., description="Offset pagination")

    class Config:
        json_schema_extra = {
            "example": {
                "imports": [
                    {
                        "import_id": "550e8400-e29b-41d4-a716-446655440000",
                        "filename": "Doc1.pptx",
                        "chunk_count": 42,
                        "imported_at": "2025-10-02T14:30:00Z"
                    }
                ],
                "total": 15,
                "limit": 50,
                "offset": 0
            }
        }
