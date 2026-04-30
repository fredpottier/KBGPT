"""
Pydantic models pour Runtime V2 — Pipeline anchor-driven.

Réponse structurée minimale, domain-agnostic. Pas de "5 sections obligatoires"
de Runtime V1.1 (qui supposait 7 modes). Réponse plat avec sections optionnelles
selon le résultat des étapes du pipeline.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from knowbase.anchor.models import AnchorType, ResolvedAnchor


class PipelineDecision(str, Enum):
    """Décision globale du pipeline pour une question."""

    ANSWERED_AUTHORITATIVE = "answered_authoritative"  # 1 doc autoritaire identifié, claims retournés
    ANSWERED_SCOPED = "answered_scoped"  # POINT explicite, scope identifié
    ANSWERED_EVOLUTION = "answered_evolution"  # RANGE — timeline construite
    ESCALATE_AMBIGUOUS = "escalate_ambiguous"  # Current Resolver < 0.55
    ESCALATE_NO_DOCS = "escalate_no_docs"  # Anchor Filter retourne 0
    NOT_FOUND = "not_found"  # Aucun claim pertinent
    AUDIT_REPORT = "audit_report"  # Mode Audit → liste contradictions


class EvidenceClaim(BaseModel):
    """Un claim qui contribue à la réponse."""

    claim_id: str
    doc_id: str
    text: str
    score: float = 0.0
    publication_date: Optional[str] = None


class ConflictReport(BaseModel):
    """Une contradiction intra-anchor détectée (mode Audit)."""

    claim_a_id: str
    claim_b_id: str
    doc_a_id: str
    doc_b_id: str
    confidence: float
    reasoning: Optional[str] = None
    is_resolved_by_lifecycle: bool = False  # True si LIFECYCLE_RELATION résout
    lifecycle_resolution_type: Optional[str] = None  # SUPERSEDES/EVOLVES_FROM si résolu


class EvolutionPoint(BaseModel):
    """Un point de la timeline pour anchor=range."""

    doc_id: str
    publication_date: Optional[str] = None
    claims: list[EvidenceClaim] = Field(default_factory=list)


class PipelineResponse(BaseModel):
    """Sortie du pipeline V2.

    Le frontend rend la réponse selon `decision` + sections présentes :
    - ANSWERED_* → claims + (suggestions si SUGGEST_WITH_ALTERNATIVES)
    - ANSWERED_EVOLUTION → timeline (evolution_points)
    - ESCALATE_* → escalation_message + alternatives
    - AUDIT_REPORT → conflicts
    """

    decision: PipelineDecision
    question: str
    anchor: ResolvedAnchor

    # Si décision = ANSWERED_AUTHORITATIVE / ANSWERED_SCOPED
    authoritative_doc_ids: list[str] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)

    # Si décision = ANSWERED_EVOLUTION
    evolution_points: list[EvolutionPoint] = Field(default_factory=list)

    # Si décision contient ESCALATE_*
    escalation_message: Optional[str] = None
    alternatives: list[dict] = Field(default_factory=list)

    # Si mode Audit ou anchor=POINT/CURRENT avec conflicts détectés
    conflicts: list[ConflictReport] = Field(default_factory=list)

    # Trust score global (composite des phases)
    trust_score: float = 0.0
    trust_breakdown: dict = Field(default_factory=dict)

    # Synthèse LLM (V2-P2.1) — réponse en prose en langue de la question
    synthesized_answer: Optional[str] = None

    # Diagnostics pour debug/audit
    diagnostic: dict[str, Any] = Field(default_factory=dict)
