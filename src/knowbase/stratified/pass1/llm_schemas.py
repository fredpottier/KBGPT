"""
OSMOSE Pipeline V2 - Volet B: Schemas Pydantic pour vLLM Structured Outputs
===========================================================================
Ref: doc/ongoing/PLAN_QWEN_STRUCTURED_OUTPUTS_2026-01-27.md

Schemas JSON stricts pour forcer vLLM à générer du JSON valide.
Utilisés avec response_format={"type": "json_schema", "json_schema": {...}}

Avantages:
- Impossible de tronquer le JSON (vLLM garantit la structure)
- Impossible de reformuler (le texte doit matcher le schema)
- Types strictement validés (enum, int, float range)
"""

from enum import Enum
from typing import Dict, List, Literal, Optional, Any
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# ENUMS POUR STRUCTURED OUTPUTS
# ============================================================================

class AssertionTypeEnum(str, Enum):
    """Types d'assertions supportés."""
    definitional = "definitional"
    factual = "factual"
    prescriptive = "prescriptive"
    permissive = "permissive"
    conditional = "conditional"
    causal = "causal"
    procedural = "procedural"
    comparative = "comparative"


class LanguageEnum(str, Enum):
    """Langues supportées."""
    fr = "fr"
    en = "en"
    de = "de"


class ConceptRoleEnum(str, Enum):
    """Rôles de concepts."""
    CENTRAL = "CENTRAL"
    STANDARD = "STANDARD"
    CONTEXTUAL = "CONTEXTUAL"


class LinkTypeEnum(str, Enum):
    """Types de liens sémantiques."""
    defines = "defines"
    describes = "describes"
    constrains = "constrains"
    enables = "enables"
    conditions = "conditions"
    causes = "causes"


class DocumentStructureEnum(str, Enum):
    """Types de structure documentaire."""
    CENTRAL = "CENTRAL"
    TRANSVERSAL = "TRANSVERSAL"
    CONTEXTUAL = "CONTEXTUAL"


# ============================================================================
# PHASE 1.1: DOCUMENT ANALYSIS
# ============================================================================

class StructureInfo(BaseModel):
    """Information sur la structure du document."""
    chosen: DocumentStructureEnum
    justification: str = Field(..., max_length=200)


class DocumentAnalysisResponse(BaseModel):
    """Réponse pour l'analyse documentaire (Phase 1.1)."""
    subject_name: str = Field(..., max_length=50, description="Nom court du sujet (5-10 mots)")
    subject: str = Field(..., max_length=200, description="Résumé en 1 phrase")
    structure: StructureInfo
    themes: List[str] = Field(..., max_length=10)
    language: LanguageEnum


# ============================================================================
# PHASE 1.2: CONCEPT IDENTIFICATION
# ============================================================================

class ConceptCompact(BaseModel):
    """Concept en format compact (sans définition pour éviter troncature)."""
    name: str = Field(..., max_length=50, description="Nom du concept (2-4 mots)")
    role: ConceptRoleEnum
    theme: str = Field(..., max_length=100)


class RefusedTerm(BaseModel):
    """Terme refusé avec raison."""
    term: str = Field(..., max_length=50)
    reason: str = Field(..., max_length=100)


class ConceptIdentificationResponse(BaseModel):
    """Réponse pour l'identification de concepts (Phase 1.2)."""
    concepts: List[ConceptCompact] = Field(..., max_length=100)  # V2.2: adaptatif jusqu'à 80
    refused_terms: List[RefusedTerm] = Field(default_factory=list, max_length=20)


# ============================================================================
# PHASE 1.3: ASSERTION EXTRACTION
# ============================================================================

class ExtractedAssertion(BaseModel):
    """
    Assertion extraite du texte.

    IMPORTANT: Le champ 'text' DOIT être une copie VERBATIM du texte source.
    Le LLM ne doit PAS reformuler.
    """
    text: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Texte EXACT copié du source (INTERDIT de reformuler)"
    )
    type: AssertionTypeEnum
    start_char: int = Field(..., ge=0, description="Position de début dans le texte source")
    end_char: int = Field(..., gt=0, description="Position de fin dans le texte source")
    confidence: float = Field(..., ge=0.0, le=1.0)
    language: LanguageEnum = LanguageEnum.en

    @field_validator('end_char')
    @classmethod
    def end_after_start(cls, v: int, info) -> int:
        """Vérifie que end > start."""
        if 'start_char' in info.data and v <= info.data['start_char']:
            raise ValueError('end_char must be greater than start_char')
        return v


class AssertionExtractionResponse(BaseModel):
    """Réponse pour l'extraction d'assertions (Phase 1.3)."""
    assertions: List[ExtractedAssertion] = Field(
        default_factory=list,
        max_length=50,
        description="Liste des assertions extraites (max 50 par chunk)"
    )


# ============================================================================
# PHASE 1.3b: SEMANTIC LINKING
# ============================================================================

class SemanticLink(BaseModel):
    """Lien sémantique entre assertion et concept."""
    assertion_id: str = Field(..., pattern=r"^assert_[a-f0-9]{8}$")
    concept_id: str = Field(..., pattern=r"^concept_[a-f0-9]{8}$")
    link_type: LinkTypeEnum
    justification: str = Field(..., max_length=150)
    confidence: float = Field(..., ge=0.0, le=1.0)


class UnlinkedAssertion(BaseModel):
    """Assertion non liée à un concept."""
    assertion_id: str = Field(..., pattern=r"^assert_[a-f0-9]{8}$")
    reason: str = Field(..., max_length=150)


class SemanticLinkingResponse(BaseModel):
    """Réponse pour le linking sémantique (Phase 1.3b)."""
    links: List[SemanticLink] = Field(default_factory=list)
    unlinked_assertions: List[UnlinkedAssertion] = Field(default_factory=list)


# ============================================================================
# HELPERS POUR GENERATION DE SCHEMAS
# ============================================================================

def get_schema_for_phase(phase: str) -> Dict[str, Any]:
    """
    Retourne le JSON schema pour une phase donnée.

    Args:
        phase: "document_analysis", "concept_identification",
               "assertion_extraction", "semantic_linking"

    Returns:
        JSON Schema dict compatible avec vLLM response_format
    """
    schemas = {
        "document_analysis": DocumentAnalysisResponse,
        "concept_identification": ConceptIdentificationResponse,
        "assertion_extraction": AssertionExtractionResponse,
        "semantic_linking": SemanticLinkingResponse,
    }

    model = schemas.get(phase)
    if model is None:
        raise ValueError(f"Unknown phase: {phase}")

    return model.model_json_schema()


def get_vllm_response_format(phase: str, strict: bool = True) -> Dict[str, Any]:
    """
    Retourne le format response_format pour vLLM.

    Args:
        phase: Phase du pipeline
        strict: Si True, applique la validation stricte

    Returns:
        Dict compatible avec vLLM response_format parameter
    """
    schema = get_schema_for_phase(phase)

    return {
        "type": "json_schema",
        "json_schema": {
            "name": phase,
            "strict": strict,
            "schema": schema
        }
    }


def get_guided_json_schema(phase: str) -> Dict[str, Any]:
    """
    Retourne le schema pour le mode guided_json (legacy vLLM).

    Args:
        phase: Phase du pipeline

    Returns:
        JSON Schema dict pour extra_body={"guided_json": schema}
    """
    return get_schema_for_phase(phase)


# ============================================================================
# SCHEMAS SIMPLIFIES (POUR MODELES LIMITES)
# ============================================================================

class SimpleAssertion(BaseModel):
    """Version simplifiée pour modèles avec moins de capacité."""
    text: str = Field(..., max_length=300)
    type: str = Field(..., pattern=r"^(definitional|factual|prescriptive|permissive|conditional|causal|procedural|comparative)$")
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., gt=0)
    confidence: float = Field(0.8, ge=0.0, le=1.0)


class SimpleAssertionResponse(BaseModel):
    """Réponse simplifiée pour extraction d'assertions."""
    assertions: List[SimpleAssertion] = Field(default_factory=list, max_length=30)


class SimpleConcept(BaseModel):
    """Version simplifiée pour concept."""
    name: str = Field(..., max_length=40)
    role: str = Field(..., pattern=r"^(CENTRAL|STANDARD|CONTEXTUAL)$")
    theme: str = Field(..., max_length=60)


class SimpleConceptResponse(BaseModel):
    """Réponse simplifiée pour concepts."""
    concepts: List[SimpleConcept] = Field(default_factory=list, max_length=10)


# ============================================================================
# REGISTRY DES SCHEMAS PAR TASK TYPE
# ============================================================================

SCHEMA_REGISTRY = {
    # Phase 1.1
    "document_analysis": DocumentAnalysisResponse,
    "doc_analysis": DocumentAnalysisResponse,

    # Phase 1.2
    "concept_identification": ConceptIdentificationResponse,
    "concept_id": ConceptIdentificationResponse,
    "concepts": ConceptIdentificationResponse,

    # Phase 1.3
    "assertion_extraction": AssertionExtractionResponse,
    "assertions": AssertionExtractionResponse,
    "extract_assertions": AssertionExtractionResponse,

    # Phase 1.3b
    "semantic_linking": SemanticLinkingResponse,
    "linking": SemanticLinkingResponse,
    "links": SemanticLinkingResponse,

    # Simplified versions
    "simple_assertions": SimpleAssertionResponse,
    "simple_concepts": SimpleConceptResponse,
}


def get_schema_by_task(task: str) -> Optional[type]:
    """Retourne le schema Pydantic pour une tâche donnée."""
    return SCHEMA_REGISTRY.get(task)


def parse_with_schema(json_str: str, task: str) -> Optional[BaseModel]:
    """
    Parse une réponse JSON avec validation schema.

    Args:
        json_str: JSON string à parser
        task: Nom de la tâche pour sélectionner le schema

    Returns:
        Instance Pydantic validée ou None si erreur
    """
    import json

    schema_class = get_schema_by_task(task)
    if schema_class is None:
        return None

    try:
        data = json.loads(json_str)
        return schema_class.model_validate(data)
    except (json.JSONDecodeError, Exception) as e:
        import logging
        logging.getLogger(__name__).warning(f"[LLM_SCHEMAS] Parse failed for {task}: {e}")
        return None
