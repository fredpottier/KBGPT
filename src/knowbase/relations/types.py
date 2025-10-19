# Phase 2 OSMOSE - Types Relations & Metadata Layer

from enum import Enum
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class RelationType(str, Enum):
    """Types de relations Phase 2 (12 types - 9 core + 3 optionnels Phase 2.5)"""

    # STRUCTURELLES (Hiérarchies & Taxonomies)
    PART_OF = "PART_OF"
    SUBTYPE_OF = "SUBTYPE_OF"

    # DÉPENDANCES (Fonctionnelles & Techniques)
    REQUIRES = "REQUIRES"
    USES = "USES"

    # INTÉGRATIONS (Connexions Systèmes)
    INTEGRATES_WITH = "INTEGRATES_WITH"
    EXTENDS = "EXTENDS"  # Phase 2.5 optionnel

    # CAPACITÉS (Fonctionnalités Activées)
    ENABLES = "ENABLES"  # Phase 2.5 optionnel

    # TEMPORELLES (Évolution & Cycles de Vie)
    VERSION_OF = "VERSION_OF"
    PRECEDES = "PRECEDES"
    REPLACES = "REPLACES"
    DEPRECATES = "DEPRECATES"

    # VARIANTES (Alternatives & Compétition)
    ALTERNATIVE_TO = "ALTERNATIVE_TO"  # Phase 2.5 optionnel


class ExtractionMethod(str, Enum):
    """Méthode extraction utilisée"""
    PATTERN = "pattern"  # Pattern-based (regex + spaCy)
    LLM = "llm"  # LLM-assisted seul
    HYBRID = "hybrid"  # Pattern + LLM
    INFERRED = "inferred"  # Inférence transitive


class RelationStrength(str, Enum):
    """Force de la relation"""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class RelationStatus(str, Enum):
    """Statut de la relation"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    INFERRED = "inferred"


class RelationMetadata(BaseModel):
    """Metadata layer pour relations Neo4j"""

    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score [0.0-1.0]")
    extraction_method: ExtractionMethod
    source_doc_id: str
    source_chunk_ids: List[str] = Field(default_factory=list)
    language: str = Field(default="EN", description="Langue détection (EN, FR, DE, ES)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    valid_from: Optional[date] = Field(default=None, description="Validité temporelle début")
    valid_until: Optional[date] = Field(default=None, description="Validité temporelle fin")
    strength: RelationStrength = Field(default=RelationStrength.MODERATE)
    status: RelationStatus = Field(default=RelationStatus.ACTIVE)
    require_validation: bool = Field(default=False, description="True pour ENABLES Phase 2.5")

    # Métadonnées spécifiques REPLACES
    breaking_changes: Optional[List[str]] = Field(default=None)
    migration_effort: Optional[str] = Field(default=None, description="LOW|MEDIUM|HIGH")
    backward_compatible: Optional[bool] = Field(default=None)

    # Métadonnées temporelles (VERSION_OF, PRECEDES, REPLACES, DEPRECATES)
    timeline_position: Optional[int] = Field(default=None, description="Position dans séquence chronologique")
    release_date: Optional[date] = Field(default=None)
    eol_date: Optional[date] = Field(default=None, description="End of Life (pour DEPRECATES)")


class TypedRelation(BaseModel):
    """Relation typée extraite entre deux concepts"""

    relation_id: str = Field(description="Identifiant unique relation")
    source_concept: str = Field(description="Concept source (A)")
    target_concept: str = Field(description="Concept target (B)")
    relation_type: RelationType
    metadata: RelationMetadata

    # Justification
    evidence: Optional[str] = Field(default=None, description="Snippet textuel justification")
    context: Optional[str] = Field(default=None, description="Context chunk complet")

    class Config:
        use_enum_values = True


class RelationExtractionResult(BaseModel):
    """Résultat extraction relations pour un document"""

    document_id: str
    relations: List[TypedRelation]
    extraction_time_seconds: float
    total_relations_extracted: int
    relations_by_type: dict[RelationType, int]
    extraction_method_stats: dict[ExtractionMethod, int]
