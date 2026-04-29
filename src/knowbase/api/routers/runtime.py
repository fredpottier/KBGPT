"""
R1+R2 — Endpoint API runtime V1.1.

Expose le pipeline complet via POST /api/runtime/query.

Pour V1.1 socle, on supporte les 7 modes mais on focus le test E2E sur :
- LOOKUP_FACTUAL (RAG_LED)
- APPLICABILITY_QUERY (KG_LED)
- CONFLICT_RISK (KG_LED)

Les modes temporels (SNAPSHOT/DIFF) restent fonctionnels mais à calibrer en R3.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from knowbase.api.dependencies import get_tenant_id
from knowbase.runtime.orchestrator import RuntimeOrchestrator
from knowbase.runtime.response_composer import ComposedResponse, EvidenceCitation
from knowbase.runtime.trust_evaluator import TrustScore

logger = logging.getLogger("[OSMOSE] runtime_router")

router = APIRouter(prefix="/runtime", tags=["runtime"])


# ============================================================================
# Pydantic schemas
# ============================================================================

class RuntimeQueryRequest(BaseModel):
    question: str = Field(..., description="Question utilisateur")
    persona: Optional[str] = Field(default=None, description="compliance_officer | explorer | reader")
    synthesize: bool = Field(default=True, description="Si True, appel LLM pour short_answer")


class EvidenceItem(BaseModel):
    claim_id: str
    text: str
    doc_id: str
    publication_date: Optional[str] = None
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    lifecycle_status: Optional[str] = None
    relation_type: Optional[str] = None


class TrustScoreOut(BaseModel):
    score: float
    level: str
    breakdown: dict
    notes: list[str]


class RuntimeQueryResponse(BaseModel):
    short_answer: str
    conditions: list[str]
    business_block: dict
    evidence: list[EvidenceItem]
    confidence: TrustScoreOut
    drill_down: list[dict]
    mode: str
    regime: str
    debug_info: dict


# ============================================================================
# Endpoint
# ============================================================================

# Singleton orchestrator (évite recréation à chaque request)
_orchestrator: Optional[RuntimeOrchestrator] = None


def _get_orchestrator(tenant_id: str) -> RuntimeOrchestrator:
    global _orchestrator
    if _orchestrator is None or _orchestrator.tenant_id != tenant_id:
        if _orchestrator is not None:
            try:
                _orchestrator.close()
            except Exception:
                pass
        _orchestrator = RuntimeOrchestrator(tenant_id=tenant_id)
    return _orchestrator


@router.post("/query", response_model=RuntimeQueryResponse)
async def runtime_query(
    req: RuntimeQueryRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> RuntimeQueryResponse:
    """
    Pipeline runtime V1.1 complet.

    Pipeline :
    1. Resolve persona (R6 — compliance_officer / explorer / reader)
    2. QueryResolver détecte le mode (1 sur 7)
    3. EvidencePlanner choisit le régime (RAG_LED/KG_LED/HYBRID) + applique persona overrides
    4. Retrieval Qdrant + Cypher + TemporalRetriever (R3+R4) + fusion HYBRID (R5)
    5. Auto-escalation RAG_LED → KG_LED si signaux structurels
    6. TrustEvaluator calcule kg_trust (4 niveaux + thresholds persona-aware R6)
    7. Fallback strategy (HARD_ABSTENTION strict / SOFT_RAG_DISCLAIMED permissive)
    8. ResponseComposer compose la réponse en 5 sections + bloc métier modulable
    9. Synthèse LLM short_answer (mode-aware + persona-aware)

    Persona supportés (R6) :
    - compliance_officer : strict, audit trail max, hard abstention si trust < 0.55
    - explorer (default) : permissive, surface contradictions/exceptions
    - reader : concis, executive style, drill-down minimal
    """
    try:
        orch = _get_orchestrator(tenant_id)
        persona_hints = {"persona": req.persona} if req.persona else {}
        composed: ComposedResponse = orch.query(
            question=req.question,
            persona_hints=persona_hints,
            synthesize=req.synthesize,
        )

        return _to_response(composed)
    except Exception as e:
        logger.exception(f"[runtime] query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Runtime query failed: {e}")


def _to_response(composed: ComposedResponse) -> RuntimeQueryResponse:
    return RuntimeQueryResponse(
        short_answer=composed.short_answer,
        conditions=composed.conditions,
        business_block=composed.business_block,
        evidence=[
            EvidenceItem(
                claim_id=e.claim_id,
                text=e.text,
                doc_id=e.doc_id,
                publication_date=e.publication_date,
                validity_start=e.validity_start,
                validity_end=e.validity_end,
                lifecycle_status=e.lifecycle_status,
                relation_type=e.relation_type,
            )
            for e in composed.evidence
        ],
        confidence=TrustScoreOut(
            score=composed.confidence.score if composed.confidence else 0.0,
            level=composed.confidence.level.value if composed.confidence else "FALLBACK",
            breakdown=composed.confidence.breakdown if composed.confidence else {},
            notes=composed.confidence.notes if composed.confidence else [],
        ),
        drill_down=composed.drill_down,
        mode=composed.mode.value if composed.mode else "UNKNOWN",
        regime=composed.regime or "UNKNOWN",
        debug_info=composed.debug_info,
    )


__all__ = ["router"]
