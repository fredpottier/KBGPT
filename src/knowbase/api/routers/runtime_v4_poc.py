"""Router API Runtime V4 POC — Tiered Architecture validation (CH-49.POC).

Endpoint POST /api/runtime_v4_poc/answer
Endpoint GET  /api/runtime_v4_poc/health

POC minimal Layer 0 (Cheap Certainty + Q↔A Alignment Verifier).
Phase 1.A : pas d'operator, juste retrieval + extraction + Q↔A check.
Phase 1.B : ajout temporal_active_version operator.
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
from knowbase.runtime_v4_poc.layer0_pipeline import Layer0Pipeline, Layer0Response
from knowbase.runtime_v4_poc.qa_alignment_verifier import QAAlignmentVerifier
from knowbase.runtime_v4_poc.operators import TemporalActiveVersionOperator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime_v4_poc", tags=["runtime_v4_poc"])


class POCRequest(BaseModel):
    question: str = Field(..., min_length=2)
    top_k_claims: int = Field(12, ge=1, le=30)


class POCResponse(BaseModel):
    question: str
    decision: str
    answer: str
    layer: str = "layer0"  # layer0 | layer1_temporal_active
    abstention_reason: Optional[str] = None
    qa_alignment: Optional[str] = None
    qa_reason: Optional[str] = None
    n_chunks_used: int = 0
    doc_ids_cited: list[str] = []
    latency_breakdown_ms: dict = {}


_layer0: Optional[Layer0Pipeline] = None


def _get_layer0() -> Layer0Pipeline:
    global _layer0
    if _layer0 is not None:
        return _layer0

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

    llm_client = get_runtime_llm_client()
    qa_verifier = QAAlignmentVerifier()  # DeepSeek-V3.1
    temporal_op = TemporalActiveVersionOperator(
        neo4j_driver=driver, tenant_id=tenant_id, evidence_collector=evidence_collector,
    )

    _layer0 = Layer0Pipeline(
        evidence_collector=evidence_collector,
        llm_client=llm_client,
        qa_verifier=qa_verifier,
        temporal_active_op=temporal_op,
    )
    logger.info(
        "Runtime V4 POC pipeline initialized (verifier=%s, temporal_op=on)",
        qa_verifier.model,
    )
    return _layer0


@router.get("/health")
def health():
    layer0 = _get_layer0()
    return {
        "status": "ok",
        "layer0_ready": layer0 is not None,
        "verifier_model": layer0.qa_verifier.model,
        "verifier_has_key": bool(layer0.qa_verifier.api_key),
        "temporal_active_op": layer0.temporal_active_op is not None,
        "phase": "1.B",
    }


@router.post("/answer", response_model=POCResponse)
def answer(req: POCRequest) -> POCResponse:
    layer0 = _get_layer0()
    r = layer0.answer(req.question, top_k_claims=req.top_k_claims)
    return POCResponse(
        question=r.question,
        decision=r.decision,
        answer=r.answer,
        layer=r.layer,
        abstention_reason=r.abstention_reason,
        qa_alignment=r.qa_alignment,
        qa_reason=r.qa_reason,
        n_chunks_used=r.n_chunks_used,
        doc_ids_cited=r.doc_ids_cited or [],
        latency_breakdown_ms=r.latency_breakdown_ms or {},
    )
