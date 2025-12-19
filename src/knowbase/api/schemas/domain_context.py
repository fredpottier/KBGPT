"""
Schemas Pydantic pour Domain Context API.

Permet la configuration du contexte métier global de l'instance.
"""

from typing import Dict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class DomainContextCreate(BaseModel):
    """Schema création/mise à jour Domain Context."""

    domain_summary: str = Field(
        ...,
        description="Résumé concis du domaine métier (1-2 phrases)",
        min_length=10,
        max_length=500,
        json_schema_extra={"example": "Entreprise spécialisée dans les solutions cloud pour le secteur de la santé"}
    )

    industry: str = Field(
        ...,
        description="Industrie principale",
        min_length=2,
        max_length=100,
        json_schema_extra={"example": "healthcare"}
    )

    sub_domains: List[str] = Field(
        default_factory=list,
        description="Sous-domaines spécifiques",
        json_schema_extra={"example": ["telemedicine", "patient_records", "clinical_trials"]}
    )

    target_users: List[str] = Field(
        default_factory=list,
        description="Profils utilisateurs cibles",
        json_schema_extra={"example": ["doctors", "nurses", "administrators"]}
    )

    document_types: List[str] = Field(
        default_factory=list,
        description="Types de documents traités",
        json_schema_extra={"example": ["technical", "regulatory", "clinical"]}
    )

    common_acronyms: Dict[str, str] = Field(
        default_factory=dict,
        description="Acronymes courants → Expansions (max 50)",
        json_schema_extra={"example": {"EHR": "Electronic Health Record", "FDA": "Food and Drug Administration"}}
    )

    key_concepts: List[str] = Field(
        default_factory=list,
        description="Concepts clés du domaine à reconnaître prioritairement (max 20)",
        json_schema_extra={"example": ["HIPAA Compliance", "Clinical Trials", "Patient Data Privacy"]}
    )

    context_priority: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Priorité injection contexte dans prompts LLM"
    )


class DomainContextResponse(BaseModel):
    """Schema réponse Domain Context."""

    tenant_id: str = Field(..., description="ID tenant")
    domain_summary: str = Field(..., description="Résumé domaine métier")
    industry: str = Field(..., description="Industrie principale")
    sub_domains: List[str] = Field(default_factory=list)
    target_users: List[str] = Field(default_factory=list)
    document_types: List[str] = Field(default_factory=list)
    common_acronyms: Dict[str, str] = Field(default_factory=dict)
    key_concepts: List[str] = Field(default_factory=list)
    context_priority: str = Field(default="medium")
    llm_injection_prompt: str = Field(..., description="Prompt généré pour injection LLM")
    created_at: datetime = Field(..., description="Date création")
    updated_at: datetime = Field(..., description="Date mise à jour")

    class Config:
        from_attributes = True


class DomainContextPreviewRequest(BaseModel):
    """Schema pour prévisualiser le prompt d'injection."""

    domain_summary: str = Field(..., min_length=10, max_length=500)
    industry: str = Field(..., min_length=2, max_length=100)
    sub_domains: List[str] = Field(default_factory=list)
    common_acronyms: Dict[str, str] = Field(default_factory=dict)
    key_concepts: List[str] = Field(default_factory=list)
    context_priority: Literal["low", "medium", "high"] = Field(default="medium")


class DomainContextPreviewResponse(BaseModel):
    """Schema réponse prévisualisation prompt."""

    llm_injection_prompt: str = Field(..., description="Prompt qui sera injecté dans les LLM")
    estimated_tokens: int = Field(..., description="Nombre estimé de tokens")
