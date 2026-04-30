"""
Pydantic models pour Lifecycle Doc→Doc V2-S1 (version stricte).

Aucun champ `*_score` (cf. VISION_RECENTREE §1bis : pas de score hybride en persistence).
Seul `confidence` du LLM est conservé pour audit (pas pour décision de persistence).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LifecycleType(str, Enum):
    """Trois types Lifecycle Doc→Doc V3.3."""

    SUPERSEDES = "SUPERSEDES"  # doc B abroge/remplace doc A
    EVOLVES_FROM = "EVOLVES_FROM"  # doc B modifie/étend doc A (A reste en vigueur, modifié)
    REAFFIRMS = "REAFFIRMS"  # doc B réaffirme/restate les règles de doc A


class LifecycleDeclarationCandidate(BaseModel):
    """Une déclaration extraite par LLM, en attente de validation."""

    type: LifecycleType
    target_doc_reference: str = Field(
        ...,
        description="Référence textuelle au doc cible, verbatim (ex: 'Regulation (EC) No 428/2009')",
    )
    evidence_quote: str = Field(
        ...,
        description="Phrase verbatim de la déclaration, doit être substring du source text",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: Optional[str] = Field(default=None, description="Bref raisonnement LLM")


class LifecycleExtractionResult(BaseModel):
    """Résultat brut d'une extraction LLM sur un doc source."""

    source_doc_id: str
    declarations: list[LifecycleDeclarationCandidate] = Field(default_factory=list)
    extraction_method: str = "llm_evidence_locked_v2_strict"
    model_id: str
    extracted_at: str  # ISO8601


class ValidationOutcome(str, Enum):
    """Issue de la validation post-LLM."""

    ACCEPTED = "ACCEPTED"  # quote substring + target résolu → persister
    REJECTED_QUOTE_NOT_IN_SOURCE = "REJECTED_QUOTE_NOT_IN_SOURCE"  # hallucination
    REJECTED_TARGET_NOT_RESOLVED = "REJECTED_TARGET_NOT_RESOLVED"  # cible hors corpus
    REJECTED_TARGET_AMBIGUOUS = "REJECTED_TARGET_AMBIGUOUS"  # plusieurs candidats


class ValidatedLifecycleRelation(BaseModel):
    """Une déclaration validée et résolue, prête à persister."""

    source_doc_id: str
    target_doc_id: str
    type: LifecycleType
    evidence_quote: str
    confidence: float
    source_doc_section: Optional[str] = Field(
        default=None, description="section_id ou page_no où la clause apparaît"
    )
    reasoning: Optional[str] = None
    model_id: str
    derivation_path: str = "lifecycle_extractor.v1.evidence_locked"


class ValidationReport(BaseModel):
    """Trace de validation (acceptés + rejetés) pour audit forensics."""

    source_doc_id: str
    accepted: list[ValidatedLifecycleRelation] = Field(default_factory=list)
    rejected: list[dict] = Field(
        default_factory=list,
        description="Liste de {candidate, outcome, reason} pour audit",
    )
