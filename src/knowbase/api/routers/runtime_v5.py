"""V5 Reading Agent API router (mount dans api/main.py).

Wire les composants V5.1 production avec dependencies singleton :
- AdmissionController (in-memory, charte OSMOSIS rate/concurrency)
- IdempotencyStore (in-memory backend, Redis-backed différé)
- InMemoryJobStore (jobs async)
- HTTPLLMCaller (Together AI + DeepInfra fallback)
- ReasoningAgentV51 (orchestrateur agent)

Endpoint exposés :
- POST /api/runtime_v5/answer → 202 + request_id (Mode B async)
- GET  /api/runtime_v5/answer/{request_id} → status + partial + result
- POST /api/runtime_v5/answer/{request_id}/cancel
- POST /api/runtime_v5/answer/stream → text/event-stream (Mode A, partial)

Note SSE : pour V5.1 minimal, l'endpoint stream émet un seul event 'complete'
avec la réponse finale. Streaming au fil de l'eau (plan/tool_call/section_read
events) sera ajouté en S9 (frontend chat hooks).
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import APIRouter

from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.api.admission import (
    AdmissionConfig,
    AdmissionController,
)
from knowbase.runtime_v5.api.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyBackend,
)
from knowbase.runtime_v5.api.job_store import InMemoryJobStore
from knowbase.runtime_v5.api.models import (
    AnswerRequest,
    AnswerResponse,
    CitationRef,
    EpistemicStatusAPI,
    ResponseMetrics,
    SSEEventType,
)
from knowbase.runtime_v5.api.router import JobRunner, create_router
from knowbase.runtime_v5.api.sse import StreamingJobRunner, create_sse_router
from knowbase.runtime_v5.agent.workspace import EpistemicStatus
from knowbase.runtime_v5.http_llm_caller import HTTPLLMCaller
from knowbase.runtime_v5.reasoning_agent_v51 import ReasoningAgentV51
from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import (
    ToolRegistry,
    get_default_registry,
    reset_default_registry,
)
from knowbase.runtime_v5.tools.v2_tools_registration import register_v2_tools
from knowbase.runtime_v5.tools.v6_tools_registration import register_v6_tools

logger = logging.getLogger(__name__)


# ─── Singleton dependencies (process-level) ──────────────────────────────────


_admission: AdmissionController | None = None
_idempotency: IdempotencyStore | None = None
_job_store: InMemoryJobStore | None = None
_agent: ReasoningAgentV51 | None = None

# Cache d'agents par model (pour bake-off bench parallèle)
# Évite de recréer un agent à chaque request quand on bench plusieurs modèles
_agents_by_model: dict[str, ReasoningAgentV51] = {}


def _get_admission() -> AdmissionController:
    global _admission
    if _admission is None:
        _admission = AdmissionController(config=AdmissionConfig())
    return _admission


def _get_idempotency() -> IdempotencyStore:
    global _idempotency
    if _idempotency is None:
        _idempotency = IdempotencyStore(backend=InMemoryIdempotencyBackend())
    return _idempotency


def _get_job_store() -> InMemoryJobStore:
    global _job_store
    if _job_store is None:
        _job_store = InMemoryJobStore()
    return _job_store


def _get_agent() -> ReasoningAgentV51:
    """Singleton agent : init registry (POC + V2 tools) + HTTPLLMCaller +
    optional GroundingVerifier (S7.7 Mode A passive)."""
    global _agent
    if _agent is None:
        import os
        import threading as _threading
        # Re-init registry pour s'assurer que tous les tools sont enregistrés
        reset_default_registry()
        registry = get_default_registry()
        register_poc_tools(registry)
        register_v2_tools(registry)
        # V6-J1 — find_procedures (additif, expose les Procedure Neo4j à l'agent).
        # Nécessite que l'extraction V6-J1 ait été lancée (v6_j1_extract_corpus.py).
        register_v6_tools(registry)

        # LLM caller — switch via env V5_LLM_PROVIDER (calibration uniquement)
        # Default = Together AI / DeepInfra (charte open-source serverless).
        # 'anthropic' = bench calibration plafond (Claude Sonnet/Opus), HORS production.
        provider = os.getenv("V5_LLM_PROVIDER", "open").lower()
        if provider == "anthropic":
            from knowbase.runtime_v5.anthropic_llm_caller import AnthropicLLMCaller
            anthropic_model = os.getenv("V5_LLM_MODEL", "claude-sonnet-4-6")
            llm = AnthropicLLMCaller(model=anthropic_model)
            logger.info(
                f"[V5 Router] ⚠️ Anthropic LLM caller ({anthropic_model}) — "
                f"calibration bench ONLY, hors charte runtime"
            )
        else:
            # V5_LLM_MODEL permet le bake-off de modèles open-source serverless
            # (DeepSeek-V3.1, Llama-3.3-70B, Qwen2.5-72B, Mistral-Small, Qwen-14B, ...).
            # Default = DeepSeek-V3.1 (charte historique).
            open_model = os.getenv("V5_LLM_MODEL", "deepseek-ai/DeepSeek-V3.1")
            llm = HTTPLLMCaller(model=open_model)
            logger.info(f"[V5 Router] HTTPLLMCaller (model={open_model})")

        # A8 prewarm find_in caches en background (TF-IDF + embeddings)
        # Évite la latence 20s du premier find_in() en production
        def _prewarm():
            try:
                from knowbase.runtime_v5.reading_tools import prewarm_find_in_caches
                prewarm_find_in_caches()
            except Exception as exc:
                logger.warning("[V5 Router] prewarm find_in failed: %s", exc)
        _threading.Thread(target=_prewarm, daemon=True, name="v5-prewarm").start()
        logger.info("[V5 Router] find_in prewarm started in background thread")

        # S7.7 Mode A : verifier passif (mesure outcome, ne modifie pas answer)
        verifier = None
        if os.getenv("V5_VERIFIER_ENABLED", "0") in ("1", "true", "True"):
            try:
                from knowbase.runtime_v5.verifier.backends import HHEMBackend
                from knowbase.runtime_v5.verifier.grounding_verifier import (
                    GroundingVerifier,
                )
                backend = HHEMBackend()
                verifier = GroundingVerifier(backend=backend)
                logger.info("[V5 Router] Verifier ENABLED (HHEM-2.1 Mode A passive)")
            except Exception as exc:
                logger.warning("[V5 Router] verifier setup failed: %s", exc)

        _agent = ReasoningAgentV51(
            llm_caller=llm,
            registry=registry,
            verifier=verifier,
        )
        logger.info(
            f"[V5 Router] Agent initialized — registry stats: {registry.stats()}"
        )
    return _agent


def _get_agent_for_model(llm_model: str) -> ReasoningAgentV51:
    """Retourne (ou crée) un agent V5.1 dédié à un modèle LLM spécifique.

    Usage : bench bake-off LLM en parallèle. Le default `_get_agent()` reste
    pour les requests sans override (production).

    L'agent ad-hoc partage registry/tracer/metrics/verifier avec le default
    pour économiser les ressources ; seul le LLMCaller est dédié.

    Support vLLM self-hosted : si llm_model == V5_VLLM_MODEL (env var),
    utilise V5_VLLM_URL comme endpoint (au lieu de DeepInfra/Together).
    """
    import os
    global _agents_by_model
    if llm_model in _agents_by_model:
        return _agents_by_model[llm_model]
    # S'assure que le default est initialisé pour pouvoir partager ses deps
    default = _get_agent()

    # Détection vLLM self-hosted via env var (bench Qwen-14B AWQ EC2)
    vllm_model = os.getenv("V5_VLLM_MODEL", "").strip()
    vllm_url = os.getenv("V5_VLLM_URL", "").strip()
    if vllm_model and vllm_url and llm_model == vllm_model:
        custom_llm = HTTPLLMCaller(model=llm_model, endpoint_url=vllm_url)
        logger.info(f"[V5 Router] vLLM custom agent : model={llm_model} url={vllm_url}")
    else:
        custom_llm = HTTPLLMCaller(model=llm_model)
        logger.info(f"[V5 Router] Created custom agent for model={llm_model}")

    custom_agent = ReasoningAgentV51(
        llm_caller=custom_llm,
        registry=default.registry,
        sanitizer=default.sanitizer,
        max_message_history=default.max_message_history,
        tracer=default.tracer,
        metrics=default.metrics,
        verifier=default.verifier,
    )
    _agents_by_model[llm_model] = custom_agent
    return custom_agent


# ─── JobRunner adapter (wraps agent for endpoint) ────────────────────────────


class V51JobRunner(JobRunner):
    """JobRunner production wrap ReasoningAgentV51."""

    async def execute(
        self,
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        cancellation_token: CancellationToken,
    ) -> AnswerResponse:
        # Si llm_model override fourni (bench bake-off), créer agent ad-hoc
        # avec un HTTPLLMCaller spécifique pour cette request.
        if getattr(request, "llm_model", None):
            agent = _get_agent_for_model(request.llm_model)
        else:
            agent = _get_agent()
        result = await agent.run_async(
            question=request.question,
            tenant_id=tenant_id,
            answer_shape=request.answer_shape_hint,
            cancellation=cancellation_token,
        )
        # Convert workspace → API response
        return _result_to_api_response(result, request_id)


class V51StreamingRunner(StreamingJobRunner):
    """SSE streaming runner minimal V5.1 : émet plan + tool_calls + complete.

    Pour V5.1 minimal, on n'a pas encore les hooks fil-de-l'eau dans le pipeline
    (S9 frontend). On émet donc complete final à partir du workspace post-run.
    """

    async def stream(
        self,
        request_id: str,
        tenant_id: str,
        request: AnswerRequest,
        cancellation_token: CancellationToken,
    ) -> AsyncIterator[tuple[SSEEventType, dict]]:
        agent = _get_agent()
        result = await agent.run_async(
            question=request.question,
            tenant_id=tenant_id,
            answer_shape=request.answer_shape_hint,
            cancellation=cancellation_token,
        )
        # Émet les tool_calls collectés a posteriori (pas streaming réel)
        for tc in result.workspace.tool_calls:
            yield SSEEventType.TOOL_CALL, {
                "iter": tc.iter_idx,
                "tool": tc.tool_name,
                "args": tc.args,
                "evidence_gain": 0.0,  # not tracked at this granularity yet
            }
        # Émet complete avec la réponse finale
        api_resp = _result_to_api_response(result, request_id)
        yield SSEEventType.COMPLETE, api_resp.model_dump(mode="json")


def _result_to_api_response(result, request_id: str) -> AnswerResponse:
    """Convertit AgentRunResult en AnswerResponse API."""
    # Map epistemic_status workspace → API enum
    status_map = {
        EpistemicStatus.COMPLETE: EpistemicStatusAPI.SUPPORTED,
        EpistemicStatus.PARTIAL: EpistemicStatusAPI.PARTIAL,
        EpistemicStatus.ABSTAIN: EpistemicStatusAPI.UNANSWERABLE,
        EpistemicStatus.ABORTED: EpistemicStatusAPI.LOW_CONFIDENCE,
    }
    status_api = status_map.get(result.epistemic_status, EpistemicStatusAPI.PARTIAL)

    # Extract citations from evidence_collected
    citations: list[CitationRef] = []
    seen = set()
    for ev in result.workspace.evidence_collected:
        key = (ev.doc_id, ev.section_id)
        if key in seen:
            continue
        seen.add(key)
        citations.append(CitationRef(
            doc_id=ev.doc_id,
            section_id=ev.section_id,
        ))

    # Metrics from budget snapshot
    ws_sum = result.workspace.summary()
    metrics = ResponseMetrics(
        n_iterations=result.workspace.budgets_snapshot.iterations,
        n_tool_calls=result.workspace.budgets_snapshot.tool_calls,
        n_evidence_items=ws_sum["n_evidence_items"],
        n_repairs=ws_sum["n_repairs"],
        retrieved_chars=result.workspace.budgets_snapshot.retrieved_chars,
        output_tokens=result.workspace.budgets_snapshot.output_tokens,
        latency_s=result.latency_s,
    )

    return AnswerResponse(
        request_id=request_id,
        answer=result.answer,
        citations=citations,
        epistemic_status=status_api,
        stop_reason=result.stop_reason,
        workspace_url=f"/admin/workspaces/{request_id}",
        metrics=metrics,
        verifier_report=getattr(result, "verifier_report", None),
    )


# ─── Build router (called once at app startup) ──────────────────────────────


def build_v5_router() -> APIRouter:
    """Crée le router V5 prêt-à-mounter dans api/main.py.

    Combine endpoints async (POST/GET/CANCEL) + SSE streaming.
    """
    admission = _get_admission()
    idempotency = _get_idempotency()
    job_store = _get_job_store()

    job_runner = V51JobRunner()
    streaming_runner = V51StreamingRunner()

    # Router async (POST/GET/CANCEL)
    async_router = create_router(
        admission=admission,
        idempotency=idempotency,
        job_store=job_store,
        job_runner=job_runner,
    )
    # Router SSE (POST /answer/stream)
    sse_router = create_sse_router(
        admission=admission,
        streaming_runner=streaming_runner,
    )

    # Combine in a single APIRouter (parent)
    combined = APIRouter()
    combined.include_router(async_router)
    combined.include_router(sse_router)
    return combined


# Exposed for main.py
router = build_v5_router()
