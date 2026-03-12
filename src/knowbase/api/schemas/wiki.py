"""
Schemas Pydantic pour la Wiki Generation Console (Phase 3 — Concept Assembly Engine).

Endpoints : /api/wiki/generate, /api/wiki/status, /api/wiki/article, /api/wiki/concepts/search
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class WikiGenerateRequest(BaseModel):
    concept_name: str = Field(..., description="Nom du concept à générer")
    language: str = Field(default="français", description="Langue de génération")
    force: bool = Field(default=False, description="Forcer la régénération même si un job récent existe")


class WikiGenerateResponse(BaseModel):
    job_id: str
    status: str  # "pending"
    message: str


class WikiJobStatus(BaseModel):
    job_id: str
    status: str  # pending | running | completed | completed_with_warnings | failed
    progress: Optional[str] = None
    error: Optional[str] = None


class WikiResolutionInfo(BaseModel):
    """Diagnostics de résolution du concept (transparence sur l'ancrage)."""

    resolution_method: str = Field(..., description="exact, exact+canon, alias, fuzzy")
    resolution_confidence: float
    matched_entities: int
    ambiguity_notes: List[str] = Field(default_factory=list)


class WikiArticleResponse(BaseModel):
    job_id: str
    concept_name: str
    language: str
    markdown: str
    sections_count: int
    total_citations: int
    generation_confidence: float = Field(
        ..., description="Signal d'exploitation (pas arbitre de vérité)"
    )
    all_gaps: List[str]
    source_count: int
    unit_count: int
    resolution: WikiResolutionInfo
    generated_at: str


class WikiConceptResult(BaseModel):
    entity_name: str
    entity_type: str
    claim_count: int


class WikiConceptSearchResponse(BaseModel):
    results: List[WikiConceptResult]
    total: int
