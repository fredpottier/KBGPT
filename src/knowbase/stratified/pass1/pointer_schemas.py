"""
OSMOSE Pipeline V2 - Pointer-Based Schemas
==========================================
Ref: Plan Pointer-Based Extraction (2026-01-27)

Modèles Pydantic pour l'extraction pointer-based:
- PointerConcept: Output LLM avec unit_id
- ConceptCandidate: Concept top-down (guide recherche)
- ConceptAnchored: Concept avec preuve validée (exploitable)

PHILOSOPHIE:
- Le LLM POINTE vers une unité au lieu de COPIER
- La reconstruction du texte est GARANTIE verbatim
- La confidence LLM est ignorée pour la promotion
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# ENUMS
# ============================================================================

class PointerConceptType(str, Enum):
    """Types de concepts pour extraction pointer-based."""
    PRESCRIPTIVE = "PRESCRIPTIVE"    # Règle, obligation, contrainte
    DEFINITIONAL = "DEFINITIONAL"    # Définition, explication
    FACTUAL = "FACTUAL"              # Fait, information vérifiable
    PERMISSIVE = "PERMISSIVE"        # Option, possibilité


class ValueKind(str, Enum):
    """Types de valeurs extraites."""
    VERSION = "version"
    PERCENTAGE = "percentage"
    SIZE = "size"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DURATION = "duration"
    ENUM = "enum"


# ============================================================================
# LLM OUTPUT SCHEMAS (Pydantic)
# ============================================================================

class PointerConcept(BaseModel):
    """
    Concept pointé par le LLM.

    Le LLM retourne un unit_id au lieu de copier le texte.
    La reconstruction du texte verbatim est faite côté code.

    Exemple JSON:
    {
        "label": "TLS minimum version",
        "type": "PRESCRIPTIVE",
        "unit_id": "U1",
        "confidence": 0.9,
        "value_kind": "version"
    }
    """
    label: str = Field(
        ...,
        max_length=100,
        description="Label court du concept (2-5 mots)"
    )
    type: Literal["PRESCRIPTIVE", "DEFINITIONAL", "FACTUAL", "PERMISSIVE"] = Field(
        ...,
        description="Type sémantique du concept"
    )
    unit_id: str = Field(
        ...,
        pattern=r"^U\d+$",
        description="ID de l'unité pointée (format: U1, U2, ...)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confiance LLM (ignorée pour promotion, utilisée pour debug)"
    )
    value_kind: Optional[str] = Field(
        None,
        description="Type de valeur si applicable (version, percentage, size, etc.)"
    )

    @field_validator('unit_id')
    @classmethod
    def validate_unit_id(cls, v: str) -> str:
        """Valide le format de unit_id."""
        if not v.startswith("U") or not v[1:].isdigit():
            raise ValueError(f"Invalid unit_id format: {v}. Expected U1, U2, etc.")
        return v


class PointerExtractionResponse(BaseModel):
    """
    Réponse complète de l'extraction pointer-based.

    Format attendu du LLM:
    {
        "concepts": [
            {"label": "...", "type": "...", "unit_id": "U1", "confidence": 0.9},
            ...
        ]
    }
    """
    concepts: List[PointerConcept] = Field(
        default_factory=list,
        description="Liste des concepts pointés"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "concepts": [
                    {
                        "label": "TLS minimum version",
                        "type": "PRESCRIPTIVE",
                        "unit_id": "U1",
                        "confidence": 0.9,
                        "value_kind": "version"
                    },
                    {
                        "label": "Data encryption standard",
                        "type": "PRESCRIPTIVE",
                        "unit_id": "U3",
                        "confidence": 0.85,
                        "value_kind": None
                    }
                ]
            }
        }
    )


# ============================================================================
# INTERNAL DATA CLASSES
# ============================================================================

@dataclass
class ConceptCandidate:
    """
    Concept top-down sans preuve (guide la recherche).

    Source: GlobalView ou analyse haut niveau.
    Usage: Orienter l'extraction, pas exploitable directement.

    NOTE: Un ConceptCandidate n'est PAS navigable dans le KG final.
    Il doit être transformé en ConceptAnchored via validation.
    """
    label: str
    source: str = "top_down"  # "top_down" | "global_view" | "theme_derived"
    search_terms: List[str] = field(default_factory=list)
    expected_type: Optional[str] = None  # Type attendu (PRESCRIPTIVE, etc.)

    def __hash__(self):
        return hash(self.label)


@dataclass
class Anchor:
    """
    Ancrage d'un concept vers un DocItem via une unité.

    L'ancrage est GARANTI verbatim car reconstruit depuis l'index.
    """
    docitem_id: str       # ID composite du DocItem (tenant:doc:item)
    unit_id: str          # ID local de l'unité (U1, U2, etc.)
    char_start: int       # Position dans le DocItem
    char_end: int
    unit_type: str        # "sentence" | "clause" | "bullet" | "segment"

    @property
    def unit_global_id(self) -> str:
        """ID global de l'unité (docitem_id#unit_id)."""
        return f"{self.docitem_id}#{self.unit_id}"


@dataclass
class ConceptAnchored:
    """
    Concept avec preuve validée (exploitable).

    Source: Bottom-up via pointer + validation.
    Usage: Exploitable dans le KG, avec preuve garantie verbatim.

    Le passage de ConceptCandidate à ConceptAnchored nécessite:
    1. Un pointeur LLM (unit_id)
    2. Une validation 3 niveaux (lexical, type, value)
    """
    label: str
    concept_type: str                    # PRESCRIPTIVE, DEFINITIONAL, etc.
    exact_quote: str                     # Texte verbatim (depuis index, GARANTI)
    anchor: Anchor                       # Ancrage vers le DocItem
    validation_status: str               # "VALID" | "DOWNGRADED"
    validation_score: float              # Score lexical de la validation
    value_kind: Optional[str] = None     # Type de valeur si applicable
    downgraded_from: Optional[str] = None  # Type original si downgraded

    # Metadata
    concept_id: str = ""                 # ID généré pour le KG

    def __post_init__(self):
        if not self.concept_id:
            import uuid
            self.concept_id = f"concept_{uuid.uuid4().hex[:8]}"


@dataclass
class PointerExtractionResult:
    """
    Résultat complet de l'extraction pointer-based.

    Contient:
    - Les concepts ancrés (validés)
    - Les concepts rejetés (avec raisons)
    - Les statistiques
    """
    docitem_id: str
    anchored: List[ConceptAnchored] = field(default_factory=list)
    rejected: List[tuple] = field(default_factory=list)  # (PointerConcept, reason)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def valid_count(self) -> int:
        return len(self.anchored)

    @property
    def reject_count(self) -> int:
        return len(self.rejected)

    @property
    def valid_rate(self) -> float:
        total = self.valid_count + self.reject_count
        return self.valid_count / total if total > 0 else 0.0


# ============================================================================
# SCHEMA HELPERS
# ============================================================================

def get_pointer_extraction_schema() -> dict:
    """
    Retourne le JSON Schema pour vLLM structured outputs.

    Compatible avec le paramètre guided_json de vLLM.
    """
    return PointerExtractionResponse.model_json_schema()


def get_vllm_response_format() -> dict:
    """
    Retourne le format de réponse pour vLLM.

    Usage:
        response_format = get_vllm_response_format()
        # Passer à vLLM/OpenAI API
    """
    return {
        "type": "json_object",
        "schema": get_pointer_extraction_schema()
    }


def parse_pointer_response(json_str: str) -> PointerExtractionResponse:
    """
    Parse une réponse JSON en PointerExtractionResponse.

    Args:
        json_str: JSON string de la réponse LLM

    Returns:
        PointerExtractionResponse validé

    Raises:
        ValueError si JSON invalide ou non conforme au schema
    """
    import json

    try:
        data = json.loads(json_str)
        return PointerExtractionResponse.model_validate(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    except Exception as e:
        raise ValueError(f"Schema validation failed: {e}")


# ============================================================================
# CONVERSION HELPERS
# ============================================================================

def pointer_to_anchored(
    pointer: PointerConcept,
    unit_text: str,
    anchor: Anchor,
    validation_status: str,
    validation_score: float,
    downgraded_from: Optional[str] = None,
) -> ConceptAnchored:
    """
    Convertit un PointerConcept validé en ConceptAnchored.

    Args:
        pointer: Concept pointé par le LLM
        unit_text: Texte verbatim de l'unité (depuis index)
        anchor: Ancrage vers le DocItem
        validation_status: "VALID" ou "DOWNGRADED"
        validation_score: Score lexical
        downgraded_from: Type original si downgraded

    Returns:
        ConceptAnchored prêt pour le KG
    """
    return ConceptAnchored(
        label=pointer.label,
        concept_type=pointer.type if validation_status == "VALID" else (downgraded_from or pointer.type),
        exact_quote=unit_text,
        anchor=anchor,
        validation_status=validation_status,
        validation_score=validation_score,
        value_kind=pointer.value_kind,
        downgraded_from=downgraded_from,
    )
