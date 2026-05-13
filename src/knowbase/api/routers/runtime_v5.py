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

logger = logging.getLogger(__name__)


# ─── Singleton dependencies (process-level) ──────────────────────────────────


_admission: AdmissionController | None = None
_idempotency: IdempotencyStore | None = None
_job_store: InMemoryJobStore | None = None
_agent: ReasoningAgentV51 | None = None


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
    """Singleton agent : init registry (POC + V2 tools) + HTTPLLMCaller."""
    global _agent
    if _agent is None:
        # Re-init registry pour s'assurer que tous les tools sont enregistrés
        reset_default_registry()
        registry = get_default_registry()
        register_poc_tools(registry)
        register_v2_tools(registry)
        llm = HTTPLLMCaller(model="deepseek-ai/DeepSeek-V3.1")
        _agent = ReasoningAgentV51(
            llm_caller=llm,
            registry=registry,
        )
        logger.info(
            f"[V5 Router] Agent initialized — registry stats: {registry.stats()}"
        )
    return _agent


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
