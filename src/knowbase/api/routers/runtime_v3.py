"""
Router API Runtime V3 — Pipeline minimaliste 5 stages (CH-39).

Endpoint POST /api/runtime_v3/answer
Endpoint GET  /api/runtime_v3/health

Architecture clean :
1. Hybrid retrieve + rerank GPU
2. Agentic synthesis (1 LLM call, JSON output)
3. NLI faithfulness (mDeBERTa multilingual)
4. Conditional regen (1× max)

Domain-agnostic, pas de hardcoded patterns/lists.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

from knowbase.common.clients.shared_clients import (
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from knowbase.runtime_v3.pipeline import RuntimeV3Pipeline, PipelineV3Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime_v3", tags=["runtime_v3"])


class V3AnswerRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Question utilisateur en langage naturel")
    top_k_claims: int = Field(10, ge=1, le=30, description="Nombre de chunks retrieved après rerank")


class V3AnswerResponse(BaseModel):
    """Schema réponse Runtime V3."""
    question: str
    decision: str  # ANSWER | REJECT_FALSE_PREMISE | ABSTAIN
    answer: str
    false_premise_detected: bool = False
    false_premise_correction: Optional[str] = None
    abstention_reason: Optional[str] = None
    doc_ids_cited: list[str] = []
    subject: str = ""
    presupposition_check: str = ""
    confidence: float = 0.0
    faithfulness_score: float = 0.0
    faithfulness_verdict: str = "UNKNOWN"
    n_claims_supported: int = 0
    n_claims_unsupported: int = 0
    n_chunks_retrieved: int = 0
    chunks_used: list[dict] = []
    regenerated: bool = False
    latency_breakdown_ms: dict = {}


_pipeline_instance: Optional[RuntimeV3Pipeline] = None


def _get_pipeline(force_reload: bool = False) -> RuntimeV3Pipeline:
    """Lazy singleton du pipeline V3."""
    global _pipeline_instance
    if _pipeline_instance is not None and not force_reload:
        return _pipeline_instance

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

    _pipeline_instance = RuntimeV3Pipeline(
        driver=driver,
        qdrant_client=qdrant,
        embedder=embedder,
        tenant_id=tenant_id,
    )
    logger.info("Runtime V3 pipeline initialized")
    return _pipeline_instance


@router.post("/answer", response_model=V3AnswerResponse)
def answer(request: V3AnswerRequest) -> V3AnswerResponse:
    """Execute le pipeline V3 minimaliste sur une question.

    5 stages :
    1. Hybrid retrieve (BM25 + vector) → top_k_claims*3 candidats
    2. Cross-encoder rerank GPU (BGE-v2-m3 multilingue) → top_k_claims
    3. Agentic synthesis : 1 LLM call avec JSON output structuré
    4. NLI faithfulness judge (mDeBERTa-v3 multilingue)
    5. Regen conditionnel (1× max si UNFAITHFUL avec score < 0.5)

    Réponse JSON structurée avec decision (ANSWER/REJECT_FALSE_PREMISE/ABSTAIN),
    citations, faithfulness score, et diagnostic latence par étape.
    """
    pipeline = _get_pipeline()
    try:
        response: PipelineV3Response = pipeline.answer(
            question=request.question,
            top_k=request.top_k_claims,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Runtime V3 pipeline failed")
        raise HTTPException(status_code=500, detail=f"V3 pipeline error: {exc}") from exc

    return V3AnswerResponse(
        question=response.question,
        decision=response.decision,
        answer=response.answer,
        false_premise_detected=response.false_premise_detected,
        false_premise_correction=response.false_premise_correction,
        abstention_reason=response.abstention_reason,
        doc_ids_cited=response.doc_ids_cited,
        subject=response.subject,
        presupposition_check=response.presupposition_check,
        confidence=response.confidence,
        faithfulness_score=response.faithfulness_score,
        faithfulness_verdict=response.faithfulness_verdict,
        n_claims_supported=response.n_claims_supported,
        n_claims_unsupported=response.n_claims_unsupported,
        n_chunks_retrieved=response.n_chunks_retrieved,
        chunks_used=response.chunks_used,
        regenerated=response.regenerated,
        latency_breakdown_ms=response.latency_breakdown_ms,
    )


@router.get("/health")
def health() -> dict:
    """Health check + diagnostic config V3."""
    return {
        "status": "ok",
        "version": "v3",
        "pipeline_loaded": _pipeline_instance is not None,
        "stages": [
            "hybrid_retrieve_bm25_vector",
            "cross_encoder_rerank_gpu",
            "agentic_synthesis_llm",
            "nli_faithfulness_judge",
            "conditional_regen",
        ],
        "models": {
            "rerank": os.getenv("RUNTIME_V2_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
            "nli": os.getenv("RUNTIME_V3_NLI_MODEL", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"),
        },
    }
