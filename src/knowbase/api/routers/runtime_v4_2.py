"""Router API Runtime V4.2 — Tiered Pipeline production (CH-49 Phase 1).

Endpoint POST /api/runtime_v4_2/answer
Endpoint GET  /api/runtime_v4_2/health
Endpoint GET  /api/runtime_v4_2/telemetry/today

Phase 1 : Layer 0 Cheap Certainty + temporal_active_op (Cap2.A) + Q↔A Verifier prod.
Phase 2 : ajoutera lifecycle_resolution_op, kg_query_op, set_reasoning_op (Cap2.B/C/D).
Phase 3 : ajoutera Adaptive Orchestrator (Cap3, Layer 2).

Schema réponse compatible V3/V4 pour benchmarks Robust/T2T5/RAGAS.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

from knowbase.common.clients.shared_clients import (
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from knowbase.facts_first import EvidenceCollector
from knowbase.runtime_v3.llm_client import get_runtime_llm_client
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.runtime_v4_2 import telemetry
from knowbase.runtime_v4_2.intent_router import UnifiedIntentRouter
from knowbase.runtime_v4_2.layer2_orchestrator import Layer2Orchestrator
from knowbase.runtime_v4_2.operators import (
    KGQueryOperator,
    LifecycleResolutionOperator,
    SetReasoningOperator,
    TemporalActiveVersionOperator,
)
from knowbase.runtime_v4_2.pipeline import Layer0Pipeline
from knowbase.runtime_v4_2.qa_alignment_verifier import QAAlignmentVerifier
from knowbase.runtime_v4_2.tools import ToolRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime_v4_2", tags=["runtime_v4_2"])


class V42AnswerRequest(BaseModel):
    question: str = Field(..., min_length=2)
    top_k_claims: int = Field(12, ge=1, le=30)


class V42AnswerResponse(BaseModel):
    """Schema réponse V4.2 — superset compatible V4 pour benchs."""

    question: str
    decision: str  # ANSWER | ABSTAIN
    answer: str
    layer: str  # layer0 | layer1_temporal_active | (futur: layer2)
    abstention_reason: Optional[str] = None
    abstain_category: Optional[str] = None
    qa_alignment: Optional[str] = None
    qa_reason: Optional[str] = None
    qa_confidence: Optional[float] = None
    n_chunks_used: int = 0
    doc_ids_cited: list[str] = []
    escalation_reason: str = "none"
    used_unified_prompt: bool = False
    latency_breakdown_ms: dict = {}
    # Compat V3/V4 pour bench RAGAS (chunks_used pour contexts)
    chunks_used: list[dict] = []


_pipeline: Optional[Layer0Pipeline] = None


def _get_pipeline() -> Layer0Pipeline:
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    settings = get_settings()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(
        settings.embeddings_model, cache_folder=str(settings.hf_home)
    )

    retriever = ClaimRetriever(
        qdrant_client=qdrant, embedder=embedder, driver=driver,
        collection_name="knowbase_chunks_v2", tenant_id=tenant_id,
    )
    evidence_collector = EvidenceCollector(
        retriever=retriever, neo4j_driver=driver, tenant_id=tenant_id, top_k=20,
    )

    qa_verifier = QAAlignmentVerifier()
    temporal_op = TemporalActiveVersionOperator(
        neo4j_driver=driver,
        tenant_id=tenant_id,
        evidence_collector=evidence_collector,
    )
    lifecycle_op = LifecycleResolutionOperator(
        neo4j_driver=driver,
        tenant_id=tenant_id,
        evidence_collector=evidence_collector,
    )
    kg_query_op = KGQueryOperator(
        neo4j_driver=driver,
        tenant_id=tenant_id,
    )
    llm_client = get_runtime_llm_client()
    set_reasoning_op = SetReasoningOperator(
        evidence_collector=evidence_collector,
        llm_client=llm_client,
    )

    # Unified Intent Router (Optim Phase 4) — opt-in via env, default ON
    intent_router = None
    if os.getenv("RUNTIME_V4_2_INTENT_ROUTER", "true").lower() == "true":
        intent_router = UnifiedIntentRouter()

    # Layer 2 orchestrator (Cap3) — opt-in via env (peut être lourd en latence)
    layer2_orchestrator = None
    if os.getenv("RUNTIME_V4_2_LAYER2", "true").lower() == "true":
        tool_registry = ToolRegistry(
            evidence_collector=evidence_collector,
            llm_client=llm_client,
            temporal_active_op=temporal_op,
            lifecycle_resolution_op=lifecycle_op,
            kg_query_op=kg_query_op,
            set_reasoning_op=set_reasoning_op,
        )
        layer2_orchestrator = Layer2Orchestrator(tool_registry=tool_registry)

    _pipeline = Layer0Pipeline(
        evidence_collector=evidence_collector,
        llm_client=llm_client,
        qa_verifier=qa_verifier,
        temporal_active_op=temporal_op,
        lifecycle_resolution_op=lifecycle_op,
        kg_query_op=kg_query_op,
        set_reasoning_op=set_reasoning_op,
        layer2_orchestrator=layer2_orchestrator,
        intent_router=intent_router,
        enable_telemetry=os.getenv("RUNTIME_V4_2_TELEMETRY", "true").lower() == "true",
    )
    logger.info(
        "Runtime V4.2 pipeline initialized "
        "(verifier=%s, intent_router=%s, temporal_op=on, lifecycle_op=on, kg_query_op=on, set_reasoning_op=on, "
        "layer2=%s, unified_prompt=%s, telemetry=%s)",
        qa_verifier.model,
        intent_router is not None,
        layer2_orchestrator is not None,
        _pipeline.unified_prompt_enabled,
        _pipeline.enable_telemetry,
    )
    return _pipeline


@router.get("/health")
def health() -> dict:
    pipeline = _get_pipeline()
    return {
        "status": "ok",
        "version": "v4_2_tiered",
        "pipeline_loaded": pipeline is not None,
        "phase": "1",
        "layers": {
            "layer0": "cheap_certainty + qa_verifier",
            "layer1": [
                "temporal_active_version (Cap2.A)",
                "lifecycle_resolution (Cap2.B)",
                "kg_query (Cap2.C)",
                "set_reasoning (Cap2.D)",
            ],
            "layer2": (
                "adaptive_orchestrator DeepSeek-V3.1 (Cap3)"
                if pipeline.layer2_orchestrator is not None else "disabled"
            ),
        },
        "config": {
            "verifier_model": pipeline.qa_verifier.model,
            "verifier_has_together_key": bool(pipeline.qa_verifier.together_key),
            "verifier_has_deepinfra_key": bool(pipeline.qa_verifier.deepinfra_key),
            "unified_prompt_enabled": pipeline.unified_prompt_enabled,
            "telemetry_enabled": pipeline.enable_telemetry,
        },
    }


@router.get("/telemetry/today")
def telemetry_today() -> dict:
    """Agrégation traces du jour pour dashboard ops."""
    return telemetry.daily_aggregate()


@router.post("/answer", response_model=V42AnswerResponse)
def answer(request: V42AnswerRequest) -> V42AnswerResponse:
    pipeline = _get_pipeline()
    r = pipeline.answer(request.question, top_k_claims=request.top_k_claims)

    # Pour compat bench RAGAS contexts : extract chunks_used (best-effort)
    chunks_used: list[dict] = []
    # On ne réexpose pas les claims internes pour Layer 0 (réponse extractive courte) —
    # les benchs RAGAS doivent passer par /api/runtime_v4/answer pour contexts complets.

    return V42AnswerResponse(
        question=r.question,
        decision=r.decision,
        answer=r.answer,
        layer=r.layer,
        abstention_reason=r.abstention_reason,
        abstain_category=r.abstain_category.value if r.abstain_category else None,
        qa_alignment=r.qa_alignment,
        qa_reason=r.qa_reason,
        qa_confidence=r.qa_confidence,
        n_chunks_used=r.n_chunks_used,
        doc_ids_cited=r.doc_ids_cited or [],
        escalation_reason=r.escalation_reason.value if r.escalation_reason else "none",
        used_unified_prompt=r.used_unified_prompt,
        latency_breakdown_ms=r.latency_breakdown_ms or {},
        chunks_used=chunks_used,
    )
