"""Layer 0 Pipeline production-grade (CH-49 Phase 1, Cap1).

Évolutions vs `runtime_v4_poc.layer0_pipeline` :
  - QuestionTrace telemetry (Amendment 5)
  - 3 catégories abstain logging (Amendment 1) — log technique, gold-grid offline
  - Mode unified_prompt opt-in (Amendment 7) — bascule via env RUNTIME_V4_2_UNIFIED_PROMPT
  - Escalation reason explicite (Cap3 trigger §1)
  - Fail-safe extraction (capture exceptions, retourne ABSTAIN structuré)

Réutilise :
  - EvidenceCollector V4.1 (knowbase.facts_first.evidence_collector)
  - ClaimRetriever V3 (knowbase.runtime_v3.retriever)
  - TemporalActiveVersionOperator POC (knowbase.runtime_v4_poc.operators)
  - RuntimeLLMClient V3 (Llama-3.3-70B-Turbo Together AI primary)
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional

from knowbase.runtime_v4_2 import telemetry
from knowbase.runtime_v4_2.intent_router import UnifiedIntentRouter, RouterDecision
from knowbase.runtime_v4_2.layer2_orchestrator import Layer2Orchestrator
from knowbase.runtime_v4_2.models import (
    AbstainCategory,
    EscalationReason,
    Layer0Response,
    QuestionTrace,
    UnifiedExtractionResult,
)
from knowbase.runtime_v4_2.qa_alignment_verifier import QAAlignmentVerifier
from knowbase.runtime_v4_2.unified_extractor import UnifiedExtractor

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """You are a documentary assistant. Answer the user's question using ONLY the evidence chunks provided.

Rules:
- If the answer is clearly supported by the chunks, give a concise direct answer with citations [doc=ID]
- If multiple chunks contradict, mention both with citations
- If the chunks don't contain the answer, respond exactly: "La reponse a votre question n'a pas ete trouvee dans les documents disponibles."
- Stay concise: 1-3 sentences max
- Always include [doc=...] citations when claiming a fact

Format your answer as plain text, no JSON.
"""

# Abstain reason codes (techniques, pour log) — Amendment 1
REASON_NO_EVIDENCE = "abstain_no_evidence"
REASON_QA_MISALIGNED = "abstain_qa_misaligned"
REASON_QA_ABSTAIN_OK = "abstain_qa_abstain_ok"
REASON_LLM_ERROR = "abstain_llm_error"


class _SyntheticAlign:
    """Substitut QAVerifierTrace lorsqu'on saute le DeepSeek call (mode unifié haute conf)."""

    __slots__ = ("decision", "reason", "confidence", "latency_ms", "provider", "fallback_used")

    def __init__(
        self,
        decision: str,
        reason: str,
        confidence: float,
        latency_ms: int,
        provider: str,
        fallback_used: bool,
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.confidence = confidence
        self.latency_ms = latency_ms
        self.provider = provider
        self.fallback_used = fallback_used


class Layer0Pipeline:
    """Pipeline Layer 0 production avec telemetry + escalation Cap2 operators."""

    def __init__(
        self,
        evidence_collector: Any,
        llm_client: Any,
        qa_verifier: Optional[QAAlignmentVerifier] = None,
        temporal_active_op: Optional[Any] = None,
        lifecycle_resolution_op: Optional[Any] = None,
        kg_query_op: Optional[Any] = None,
        set_reasoning_op: Optional[Any] = None,
        comparison_contradiction_op: Optional[Any] = None,
        layer2_orchestrator: Optional[Layer2Orchestrator] = None,
        intent_router: Optional[UnifiedIntentRouter] = None,
        enable_telemetry: bool = True,
        unified_extractor: Optional[UnifiedExtractor] = None,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.llm_client = llm_client
        self.qa_verifier = qa_verifier or QAAlignmentVerifier()
        self.temporal_active_op = temporal_active_op
        self.lifecycle_resolution_op = lifecycle_resolution_op
        self.kg_query_op = kg_query_op
        self.set_reasoning_op = set_reasoning_op
        self.comparison_contradiction_op = comparison_contradiction_op
        self.layer2_orchestrator = layer2_orchestrator
        self.intent_router = intent_router
        self.enable_telemetry = enable_telemetry
        self.unified_prompt_enabled = (
            os.getenv("RUNTIME_V4_2_UNIFIED_PROMPT", "false").lower() == "true"
        )
        self.unified_extractor = unified_extractor or UnifiedExtractor(llm_client=llm_client)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def answer(self, question: str, top_k_claims: int = 12) -> Layer0Response:
        question_id = telemetry.make_question_id(question)
        timings: dict[str, int] = {}
        t_total = time.time()

        trace = QuestionTrace(
            question_id=question_id,
            question=question,
            timestamp=telemetry.now_iso(),
            layer_used="layer0",
            used_unified_prompt=self.unified_prompt_enabled,
        )

        # --------------------------------------------------------------- #
        # 0.0 Unified Intent Router (Optim Phase 4) — 1 LLM call dispatche
        # vers les operators applicables au lieu de cascade séquentielle.
        # --------------------------------------------------------------- #
        applicable_ops: set[str] = {"temporal_active", "lifecycle_resolution",
                                     "kg_query", "set_reasoning",
                                     "comparison_contradiction"}  # default : tous
        if self.intent_router is not None:
            t0 = time.time()
            try:
                router_decision = self.intent_router.dispatch(question)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[router] dispatch raised: {exc} — fallback all operators")
                router_decision = None
            timings["router_ms"] = int((time.time() - t0) * 1000)

            if router_decision is not None and not router_decision.error:
                applicable_ops = set(router_decision.applicable_operators)
                trace.intent_scores = {
                    "router_confidence": router_decision.confidence,
                    "router_skip_layer1": 1.0 if router_decision.skip_layer1 else 0.0,
                }
                if router_decision.skip_layer1:
                    logger.info(
                        f"[router] skip Layer 1 for q='{question[:80]}' "
                        f"(reason: {router_decision.reason[:80]})"
                    )
                    # On va direct Layer 0 — pas d'operator essayé
                    applicable_ops = set()
                else:
                    logger.info(
                        f"[router] dispatch operators={list(applicable_ops)} "
                        f"conf={router_decision.confidence:.2f}"
                    )

        # --------------------------------------------------------------- #
        # 0.A Escalation : temporal_active_version operator (Cap2.A)
        # --------------------------------------------------------------- #
        if self.temporal_active_op is not None and "temporal_active" in applicable_ops:
            t0 = time.time()
            try:
                top_result = self.temporal_active_op.execute(question)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Cap2.A operator raised: {exc} — falling back to Layer 0")
                top_result = None
            timings["operator_temporal_ms"] = int((time.time() - t0) * 1000)

            if top_result is not None and top_result.triggered and top_result.decision == "ANSWER":
                # Verifier alignment quand même (anti-biais déterministe — ADR §0)
                t0 = time.time()
                align = self.qa_verifier.verify(question, top_result.answer)
                timings["qa_align_ms"] = int((time.time() - t0) * 1000)

                if align.decision == "MISALIGNED":
                    # Verifier rejette : la réponse de l'operator ne correspond pas à la question.
                    # Fallback vers le prochain operator (cascade).
                    logger.info(
                        f"[L1.temporal_active] verifier MISALIGNED "
                        f"(reason={align.reason[:80]}), falling back to next operator"
                    )
                else:
                    logger.info(
                        f"[L1.temporal_active] q='{question[:80]}' "
                        f"active_doc={top_result.active_doc_id} verifier={align.decision}"
                    )
                    merged = dict(top_result.latency_breakdown_ms)
                    merged.update(timings)
                    merged["total_ms"] = int((time.time() - t_total) * 1000)
                    doc_ids = self._extract_doc_ids(top_result.answer)

                    response = Layer0Response(
                        question=question,
                        decision="ANSWER",
                        answer=top_result.answer,
                        layer="layer1_temporal_active",
                        qa_alignment=align.decision,
                        qa_reason=align.reason,
                        qa_confidence=align.confidence,
                        n_chunks_used=top_result.cypher_n_hits,
                        doc_ids_cited=doc_ids,
                        latency_breakdown_ms=merged,
                        escalation_reason=EscalationReason.OPERATOR_TRIGGERED,
                        abstain_category=AbstainCategory.ALIGNED,
                    )
                    self._record_trace(
                        trace=trace,
                        response=response,
                        layer1_op="temporal_active_version",
                        layer1_output={
                            "active_doc_id": top_result.active_doc_id,
                            "n_hits": top_result.cypher_n_hits,
                        },
                        fallback_path="primary",
                        verifier=align,
                    )
                    return response

            if top_result is not None and top_result.triggered and top_result.decision == "ABSTAIN":
                logger.info(
                    f"[L1.temporal_active] triggered but ABSTAIN "
                    f"(reason={top_result.abstention_reason}). Falling back to next operator."
                )

        # --------------------------------------------------------------- #
        # 0.B Escalation : lifecycle_resolution operator (Cap2.B)
        # --------------------------------------------------------------- #
        if self.lifecycle_resolution_op is not None and "lifecycle_resolution" in applicable_ops:
            t0 = time.time()
            try:
                lcr_result = self.lifecycle_resolution_op.execute(question)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Cap2.B operator raised: {exc} — falling back to Layer 0")
                lcr_result = None
            timings["operator_lifecycle_ms"] = int((time.time() - t0) * 1000)

            if lcr_result is not None and lcr_result.triggered and lcr_result.decision == "ANSWER":
                t0 = time.time()
                align = self.qa_verifier.verify(question, lcr_result.answer)
                timings["qa_align_ms"] = int((time.time() - t0) * 1000)

                if align.decision == "MISALIGNED":
                    logger.info(
                        f"[L1.lifecycle_resolution] verifier MISALIGNED "
                        f"(reason={align.reason[:80]}), falling back to next operator"
                    )
                else:
                    logger.info(
                        f"[L1.lifecycle_resolution] q='{question[:80]}' "
                        f"direction={lcr_result.direction} candidates={lcr_result.cypher_n_hits} "
                        f"verifier={align.decision}"
                    )
                    merged = dict(lcr_result.latency_breakdown_ms)
                    merged.update(timings)
                    merged["total_ms"] = int((time.time() - t_total) * 1000)
                    doc_ids = self._extract_doc_ids(lcr_result.answer)

                    response = Layer0Response(
                        question=question,
                        decision="ANSWER",
                        answer=lcr_result.answer,
                        layer="layer1_lifecycle_resolution",
                        qa_alignment=align.decision,
                        qa_reason=align.reason,
                        qa_confidence=align.confidence,
                        n_chunks_used=lcr_result.cypher_n_hits,
                        doc_ids_cited=doc_ids,
                        latency_breakdown_ms=merged,
                        escalation_reason=EscalationReason.OPERATOR_TRIGGERED,
                        abstain_category=AbstainCategory.ALIGNED,
                    )
                    self._record_trace(
                        trace=trace,
                        response=response,
                        layer1_op="lifecycle_resolution",
                        layer1_output={
                            "direction": lcr_result.direction,
                            "subject_keywords": lcr_result.subject_keywords,
                            "relation_hint": lcr_result.relation_hint,
                            "n_hits": lcr_result.cypher_n_hits,
                        },
                        fallback_path=lcr_result.fallback_path,
                        verifier=align,
                    )
                    return response

            if lcr_result is not None and lcr_result.triggered and lcr_result.decision == "ABSTAIN":
                logger.info(
                    f"[L1.lifecycle_resolution] triggered but ABSTAIN "
                    f"(reason={lcr_result.abstention_reason}). Falling back to next operator."
                )

        # --------------------------------------------------------------- #
        # 0.C Escalation : kg_query operator (Cap2.C)
        # --------------------------------------------------------------- #
        if self.kg_query_op is not None and "kg_query" in applicable_ops:
            t0 = time.time()
            try:
                kgq_result = self.kg_query_op.execute(question)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Cap2.C operator raised: {exc} — falling back to Layer 0")
                kgq_result = None
            timings["operator_kg_query_ms"] = int((time.time() - t0) * 1000)

            if kgq_result is not None and kgq_result.triggered and kgq_result.decision == "ANSWER":
                t0 = time.time()
                align = self.qa_verifier.verify(question, kgq_result.answer)
                timings["qa_align_ms"] = int((time.time() - t0) * 1000)

                if align.decision == "MISALIGNED":
                    logger.info(
                        f"[L1.kg_query] verifier MISALIGNED "
                        f"(reason={align.reason[:80]}), falling back to next operator"
                    )
                else:
                    logger.info(
                        f"[L1.kg_query] q='{question[:80]}' "
                        f"query_type={kgq_result.query_type} n_rows={len(kgq_result.rows)} "
                        f"verifier={align.decision}"
                    )
                    merged = dict(kgq_result.latency_breakdown_ms)
                    merged.update(timings)
                    merged["total_ms"] = int((time.time() - t_total) * 1000)
                    doc_ids = self._extract_doc_ids(kgq_result.answer)

                    response = Layer0Response(
                        question=question,
                        decision="ANSWER",
                        answer=kgq_result.answer,
                        layer="layer1_kg_query",
                        qa_alignment=align.decision,
                        qa_reason=align.reason,
                        qa_confidence=align.confidence,
                        n_chunks_used=len(kgq_result.rows),
                        doc_ids_cited=doc_ids,
                        latency_breakdown_ms=merged,
                        escalation_reason=EscalationReason.OPERATOR_TRIGGERED,
                        abstain_category=AbstainCategory.ALIGNED,
                    )
                    self._record_trace(
                        trace=trace,
                        response=response,
                        layer1_op="kg_query",
                        layer1_output={
                            "query_type": kgq_result.query_type,
                            "count_value": kgq_result.count_value,
                            "n_rows": len(kgq_result.rows),
                        },
                        fallback_path=kgq_result.fallback_path,
                        verifier=align,
                    )
                    return response

            if kgq_result is not None and kgq_result.triggered and kgq_result.decision == "ABSTAIN":
                logger.info(
                    f"[L1.kg_query] triggered but ABSTAIN "
                    f"(reason={kgq_result.abstention_reason}). Falling back to next operator."
                )

        # --------------------------------------------------------------- #
        # 0.D Escalation : set_reasoning operator (Cap2.D)
        # --------------------------------------------------------------- #
        if self.set_reasoning_op is not None and "set_reasoning" in applicable_ops:
            t0 = time.time()
            try:
                sr_result = self.set_reasoning_op.execute(question)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Cap2.D operator raised: {exc} — falling back to Layer 0")
                sr_result = None
            timings["operator_set_reasoning_ms"] = int((time.time() - t0) * 1000)

            if sr_result is not None and sr_result.triggered and sr_result.decision == "ANSWER":
                t0 = time.time()
                align = self.qa_verifier.verify(question, sr_result.answer)
                timings["qa_align_ms"] = int((time.time() - t0) * 1000)

                if align.decision == "MISALIGNED":
                    logger.info(
                        f"[L1.set_reasoning] verifier MISALIGNED "
                        f"(reason={align.reason[:80]}), falling back to Layer 0"
                    )
                else:
                    logger.info(
                        f"[L1.set_reasoning] q='{question[:80]}' "
                        f"polarity={sr_result.polarity} n_excluded={len(sr_result.items_excluded)} "
                        f"verifier={align.decision}"
                    )
                    merged = dict(sr_result.latency_breakdown_ms)
                    merged.update(timings)
                    merged["total_ms"] = int((time.time() - t_total) * 1000)
                    doc_ids = self._extract_doc_ids(sr_result.answer)

                    response = Layer0Response(
                        question=question,
                        decision="ANSWER",
                        answer=sr_result.answer,
                        layer="layer1_set_reasoning",
                        qa_alignment=align.decision,
                        qa_reason=align.reason,
                        qa_confidence=align.confidence,
                        n_chunks_used=sr_result.n_chunks_analyzed,
                        doc_ids_cited=doc_ids,
                        latency_breakdown_ms=merged,
                        escalation_reason=EscalationReason.OPERATOR_TRIGGERED,
                        abstain_category=AbstainCategory.ALIGNED,
                    )
                    self._record_trace(
                        trace=trace,
                        response=response,
                        layer1_op="set_reasoning",
                        layer1_output={
                            "polarity": sr_result.polarity,
                            "target_scope": sr_result.target_scope,
                            "n_items_excluded": len(sr_result.items_excluded),
                        },
                        fallback_path=sr_result.fallback_path,
                        verifier=align,
                    )
                    return response

            if sr_result is not None and sr_result.triggered and sr_result.decision == "ABSTAIN":
                logger.info(
                    f"[L1.set_reasoning] triggered but ABSTAIN "
                    f"(reason={sr_result.abstention_reason}). Falling back to next operator."
                )

        # --------------------------------------------------------------- #
        # 0.E Escalation : comparison_contradiction operator (Cap2.E)
        # --------------------------------------------------------------- #
        if (
            self.comparison_contradiction_op is not None
            and "comparison_contradiction" in applicable_ops
        ):
            t0 = time.time()
            try:
                cc_result = self.comparison_contradiction_op.execute(question)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Cap2.E operator raised: {exc} — falling back to Layer 0")
                cc_result = None
            timings["operator_comparison_ms"] = int((time.time() - t0) * 1000)

            if cc_result is not None and cc_result.triggered and cc_result.decision == "ANSWER":
                t0 = time.time()
                align = self.qa_verifier.verify(question, cc_result.answer)
                timings["qa_align_ms"] = int((time.time() - t0) * 1000)

                if align.decision == "MISALIGNED":
                    logger.info(
                        f"[L1.comparison_contradiction] verifier MISALIGNED "
                        f"(reason={align.reason[:80]}), falling back to Layer 0"
                    )
                else:
                    logger.info(
                        f"[L1.comparison_contradiction] q='{question[:80]}' "
                        f"clusters={cc_result.n_clusters_analyzed} "
                        f"genuine_conflicts={cc_result.n_genuine_conflicts} "
                        f"verifier={align.decision}"
                    )
                    merged = dict(cc_result.latency_breakdown_ms)
                    merged.update(timings)
                    merged["total_ms"] = int((time.time() - t_total) * 1000)
                    doc_ids = self._extract_doc_ids(cc_result.answer)

                    response = Layer0Response(
                        question=question,
                        decision="ANSWER",
                        answer=cc_result.answer,
                        layer="layer1_comparison_contradiction",
                        qa_alignment=align.decision,
                        qa_reason=align.reason,
                        qa_confidence=align.confidence,
                        n_chunks_used=cc_result.n_clusters_analyzed,
                        doc_ids_cited=doc_ids,
                        latency_breakdown_ms=merged,
                        escalation_reason=EscalationReason.OPERATOR_TRIGGERED,
                        abstain_category=AbstainCategory.ALIGNED,
                    )
                    self._record_trace(
                        trace=trace,
                        response=response,
                        layer1_op="comparison_contradiction",
                        layer1_output={
                            "expected_outcome": cc_result.expected_outcome,
                            "n_clusters": cc_result.n_clusters_analyzed,
                            "n_genuine_conflicts": cc_result.n_genuine_conflicts,
                            "divergences": cc_result.divergences,
                        },
                        fallback_path=cc_result.fallback_path,
                        verifier=align,
                    )
                    return response

            if cc_result is not None and cc_result.triggered and cc_result.decision == "ABSTAIN":
                logger.info(
                    f"[L1.comparison_contradiction] triggered but ABSTAIN "
                    f"(reason={cc_result.abstention_reason}). Falling back to Layer 0."
                )

        # --------------------------------------------------------------- #
        # 1. Retrieval V4.1
        # --------------------------------------------------------------- #
        t0 = time.time()
        try:
            bundle = self.evidence_collector.collect(
                question=question, top_k=top_k_claims, mode="single",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Layer0 retrieval failed")
            timings["retrieval_ms"] = int((time.time() - t0) * 1000)
            timings["total_ms"] = int((time.time() - t_total) * 1000)
            response = Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="Erreur lors de la collecte d'évidence.",
                abstention_reason=f"retrieval_error: {exc}",
                latency_breakdown_ms=timings,
                escalation_reason=EscalationReason.LAYER0_ABSTAIN_NO_OP,
                abstain_category=AbstainCategory.UNKNOWN,
            )
            self._record_trace(trace, response, error=str(exc))
            return response
        timings["retrieval_ms"] = int((time.time() - t0) * 1000)

        n_claims = len(bundle.claims)
        if n_claims == 0:
            timings["total_ms"] = int((time.time() - t_total) * 1000)
            response = Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="Aucune preuve trouvée pour cette question.",
                abstention_reason=f"{REASON_NO_EVIDENCE} "
                f"(answerability_hint={bundle.answerability_hint})",
                n_chunks_used=0,
                latency_breakdown_ms=timings,
                escalation_reason=EscalationReason.LAYER0_ABSTAIN_NO_OP,
                abstain_category=AbstainCategory.MISALIGNED_ABSTAIN_CORRECT,
                raw_evidence_n_claims=0,
            )
            self._record_trace(trace, response)
            return response

        chunks_text = self._format_claims(bundle.claims)

        # --------------------------------------------------------------- #
        # 2. Extraction (mode séparé ou unifié)
        # --------------------------------------------------------------- #
        used_unified = False
        unified_qa_skipped = False
        unified_result: Optional[UnifiedExtractionResult] = None
        t0 = time.time()
        try:
            if self.unified_prompt_enabled:
                unified_result = self.unified_extractor.extract(question, chunks_text)
                answer_text = unified_result.extracted_answer
                used_unified = True
                trace.intent_scores = dict(unified_result.intent_scores)
            else:
                answer_text = self._extract_answer(question, chunks_text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Layer0 extraction failed")
            timings["extraction_ms"] = int((time.time() - t0) * 1000)
            timings["total_ms"] = int((time.time() - t_total) * 1000)
            response = Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="Erreur du pipeline d'extraction.",
                abstention_reason=f"{REASON_LLM_ERROR}: {exc}",
                n_chunks_used=n_claims,
                latency_breakdown_ms=timings,
                escalation_reason=EscalationReason.LAYER0_ABSTAIN_NO_OP,
                abstain_category=AbstainCategory.UNKNOWN,
                raw_evidence_n_claims=n_claims,
                used_unified_prompt=used_unified,
            )
            self._record_trace(trace, response, error=str(exc))
            return response
        timings["extraction_ms"] = int((time.time() - t0) * 1000)

        # --------------------------------------------------------------- #
        # 3. Q↔A Alignment Verifier (skippé si unified haute confiance)
        # --------------------------------------------------------------- #
        t0 = time.time()
        if used_unified and unified_result is not None and not unified_result.needs_external_verifier:
            # Skip DeepSeek call : on fait confiance au self-check Llama
            unified_qa_skipped = True
            align = _SyntheticAlign(
                decision=unified_result.qa_alignment,
                reason=f"unified_self_check (conf={unified_result.qa_confidence:.2f}): {unified_result.qa_reason}",
                confidence=unified_result.qa_confidence,
                latency_ms=0,
                provider="self_check_unified",
                fallback_used=False,
            )
        else:
            align = self.qa_verifier.verify(question, answer_text)
        timings["qa_align_ms"] = int((time.time() - t0) * 1000)
        timings["unified_qa_skipped"] = 1 if unified_qa_skipped else 0
        timings["total_ms"] = int((time.time() - t_total) * 1000)

        doc_ids = self._extract_doc_ids(answer_text)

        # --------------------------------------------------------------- #
        # 4. Decision + abstain_category (avec escalation Layer 2 si MISALIGNED)
        # --------------------------------------------------------------- #
        if align.decision == "MISALIGNED":
            # Escalation Layer 2 (Cap3) : Layer 0 a échoué, tenter l'orchestrator
            if self.layer2_orchestrator is not None:
                t_l2 = time.time()
                try:
                    l2_resp = self.layer2_orchestrator.answer(question)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[L2] orchestrator raised: {exc}")
                    l2_resp = None
                timings["layer2_ms"] = int((time.time() - t_l2) * 1000)
                timings["total_ms"] = int((time.time() - t_total) * 1000)

                if l2_resp is not None and l2_resp.decision == "ANSWER":
                    # Verifier final sur Layer 2 answer
                    t_v2 = time.time()
                    align2 = self.qa_verifier.verify(question, l2_resp.answer)
                    timings["layer2_qa_align_ms"] = int((time.time() - t_v2) * 1000)
                    timings["total_ms"] = int((time.time() - t_total) * 1000)

                    if align2.decision != "MISALIGNED":
                        logger.info(
                            f"[L2] q='{question[:80]}' iters={l2_resp.n_iterations} "
                            f"verifier={align2.decision}"
                        )
                        l2_doc_ids = self._extract_doc_ids(l2_resp.answer)
                        response = Layer0Response(
                            question=question,
                            decision="ANSWER",
                            answer=l2_resp.answer,
                            layer="layer2",
                            qa_alignment=align2.decision,
                            qa_reason=align2.reason,
                            qa_confidence=align2.confidence,
                            n_chunks_used=n_claims,
                            doc_ids_cited=l2_doc_ids,
                            latency_breakdown_ms=timings,
                            escalation_reason=EscalationReason.LAYER0_ABSTAIN_NO_OP,
                            abstain_category=AbstainCategory.ALIGNED,
                            raw_evidence_n_claims=n_claims,
                            used_unified_prompt=used_unified,
                        )
                        trace.layer2_iterations = l2_resp.n_iterations
                        trace.layer2_tool_calls = l2_resp.tool_calls_log
                        self._record_trace(
                            trace=trace, response=response,
                            verifier=align2, fallback_path="layer2",
                        )
                        return response
                    else:
                        logger.info(
                            f"[L2] verifier rejected layer2 answer too "
                            f"(reason={align2.reason[:80]})"
                        )

            # Pas d'orchestrator OU Layer 2 a aussi échoué → ABSTAIN MISALIGNED final
            response = Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="La réponse extraite ne correspond pas précisément à la question. "
                "Réessai avec un raisonnement plus poussé recommandé.",
                abstention_reason=f"{REASON_QA_MISALIGNED}: {align.reason}",
                qa_alignment=align.decision,
                qa_reason=align.reason,
                qa_confidence=align.confidence,
                n_chunks_used=n_claims,
                doc_ids_cited=doc_ids,
                latency_breakdown_ms=timings,
                escalation_reason=EscalationReason.LAYER0_ABSTAIN_NO_OP,
                abstain_category=AbstainCategory.MISALIGNED_BUT_ANSWERABLE,
                raw_evidence_n_claims=n_claims,
                used_unified_prompt=used_unified,
            )
            self._record_trace(trace, response, verifier=align)
            return response

        if align.decision == "ABSTAIN_OK":
            # Layer 0 abstient avec confirmation verifier. Avant de finaliser, on tente
            # Layer 2 (ADR §1 Cap3 cas 1+4) : peut-être que l'orchestrator avec tools
            # peut composer une réponse multi-step que Layer 0 ne pouvait pas extraire.
            if self.layer2_orchestrator is not None:
                t_l2 = time.time()
                try:
                    l2_resp = self.layer2_orchestrator.answer(question)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[L2] orchestrator raised: {exc}")
                    l2_resp = None
                timings["layer2_ms"] = int((time.time() - t_l2) * 1000)
                timings["total_ms"] = int((time.time() - t_total) * 1000)

                if l2_resp is not None and l2_resp.decision == "ANSWER":
                    t_v2 = time.time()
                    align2 = self.qa_verifier.verify(question, l2_resp.answer)
                    timings["layer2_qa_align_ms"] = int((time.time() - t_v2) * 1000)
                    timings["total_ms"] = int((time.time() - t_total) * 1000)

                    if align2.decision == "ALIGNED":
                        logger.info(
                            f"[L2] (post abstain_ok) q='{question[:80]}' "
                            f"iters={l2_resp.n_iterations} verifier=ALIGNED"
                        )
                        l2_doc_ids = self._extract_doc_ids(l2_resp.answer)
                        response = Layer0Response(
                            question=question,
                            decision="ANSWER",
                            answer=l2_resp.answer,
                            layer="layer2",
                            qa_alignment=align2.decision,
                            qa_reason=align2.reason,
                            qa_confidence=align2.confidence,
                            n_chunks_used=n_claims,
                            doc_ids_cited=l2_doc_ids,
                            latency_breakdown_ms=timings,
                            escalation_reason=EscalationReason.LAYER0_ABSTAIN_NO_OP,
                            abstain_category=AbstainCategory.ALIGNED,
                            raw_evidence_n_claims=n_claims,
                            used_unified_prompt=used_unified,
                        )
                        trace.layer2_iterations = l2_resp.n_iterations
                        trace.layer2_tool_calls = l2_resp.tool_calls_log
                        self._record_trace(
                            trace=trace, response=response,
                            verifier=align2, fallback_path="layer2_post_abstain_ok",
                        )
                        return response
                    else:
                        logger.info(
                            f"[L2] (post abstain_ok) verifier rejected layer2 answer "
                            f"(verdict={align2.decision}). Keeping Layer 0 abstain."
                        )

            # Pas de Layer 2 OU Layer 2 a échoué → ABSTAIN final propre
            response = Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer=answer_text,
                abstention_reason=f"{REASON_QA_ABSTAIN_OK}: {align.reason}",
                qa_alignment=align.decision,
                qa_reason=align.reason,
                qa_confidence=align.confidence,
                n_chunks_used=n_claims,
                doc_ids_cited=doc_ids,
                latency_breakdown_ms=timings,
                escalation_reason=EscalationReason.NONE,
                abstain_category=AbstainCategory.MISALIGNED_ABSTAIN_CORRECT,
                raw_evidence_n_claims=n_claims,
                used_unified_prompt=used_unified,
            )
            self._record_trace(trace, response, verifier=align)
            return response

        # ALIGNED → ANSWER
        response = Layer0Response(
            question=question,
            decision="ANSWER",
            answer=answer_text,
            qa_alignment=align.decision,
            qa_reason=align.reason,
            qa_confidence=align.confidence,
            n_chunks_used=n_claims,
            doc_ids_cited=doc_ids,
            latency_breakdown_ms=timings,
            escalation_reason=EscalationReason.NONE,
            abstain_category=AbstainCategory.ALIGNED,
            raw_evidence_n_claims=n_claims,
            used_unified_prompt=used_unified,
        )
        self._record_trace(trace, response, verifier=align)
        return response

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _extract_answer(self, question: str, chunks_text: str) -> str:
        """Mode unifié vs séparé. Pour Phase 1, mode séparé par défaut.

        Le mode unifié (Amendment 7) sera activé après bake-off comparatif (P1.3).
        """
        prompt_messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"Question: {question}\n\nEvidence chunks:\n{chunks_text}\n\nAnswer:",
            },
        ]
        return self.llm_client.chat_completion(
            messages=prompt_messages,
            temperature=0.1,
            max_tokens=500,
        )

    def _record_trace(
        self,
        trace: QuestionTrace,
        response: Layer0Response,
        layer1_op: Optional[str] = None,
        layer1_output: Optional[dict] = None,
        fallback_path: Optional[str] = None,
        verifier: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        if not self.enable_telemetry:
            return
        trace.layer_used = response.layer
        trace.layer1_operator = layer1_op
        trace.layer1_output = layer1_output
        trace.layer1_fallback_path = fallback_path
        trace.escalation_path = (
            response.layer if response.layer != "layer0" else "layer0"
        )
        trace.latency_breakdown_ms = response.latency_breakdown_ms
        trace.abstain_category = (
            response.abstain_category.value if response.abstain_category else None
        )
        trace.error = error
        if verifier is not None:
            trace.verifier_result = {
                "decision": verifier.decision,
                "reason": verifier.reason,
                "confidence": verifier.confidence,
                "latency_ms": verifier.latency_ms,
                "provider": getattr(verifier, "provider", None),
                "fallback_used": getattr(verifier, "fallback_used", False),
            }
        trace.final_answer = {
            "decision": response.decision,
            "answer_excerpt": (response.answer or "")[:300],
            "doc_ids_cited": response.doc_ids_cited,
            "n_chunks_used": response.n_chunks_used,
            "abstention_reason": response.abstention_reason,
        }
        telemetry.append_trace(trace)

    @staticmethod
    def _format_claims(claims: list) -> str:
        out = []
        for c in claims[:15]:
            quote = (getattr(c, "quote", "") or "").strip()
            if not quote:
                continue
            page = f" p.{c.page_no}" if getattr(c, "page_no", None) else ""
            out.append(f"[doc={c.doc_id}{page}] {quote[:500]}")
        return "\n\n".join(out)

    @staticmethod
    def _extract_doc_ids(answer: str) -> list[str]:
        return list(set(re.findall(r"\[doc=([^\]]+)\]", answer or "")))
