"""Runtime V6 API — endpoint /api/runtime_v6/answer (parallèle V5.1).

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1-§2.5 + §2.9.

Pipeline orchestré Parse → Plan → Execute → Evaluate → Synthesize avec :
    - Boucle re-plan (max 2 iter)
    - 6 hints de re-plan applicables (cf §2.4)
    - Hard caps wall-clock (60s)
    - Trace structurée par itération

Endpoint synchrone simple — pas d'admission control / SSE async (CH-52.6 V5
spécifique, hors scope V6). La latence est bornée par les hard caps.

Domain-agnostic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from knowbase.runtime_a3.orchestrator import (
    MAX_ITERATIONS,
    MAX_WALL_CLOCK_S,
    Orchestrator,
    OrchestratorResult,
)
from knowbase.runtime_a3.schemas import (
    CitedClaim,
    ResponseMode,
    SynthesizeMode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime_v6", tags=["runtime_v6"])


# ============================================================================
# Request / Response models
# ============================================================================


class RuntimeV6Request(BaseModel):
    """Input pour POST /api/runtime_v6/answer."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Question utilisateur en langage naturel.",
    )
    tenant_id: str = Field(
        default="default",
        min_length=1,
        description="Tenant ID multi-tenant.",
    )
    as_of_date: Optional[datetime] = Field(
        default=None,
        description=(
            "Date point-in-time pour queries historiques (filtre bitemporel). "
            "Si None : now() UTC."
        ),
    )
    response_mode: ResponseMode = Field(
        default="structured",
        description="Style de réponse souhaité.",
    )
    include_trace: bool = Field(
        default=True,
        description=(
            "Si True, inclut la trace structurée par itération dans la réponse "
            "(utile pour debug et bench A3.8). Mettre à False en production "
            "client-facing pour réponses plus compactes."
        ),
    )
    use_kg: bool = Field(
        default=True,
        description=(
            "Si False, court-circuite le runtime KG-first et répond via le "
            "pipeline RAG classique (Qdrant top-K chunks + synthèse directe, "
            "même bras que le bench comparatif). Toggle A/B du chat : permet "
            "de mesurer ce que le Knowledge Graph apporte à la réponse."
        ),
    )


class CitedClaimRef(BaseModel):
    """Référence claim pour la réponse API (lecture seule)."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_verbatim: str
    doc_title: Optional[str] = None
    section_id: Optional[str] = None
    page: Optional[int] = None


class IterationTraceDict(BaseModel):
    """Trace d'une itération (sérialisé pour l'API)."""

    model_config = ConfigDict(extra="allow")

    iteration: int
    duration_s: float
    n_sub_goals: int
    n_tool_calls: int
    n_unmappable: int
    n_results: int
    verdict: str
    re_plan_hint: str
    re_plan_hint_applied: Optional[str] = None
    covered_sub_goals: List[int] = Field(default_factory=list)
    uncovered_sub_goals: List[int] = Field(default_factory=list)
    evaluate_confidence: float = 0.0
    evaluate_reasoning: str = ""


class RuntimeV6Response(BaseModel):
    """Output de POST /api/runtime_v6/answer."""

    model_config = ConfigDict(extra="forbid")

    # Réponse principale
    answer_text: str = Field(..., description="Réponse rédigée avec citations inline.")
    cited_claims: List[CitedClaimRef] = Field(
        default_factory=list,
        description="Sources mobilisées (click-to-source UI).",
    )
    mode: SynthesizeMode = Field(..., description="Mode terminal (cf VISION §4.5).")

    # Transparence
    uncovered_sub_goals_warning: Optional[str] = Field(default=None)
    conflict_pending_warning: Optional[str] = Field(default=None)
    authority_divergence_warning: Optional[str] = Field(
        default=None,
        description=(
            "Divergence RÉELLE entre autorités réglementaires (les équivalences "
            "d'unités sont exclues) — signal structuré pour picto/bandeau UI."
        ),
    )
    synthesize_warnings: List[str] = Field(default_factory=list)
    citation_coverage_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Métadonnées d'exécution
    total_duration_s: float
    n_iterations: int
    terminated_reason: str
    iterations_trace: Optional[List[IterationTraceDict]] = Field(
        default=None,
        description="Trace par itération si include_trace=True dans la requête.",
    )

    # Versioning
    runtime_version: str = "a3.0"
    schema_version: str = "a3.0"


class RuntimeV6Health(BaseModel):
    """Health check status."""

    model_config = ConfigDict(extra="forbid")

    status: str
    runtime_version: str
    max_iterations: int
    max_wall_clock_s: float


# ============================================================================
# Singleton orchestrator (lazy init)
# ============================================================================


_orchestrator_instance: Optional[Orchestrator] = None


def _get_orchestrator() -> Orchestrator:
    """Lazy singleton (Parser, Executor, Evaluator, Synthesizer en mode prod)."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = Orchestrator()
    return _orchestrator_instance


def reset_orchestrator() -> None:
    """Reset du singleton (utile en tests + après reload config)."""
    global _orchestrator_instance
    _orchestrator_instance = None


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/health", response_model=RuntimeV6Health)
async def health() -> RuntimeV6Health:
    """Health check du runtime V6."""
    return RuntimeV6Health(
        status="ok",
        runtime_version="a3.0",
        max_iterations=MAX_ITERATIONS,
        max_wall_clock_s=MAX_WALL_CLOCK_S,
    )


@router.post("/answer", response_model=RuntimeV6Response)
async def answer(request: RuntimeV6Request) -> RuntimeV6Response:
    """Pipeline Parse → Plan → Execute → Evaluate → Synthesize (synchrone).

    Boucle re-plan max 2 iterations, hard cap wall-clock 60s. Trace structurée
    optionnelle (include_trace=True).

    `use_kg=false` → court-circuit RAG classique (toggle A/B du chat, 05/06) :
    le flag du frontend était ignoré depuis le branchement du chat sur
    runtime_a3 (31/05) — le KG était utilisé même toggle éteint.
    """
    if not request.use_kg:
        return _answer_classic_rag(request)
    try:
        orch = _get_orchestrator()
        result: OrchestratorResult = orch.run(
            question=request.question,
            tenant_id=request.tenant_id,
            as_of_date=request.as_of_date,
            response_mode=request.response_mode,
        )
    except Exception as exc:
        logger.exception("runtime_v6/answer: orchestrator raised")
        raise HTTPException(
            status_code=500,
            detail=f"Orchestrator error: {str(exc)[:300]}",
        )

    return _build_response(result, include_trace=request.include_trace)


# ============================================================================
# Bras RAG classique (toggle A/B — use_kg=false)
# ============================================================================

_classic_rag_instance = None


def _get_classic_rag():
    global _classic_rag_instance
    if _classic_rag_instance is None:
        from knowbase.runtime_a3.classic_rag import ClassicRAG
        _classic_rag_instance = ClassicRAG()
    return _classic_rag_instance


def _answer_classic_rag(request: RuntimeV6Request) -> RuntimeV6Response:
    """Réponse RAG vanille (Qdrant top-K chunks + synthèse directe, sans KG)."""
    try:
        out = _get_classic_rag().answer(
            question=request.question,
            tenant_id=request.tenant_id,
        )
    except Exception as exc:
        logger.exception("runtime_v6/answer: classic_rag raised")
        raise HTTPException(
            status_code=500,
            detail=f"ClassicRAG error: {str(exc)[:300]}",
        )
    return RuntimeV6Response(
        answer_text=out.get("answer_text") or "(pas de réponse)",
        cited_claims=[],  # pas de claims KG — citations [Source N] inline
        mode=out.get("mode") if out.get("mode") in ("REASONED", "ANCHORED", "TEXT_ONLY", "ABSTENTION") else "TEXT_ONLY",
        synthesize_warnings=["classic_rag_no_kg"],
        citation_coverage_rate=None,
        total_duration_s=out.get("duration_s") or 0.0,
        n_iterations=1,
        terminated_reason="classic_rag",
        iterations_trace=None,
        runtime_version="classic_rag",
        schema_version="a3.0",
    )


# ============================================================================
# Mapping interne → schema API
# ============================================================================


def _build_response(
    result: OrchestratorResult,
    include_trace: bool,
) -> RuntimeV6Response:
    synth = result.synthesize_output

    cited_refs = [
        CitedClaimRef(
            claim_id=cc.claim_id,
            claim_verbatim=cc.claim_verbatim,
            doc_title=cc.doc_title,
            section_id=cc.section_id,
            page=cc.page,
        )
        for cc in synth.cited_claims
    ]

    trace_payload: Optional[List[IterationTraceDict]] = None
    if include_trace:
        trace_payload = [
            IterationTraceDict(**it.to_dict()) for it in result.iterations
        ]

    return RuntimeV6Response(
        answer_text=synth.answer_text,
        cited_claims=cited_refs,
        mode=synth.mode,
        uncovered_sub_goals_warning=synth.uncovered_sub_goals_warning,
        conflict_pending_warning=synth.conflict_pending_warning,
        authority_divergence_warning=getattr(synth, "authority_divergence_warning", None),
        synthesize_warnings=synth.synthesize_warnings,
        citation_coverage_rate=synth.citation_coverage_rate,
        total_duration_s=result.total_duration_s,
        n_iterations=len(result.iterations),
        terminated_reason=result.terminated_reason,
        iterations_trace=trace_payload,
        runtime_version="a3.0",
        schema_version="a3.0",
    )
