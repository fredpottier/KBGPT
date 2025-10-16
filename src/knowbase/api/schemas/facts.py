"""
Schémas Pydantic pour API Facts

Définit les modèles Request/Response pour endpoints /facts
avec validation stricte et documentation OpenAPI.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict
from datetime import datetime
from enum import Enum


# ===================================
# ENUMS
# ===================================

class FactStatus(str, Enum):
    """Statut gouvernance fact."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


class FactType(str, Enum):
    """Type/catégorie fact métier."""
    SERVICE_LEVEL = "SERVICE_LEVEL"
    CAPACITY = "CAPACITY"
    PRICING = "PRICING"
    FEATURE = "FEATURE"
    COMPLIANCE = "COMPLIANCE"
    GENERAL = "GENERAL"


class ValueType(str, Enum):
    """Type valeur fact."""
    NUMERIC = "numeric"
    TEXT = "text"
    DATE = "date"
    BOOLEAN = "boolean"


class ConflictType(str, Enum):
    """Type conflit détecté."""
    CONTRADICTS = "CONTRADICTS"
    OVERRIDES = "OVERRIDES"
    OUTDATED = "OUTDATED"
    DUPLICATE = "DUPLICATE"


# ===================================
# REQUEST SCHEMAS
# ===================================

class FactCreate(BaseModel):
    """Schéma création fact."""

    subject: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="Sujet du fact (ex: 'SAP S/4HANA Cloud')",
        examples=["SAP S/4HANA Cloud, Private Edition"]
    )
    predicate: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Prédicat/propriété (ex: 'SLA_garantie')",
        examples=["SLA_garantie"]
    )
    object: str = Field(
        ...,
        max_length=500,
        description="Objet textuel (ex: '99.7%')",
        examples=["99.7%"]
    )
    value: float = Field(
        ...,
        description="Valeur numérique pour comparaison",
        examples=[99.7]
    )
    unit: str = Field(
        ...,
        max_length=50,
        description="Unité de mesure",
        examples=["%"]
    )
    value_type: ValueType = Field(
        default=ValueType.NUMERIC,
        description="Type de valeur"
    )
    fact_type: FactType = Field(
        default=FactType.GENERAL,
        description="Catégorie métier du fact"
    )
    status: FactStatus = Field(
        default=FactStatus.PROPOSED,
        description="Statut gouvernance (proposed par défaut)"
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiance extraction LLM (0.0-1.0)"
    )
    valid_from: Optional[str] = Field(
        default=None,
        description="Date début validité (ISO 8601)",
        examples=["2024-01-01T00:00:00"]
    )
    valid_until: Optional[str] = Field(
        default=None,
        description="Date fin validité (ISO 8601, optionnel)",
        examples=["2024-12-31T23:59:59"]
    )
    source_chunk_id: Optional[str] = Field(
        default=None,
        description="UUID chunk source Qdrant"
    )
    source_document: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Nom document source",
        examples=["proposal_2024.pdf"]
    )
    extraction_method: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Méthode extraction (LLM, manual, API)",
        examples=["llm_vision"]
    )
    extraction_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Modèle LLM utilisé",
        examples=["gpt-4-vision"]
    )
    extraction_prompt_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="ID prompt utilisé"
    )

    @field_validator('valid_from', 'valid_until')
    @classmethod
    def validate_iso_date(cls, v):
        """Valide format ISO 8601."""
        if v:
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(
                    "Date must be ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                )
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "subject": "SAP S/4HANA Cloud, Private Edition",
                "predicate": "SLA_garantie",
                "object": "99.7%",
                "value": 99.7,
                "unit": "%",
                "value_type": "numeric",
                "fact_type": "SERVICE_LEVEL",
                "confidence": 0.95,
                "valid_from": "2024-01-01T00:00:00",
                "source_document": "proposal_2024_q1.pdf",
                "extraction_method": "llm_vision",
                "extraction_model": "gpt-4-vision"
            }
        }
    }


class FactUpdate(BaseModel):
    """Schéma mise à jour fact (partiel)."""

    status: Optional[FactStatus] = Field(
        default=None,
        description="Nouveau statut"
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nouvelle confiance"
    )
    valid_until: Optional[str] = Field(
        default=None,
        description="Nouvelle date fin validité"
    )

    @field_validator('valid_until')
    @classmethod
    def validate_iso_date(cls, v):
        """Valide format ISO 8601."""
        if v:
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise ValueError("Date must be ISO 8601 format")
        return v


class FactApproval(BaseModel):
    """Schéma approbation fact."""

    comment: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Commentaire approbation (optionnel)"
    )


class FactRejection(BaseModel):
    """Schéma rejet fact."""

    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Raison du rejet (requis)"
    )
    comment: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Commentaire additionnel (optionnel)"
    )


# ===================================
# RESPONSE SCHEMAS
# ===================================

class FactResponse(BaseModel):
    """Schéma réponse fact complet."""

    uuid: str = Field(..., description="UUID unique fact")
    tenant_id: str = Field(..., description="ID tenant (multi-tenancy)")
    subject: str = Field(..., description="Sujet fact")
    predicate: str = Field(..., description="Prédicat/propriété")
    object: str = Field(..., description="Objet textuel")
    value: float = Field(..., description="Valeur numérique")
    unit: str = Field(..., description="Unité mesure")
    value_type: str = Field(..., description="Type valeur")
    fact_type: str = Field(..., description="Type/catégorie fact")
    status: str = Field(..., description="Statut gouvernance")
    confidence: float = Field(..., description="Confiance extraction (0-1)")
    valid_from: str = Field(..., description="Date début validité")
    valid_until: Optional[str] = Field(None, description="Date fin validité")
    created_at: str = Field(..., description="Date création")
    updated_at: str = Field(..., description="Date dernière MAJ")
    source_chunk_id: Optional[str] = Field(None, description="UUID chunk Qdrant")
    source_document: Optional[str] = Field(None, description="Document source")
    approved_by: Optional[str] = Field(None, description="User ID approbateur")
    approved_at: Optional[str] = Field(None, description="Date approbation")
    extraction_method: Optional[str] = Field(None, description="Méthode extraction")
    extraction_model: Optional[str] = Field(None, description="Modèle LLM")
    extraction_prompt_id: Optional[str] = Field(None, description="ID prompt")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "acme_corp",
                "subject": "SAP S/4HANA Cloud, Private Edition",
                "predicate": "SLA_garantie",
                "object": "99.7%",
                "value": 99.7,
                "unit": "%",
                "value_type": "numeric",
                "fact_type": "SERVICE_LEVEL",
                "status": "approved",
                "confidence": 0.95,
                "valid_from": "2024-01-01T00:00:00",
                "valid_until": None,
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-20T14:45:00",
                "source_chunk_id": "abc-123",
                "source_document": "proposal_2024_q1.pdf",
                "approved_by": "expert@acme.com",
                "approved_at": "2024-01-20T14:45:00",
                "extraction_method": "llm_vision",
                "extraction_model": "gpt-4-vision",
                "extraction_prompt_id": "extract_facts_v1"
            }
        }
    }


class ConflictResponse(BaseModel):
    """Schéma réponse conflit détecté."""

    conflict_type: ConflictType = Field(..., description="Type conflit")
    value_diff_pct: float = Field(
        ...,
        description="Différence valeurs en pourcentage"
    )
    fact_approved: FactResponse = Field(..., description="Fact approuvé existant")
    fact_proposed: FactResponse = Field(..., description="Fact proposé conflictuel")

    model_config = {
        "json_schema_extra": {
            "example": {
                "conflict_type": "CONTRADICTS",
                "value_diff_pct": 0.002,
                "fact_approved": {
                    "uuid": "abc-123",
                    "subject": "SAP S/4HANA Cloud",
                    "predicate": "SLA_garantie",
                    "value": 99.7,
                    "status": "approved"
                },
                "fact_proposed": {
                    "uuid": "def-456",
                    "subject": "SAP S/4HANA Cloud",
                    "predicate": "SLA_garantie",
                    "value": 99.5,
                    "status": "proposed"
                }
            }
        }
    }


class FactTimelineEntry(BaseModel):
    """Entrée timeline fact."""

    value: float = Field(..., description="Valeur à cette date")
    unit: str = Field(..., description="Unité")
    valid_from: str = Field(..., description="Date début validité")
    valid_until: Optional[str] = Field(None, description="Date fin validité")
    source_document: Optional[str] = Field(None, description="Document source")
    status: str = Field(..., description="Statut")


class FactsStats(BaseModel):
    """Statistiques facts."""

    total_facts: int = Field(..., description="Nombre total facts")
    by_status: Dict[str, int] = Field(..., description="Répartition par statut")
    by_type: Dict[str, int] = Field(..., description="Répartition par type")
    conflicts_count: int = Field(..., description="Nombre conflits actifs")
    latest_fact_created_at: Optional[str] = Field(
        None,
        description="Date dernier fact créé"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_facts": 156,
                "by_status": {
                    "proposed": 23,
                    "approved": 120,
                    "rejected": 10,
                    "conflicted": 3
                },
                "by_type": {
                    "SERVICE_LEVEL": 45,
                    "CAPACITY": 32,
                    "PRICING": 28,
                    "FEATURE": 35,
                    "GENERAL": 16
                },
                "conflicts_count": 3,
                "latest_fact_created_at": "2024-10-03T16:45:00"
            }
        }
    }
