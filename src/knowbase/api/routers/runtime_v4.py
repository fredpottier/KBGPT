"""
Router API Runtime V4 — Pipeline Facts-First (CH-41 + CH-42 leviers).

Endpoint POST /api/runtime_v4/answer
Endpoint GET  /api/runtime_v4/health

Architecture V4 :
  [A] QuestionAnalyzer (5 types structurels + epistemic post-retrieval)
  [B] EvidenceCollector (Claims Neo4j + chunks Qdrant)
  [C] Type-Adaptive Structurer (list/factual/temporal/comparison/causal)
  [D] Type-Adaptive Composer (Gemma-3-12b-it formatage)
  [E] Channel 1 verifier (déterministe) + Channel 2 NLI (mDeBERTa)
  [F] EvidenceRerouter (CH-42.3 promotions corpus-aware)

Schema de réponse compatible avec V3 pour benchmarks RAGAS/T2T5/Robustesse.

Domain-agnostic (charte anti-V2 respectée).
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
from knowbase.facts_first.pipeline import FactsFirstPipeline, PipelineResponse
from knowbase.facts_first import (
    QuestionAnalyzer, EvidenceCollector,
    ListStructurer, ListComposer, Channel1ListVerifier,
    FactualStructurer, FactualComposer, Channel1FactualVerifier,
    TemporalStructurer, TemporalComposer, Channel1TemporalVerifier,
    ComparisonStructurer, ComparisonComposer, Channel1ComparisonVerifier,
    CausalStructurer, CausalComposer, Channel1CausalVerifier,
    SelfCorrector, Channel2NLIVerifier, EvidenceRerouter,
)
from knowbase.runtime_v3.retriever import ClaimRetriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime_v4", tags=["runtime_v4"])


class V4AnswerRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Question utilisateur en langage naturel")
    top_k_claims: int = Field(20, ge=1, le=50, description="Nombre de claims/chunks récupérés")


class V4AnswerResponse(BaseModel):
    """Schema réponse Runtime V4 — compatible V3 pour benchmarks."""
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
    # Champs V4-specific (extra)
    primary_type: Optional[str] = None
    routing_decision: Optional[str] = None
    coverage_state: Optional[str] = None
    rerouter_promoted: bool = False
    rerouter_promoted_to: Optional[str] = None
    # CH-47 Phase 0.B — exposer facts_first pour audit qualité
    facts_first: Optional[dict] = None


_pipeline_instance: Optional[FactsFirstPipeline] = None


def _get_pipeline(force_reload: bool = False) -> FactsFirstPipeline:
    """Lazy singleton du pipeline V4 Facts-First."""
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

    retriever = ClaimRetriever(
        qdrant_client=qdrant, embedder=embedder, driver=driver,
        collection_name="knowbase_chunks_v2", tenant_id=tenant_id,
    )
    evidence_collector = EvidenceCollector(
        retriever=retriever, neo4j_driver=driver, tenant_id=tenant_id, top_k=20,
    )

    # Couches transverses activables via env (default ON)
    use_transverse = os.getenv("V4_TRANSVERSE_ENABLED", "true").lower() == "true"
    nli_enabled = os.getenv("NLI_CHANNEL2_ENABLED", "true").lower() == "true"

    _pipeline_instance = FactsFirstPipeline(
        analyzer=QuestionAnalyzer(),
        evidence_collector=evidence_collector,
        list_structurer=ListStructurer(),
        list_composer=ListComposer(),
        list_verifier=Channel1ListVerifier(),
        factual_structurer=FactualStructurer(),
        factual_composer=FactualComposer(),
        factual_verifier=Channel1FactualVerifier(),
        temporal_structurer=TemporalStructurer(),
        temporal_composer=TemporalComposer(),
        temporal_verifier=Channel1TemporalVerifier(),
        comparison_structurer=ComparisonStructurer(),
        comparison_composer=ComparisonComposer(),
        comparison_verifier=Channel1ComparisonVerifier(),
        causal_structurer=CausalStructurer(),
        causal_composer=CausalComposer(),
        causal_verifier=Channel1CausalVerifier(),
        self_corrector=SelfCorrector() if use_transverse else None,
        channel2_verifier=Channel2NLIVerifier(enabled=nli_enabled) if use_transverse else None,
        evidence_rerouter=EvidenceRerouter(neo4j_driver=driver, tenant_id=tenant_id) if use_transverse else None,
        tenant_id=tenant_id,
    )
    logger.info("Runtime V4 Facts-First pipeline initialized (transverse=%s, nli=%s)",
                use_transverse, nli_enabled)
    return _pipeline_instance


def _extract_doc_ids_and_chunks(response: PipelineResponse) -> tuple[list[str], list[dict]]:
    """Extrait doc_ids cités et chunks utilisés depuis la PipelineResponse V4."""
    doc_ids: list[str] = []
    chunks_used: list[dict] = []

    # 1. Depuis facts_first (sources des items/facts/etc.)
    ff = response.facts_first or {}
    type_specifics = ["list_specific", "factual_specific", "temporal_specific",
                      "comparison_specific", "causal_specific"]
    for ts_key in type_specifics:
        ts = ff.get(ts_key) or {}
        for collection_key in ("items", "facts", "timeline", "compared_facts", "causal_chains"):
            for entry in (ts.get(collection_key) or []):
                if not isinstance(entry, dict):
                    continue
                src = entry.get("source") or (entry.get("fact") or {}).get("source")
                if isinstance(src, dict):
                    doc_id = src.get("doc_id")
                    if doc_id and doc_id not in doc_ids:
                        doc_ids.append(doc_id)
                # nested steps (causal_chains)
                for sub in (entry.get("steps") or []):
                    sub_src = (sub or {}).get("source")
                    if isinstance(sub_src, dict):
                        d = sub_src.get("doc_id")
                        if d and d not in doc_ids:
                            doc_ids.append(d)

    # 2. Chunks_used depuis evidence_bundle (claims pré-collectés pour RAGAS contexts)
    if response.evidence_bundle is not None:
        for c in response.evidence_bundle.claims[:15]:
            text = (c.quote or "")[:1500]
            if text:
                chunks_used.append({
                    "text": text,
                    "doc_id": c.doc_id,
                    "claim_id": c.claim_id,
                    "score": c.score,
                })
    return doc_ids, chunks_used


def _derive_decision(response: PipelineResponse) -> tuple[str, Optional[str]]:
    """Détermine decision (ANSWER/REJECT_FALSE_PREMISE/ABSTAIN) + raison abstention."""
    if response.routing_decision == "abstain_unanswerable":
        return "ABSTAIN", (response.diagnostic or {}).get("reason", "no_evidence_collected")
    ff = response.facts_first or {}
    if ff.get("answerability") == "unanswerable":
        return "ABSTAIN", "answerability_unanswerable"
    if ff.get("answerability") == "false_premise":
        return "REJECT_FALSE_PREMISE", None
    if response.routing_decision == "deferred_to_v3":
        return "ABSTAIN", "type_not_handled"
    return "ANSWER", None


@router.post("/answer", response_model=V4AnswerResponse)
def answer(request: V4AnswerRequest) -> V4AnswerResponse:
    """Execute le pipeline V4 Facts-First sur une question.

    Pipeline :
    1. QuestionAnalyzer → primary_type (5 types structurels)
    2. EvidenceCollector → claims Neo4j + chunks Qdrant + KG enrichment
    3. Type-Adaptive Structurer → facts_first JSON (extractive, evidence-locked)
    4. Type-Adaptive Composer → answer_text (Gemma-3-12b-it formatage)
    5. Channel 1 verifier (déterministe) + Channel 2 NLI (mDeBERTa)
    6. EvidenceRerouter (corpus-aware promotions)

    Réponse JSON V3-compatible pour bench RAGAS/T2T5/Robustesse.
    """
    pipeline = _get_pipeline()
    try:
        response: PipelineResponse = pipeline.answer(
            question=request.question,
            top_k_evidence=request.top_k_claims,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Runtime V4 pipeline failed")
        raise HTTPException(status_code=500, detail=f"V4 pipeline error: {exc}") from exc

    decision, abstention_reason = _derive_decision(response)
    doc_ids, chunks_used = _extract_doc_ids_and_chunks(response)
    ff = response.facts_first or {}

    # Faithfulness depuis Channel 2 NLI (si actif)
    ch2 = response.channel2
    faithfulness_score = float(ch2.overall_score) if ch2 else 0.0
    faithfulness_verdict = ch2.overall_verdict if ch2 else "UNKNOWN"
    n_supported = ch2.n_claims_supported if ch2 else 0
    n_unsupported = ch2.n_claims_unsupported if ch2 else 0

    # Subject extraction selon type
    subject = ""
    for ts_key in ("list_specific", "temporal_specific", "comparison_specific", "causal_specific"):
        ts = ff.get(ts_key) or {}
        s = ts.get("list_subject") or ts.get("subject") or ts.get("comparison_subject") or ts.get("causal_question")
        if s:
            subject = str(s)[:200]
            break

    # Confidence : analyzer primary_confidence (si dispo)
    confidence = float(getattr(response.analyzer, "primary_confidence", 0.0)) if response.analyzer else 0.0

    # Rerouter info
    rerouter_diag = (response.diagnostic or {}).get("rerouter") or {}
    rerouter_promoted = bool(rerouter_diag.get("was_promoted"))
    rerouter_target = rerouter_diag.get("promoted_type") if rerouter_promoted else None

    # Latence breakdown — instrumentation profonde CH-44.b
    timing_ms = (response.diagnostic or {}).get("timing_ms") or {}
    latency_breakdown = {
        "total_ms": response.total_latency_ms,
        "evidence_count": response.evidence_bundle.n_qdrant_hits if response.evidence_bundle else 0,
        # Stages instrumentés (présents seulement si pipeline a passé par cette étape)
        "analyzer_ms": timing_ms.get("analyzer_ms"),
        "rerouter_preview_retrieval_ms": timing_ms.get("rerouter_preview_retrieval_ms"),
        "rerouter_decision_ms": timing_ms.get("rerouter_decision_ms"),
        "main_retrieval_ms": timing_ms.get("main_retrieval_ms"),
        "structurer_ms": timing_ms.get("structurer_ms"),
        "composer_ms": timing_ms.get("composer_ms"),
        "verifier_ms": timing_ms.get("verifier_ms"),
        "selfcorrector_retry_ms": timing_ms.get("selfcorrector_retry_ms"),
        "channel2_nli_ms": timing_ms.get("channel2_nli_ms"),
        "list_collect_mode": timing_ms.get("list_collect_mode") or timing_ms.get("collect_mode"),
    }

    # Regenerated = self_correction.retry_executed
    regenerated = bool((response.self_correction or {}).get("retry_executed"))

    n_chunks_retrieved = response.evidence_bundle.n_qdrant_hits if response.evidence_bundle else 0

    return V4AnswerResponse(
        question=response.question,
        decision=decision,
        answer=response.answer_text or "",
        false_premise_detected=(decision == "REJECT_FALSE_PREMISE"),
        false_premise_correction=None,  # V4 n'expose pas la correction explicite séparément
        abstention_reason=abstention_reason,
        doc_ids_cited=doc_ids,
        subject=subject,
        presupposition_check="",
        confidence=confidence,
        faithfulness_score=faithfulness_score,
        faithfulness_verdict=faithfulness_verdict,
        n_claims_supported=n_supported,
        n_claims_unsupported=n_unsupported,
        n_chunks_retrieved=n_chunks_retrieved,
        chunks_used=chunks_used,
        regenerated=regenerated,
        latency_breakdown_ms=latency_breakdown,
        primary_type=getattr(response.analyzer, "primary_type", None) if response.analyzer else None,
        routing_decision=response.routing_decision,
        coverage_state=ff.get("coverage_state"),
        rerouter_promoted=rerouter_promoted,
        rerouter_promoted_to=rerouter_target,
        facts_first=ff if ff else None,  # CH-47 Phase 0.B
    )


@router.get("/health")
def health() -> dict:
    """Health check + diagnostic config V4."""
    return {
        "status": "ok",
        "version": "v4_facts_first",
        "pipeline_loaded": _pipeline_instance is not None,
        "stages": [
            "question_analyzer",
            "evidence_collector_neo4j_qdrant",
            "type_adaptive_structurer",
            "type_adaptive_composer",
            "channel1_verifier_deterministic",
            "channel2_nli_mdeberta",
            "evidence_rerouter_corpus_aware",
        ],
        "structurer_types": ["list", "factual", "temporal", "comparison", "causal"],
        "config": {
            "structurer_model_override": os.getenv("FACTS_FIRST_STRUCTURER_MODEL", "default_qwen-72b"),
            "facts_first_mode": os.getenv("FACTS_FIRST_MODE", "quality"),
            "nli_backend": os.getenv("NLI_BACKEND", "mdeberta"),
            "transverse_enabled": os.getenv("V4_TRANSVERSE_ENABLED", "true"),
        },
    }
