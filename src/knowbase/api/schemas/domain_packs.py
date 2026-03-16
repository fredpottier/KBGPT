# src/knowbase/api/schemas/domain_packs.py
"""Schemas Pydantic pour l'API Domain Packs."""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class PackInfo(BaseModel):
    """Informations sur un Domain Pack."""
    name: str
    display_name: str
    description: str
    version: str
    priority: int
    is_active: bool = False
    container_state: str = "not_installed"
    entity_types: List[str] = Field(default_factory=list)
    ner_model: str = ""
    ner_model_size_mb: int = 0


class PackListResponse(BaseModel):
    """Réponse liste des packs."""
    packs: List[PackInfo]
    active_count: int


class PackActivateRequest(BaseModel):
    """Requête activation/désactivation."""
    pack_name: str
    tenant_id: str = "default"


class PackActivateResponse(BaseModel):
    """Réponse activation/désactivation."""
    success: bool
    message: str
    active_packs: List[str]
    container_state: str = ""


class PackStatsResponse(BaseModel):
    """Statistiques d'un pack."""
    pack_name: str
    entities_created: int = 0
    claims_linked: int = 0
    coverage_before: Optional[float] = None
    coverage_after: Optional[float] = None


class ReprocessRequest(BaseModel):
    """Requête de reprocessing."""
    pack_name: str
    tenant_id: str = "default"


class ReprocessResponse(BaseModel):
    """Réponse de reprocessing."""
    success: bool
    message: str
    job_id: Optional[str] = None


class ReprocessStatusResponse(BaseModel):
    """Status du reprocessing."""
    state: str
    progress: float = 0.0
    entities_created: int = 0
    claims_linked: int = 0
    error: Optional[str] = None


class InstallResponse(BaseModel):
    """Réponse d'installation."""
    success: bool
    message: str
    pack_name: str = ""
    version: str = ""


class UninstallResponse(BaseModel):
    """Réponse de désinstallation."""
    success: bool
    message: str
