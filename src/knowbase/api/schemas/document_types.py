"""
Schémas Pydantic pour Document Types Management.

Phase 6 - Document Types Management
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ===== Entity Type Association Schemas =====

class EntityTypeAssociationBase(BaseModel):
    """Base schema pour association entity type."""
    entity_type_name: str = Field(..., description="Nom du type d'entité")
    source: str = Field(default="manual", description="Source: manual | llm_discovered | template")
    confidence: Optional[float] = Field(None, description="Confidence score (0.0-1.0)")
    examples: Optional[List[str]] = Field(None, description="Exemples d'entités")


class EntityTypeAssociationCreate(EntityTypeAssociationBase):
    """Schema pour créer association."""
    pass


class EntityTypeAssociationResponse(EntityTypeAssociationBase):
    """Schema pour réponse association."""
    id: int
    document_type_id: str
    validated_by: Optional[str]
    validated_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ===== Document Type Schemas =====

class DocumentTypeBase(BaseModel):
    """Base schema pour document type."""
    name: str = Field(..., min_length=1, max_length=100, description="Nom du type de document")
    slug: str = Field(..., min_length=1, max_length=50, description="Slug unique")
    description: Optional[str] = Field(None, description="Description du type")
    context_prompt: Optional[str] = Field(None, description="Prompt contextuel pour LLM")
    is_active: bool = Field(default=True, description="Type actif ou archivé")


class DocumentTypeCreate(DocumentTypeBase):
    """Schema pour créer document type."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    entity_types: Optional[List[str]] = Field(
        default=None,
        description="Liste des entity_type_names à associer (source: manual)"
    )


class DocumentTypeUpdate(BaseModel):
    """Schema pour mettre à jour document type."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None)
    context_prompt: Optional[str] = Field(None)
    is_active: Optional[bool] = Field(None)


class DocumentTypeResponse(DocumentTypeBase):
    """Schema pour réponse document type."""
    id: str
    usage_count: int
    tenant_id: str
    created_at: datetime
    updated_at: datetime
    suggested_entity_types: Optional[List[str]] = Field(
        default=None,
        description="Liste des entity_type_names suggérés"
    )
    entity_type_count: Optional[int] = Field(None, description="Nombre de types associés")

    class Config:
        from_attributes = True


class DocumentTypeListResponse(BaseModel):
    """Schema pour liste de document types."""
    document_types: List[DocumentTypeResponse]
    total: int


# ===== Analysis Schemas =====

class AnalyzeSampleRequest(BaseModel):
    """Schema pour requête d'analyse de document sample."""
    context_prompt: Optional[str] = Field(
        None,
        description="Contexte additionnel pour guider le LLM"
    )
    model_preference: str = Field(
        default="claude-sonnet",
        description="Modèle LLM à utiliser"
    )


class SuggestedEntityType(BaseModel):
    """Schema pour type d'entité suggéré par LLM."""
    name: str = Field(..., description="Nom du type (UPPERCASE)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    examples: List[str] = Field(default_factory=list, description="Exemples trouvés dans le document")
    description: Optional[str] = Field(None, description="Description du type")
    is_existing: bool = Field(default=False, description="True si le type existe déjà en base, False si nouveau")


class AnalyzeSampleResponse(BaseModel):
    """Schema pour réponse d'analyse de document sample."""
    job_id: str = Field(..., description="ID du job async")
    status: str = Field(default="queued", description="Statut: queued | running | completed | failed")
    message: str = Field(default="Analysis started", description="Message de statut")


class AnalyzeSampleResult(BaseModel):
    """Schema pour résultat d'analyse de document sample."""
    suggested_types: List[SuggestedEntityType] = Field(
        default_factory=list,
        description="Types suggérés par le LLM"
    )
    document_summary: Optional[str] = Field(None, description="Résumé du document analysé")
    suggested_context_prompt: Optional[str] = Field(
        None,
        description="Prompt contextuel optimisé suggéré par le LLM pour l'ingestion de documents similaires"
    )
    pages_analyzed: int = Field(default=0, description="Nombre de pages analysées")


# ===== Template Schemas =====

class DocumentTypeTemplate(BaseModel):
    """Schema pour template prédéfini."""
    name: str
    slug: str
    description: str
    context_prompt: str
    suggested_entity_types: List[str]
    icon: Optional[str] = None


class DocumentTypeTemplateListResponse(BaseModel):
    """Schema pour liste de templates."""
    templates: List[DocumentTypeTemplate]


# ===== Add Entity Types Schemas =====

class AddEntityTypesRequest(BaseModel):
    """Schema pour ajouter entity types à un document type."""
    entity_type_names: List[str] = Field(..., description="Liste des types à ajouter")
    source: str = Field(default="manual", description="Source de l'ajout")
    validated_by: Optional[str] = Field(None, description="Email admin qui valide")


class RemoveEntityTypeRequest(BaseModel):
    """Schema pour retirer un entity type."""
    entity_type_name: str = Field(..., description="Type à retirer")


__all__ = [
    "EntityTypeAssociationCreate",
    "EntityTypeAssociationResponse",
    "DocumentTypeCreate",
    "DocumentTypeUpdate",
    "DocumentTypeResponse",
    "DocumentTypeListResponse",
    "AnalyzeSampleRequest",
    "AnalyzeSampleResponse",
    "AnalyzeSampleResult",
    "SuggestedEntityType",
    "DocumentTypeTemplate",
    "DocumentTypeTemplateListResponse",
    "AddEntityTypesRequest",
    "RemoveEntityTypeRequest",
]
