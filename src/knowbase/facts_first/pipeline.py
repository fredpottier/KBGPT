"""
OSMOSIS V4 — Facts-First Pipeline orchestrator (Tranche 1 list, CH-41.3 wiring).

Wire les 5 composants pour le type list :
  [A] QuestionAnalyzer    → primary_type detection (CH-41.1)
  [B] EvidenceCollector   → claims Neo4j + chunks Qdrant (CH-41.2)
  [C] ListStructurer      → facts_first_v1 list JSON (CH-41.3)
  [D] ListComposer        → prose + sentence_support (CH-41.3)
  [E] Channel1ListVerifier → validation déterministe (CH-41.3)

Si QuestionAnalyzer renvoie primary_type ≠ list, l'orchestrator NE traite PAS
la question (renvoie un PipelineResponse avec routing_decision != "list_path").
La Tranche 1 ne couvre QUE list. Les autres types iront en V3 (legacy) jusqu'à
ce que leur tranche soit livrée.

Si EvidenceCollector renvoie answerability_hint=unanswerable, on saute Structurer
et on retourne un answer d'abstention déterministe.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

# CH-47 — V4.1 Evidence-Grounded Reasoning (activable via env)
REASONING_MODE_ENABLED = os.getenv("V4_REASONING_MODE_ENABLED", "false").lower() == "true"
# Types qui activent le reasoning_mode (causal, comparison, temporal — types existants
# qui régressent. Hypothetical/conditional/multi_hop seraient ajoutés via CH-47.4 Analyzer)
REASONING_MODE_TYPES = {"causal", "comparison", "temporal"}

from knowbase.facts_first.evidence_collector import EvidenceCollector, EvidenceBundle
from knowbase.facts_first.list_composer import ComposerResult, ListComposer
from knowbase.facts_first.list_structurer import ListStructurer, StructurerResult
from knowbase.facts_first.list_verifier import Channel1ListVerifier, VerifierReport
from knowbase.facts_first.factual_composer import (
    ComposerResult as FactualComposerResult,
    FactualComposer,
)
from knowbase.facts_first.factual_structurer import (
    FactualStructurer,
    StructurerResult as FactualStructurerResult,
)
from knowbase.facts_first.factual_verifier import Channel1FactualVerifier
from knowbase.facts_first.evidence_rerouter import EvidenceRerouter, RerouterDecision
from knowbase.facts_first.nli_channel2 import Channel2NLIVerifier, Channel2Report
from knowbase.facts_first.question_analyzer import (
    AnalyzerResult,
    QuestionAnalyzer,
    RoutingDecision,
)
from knowbase.facts_first.self_corrector import SelfCorrector, SelfCorrectionDecision
# CH-47 — Evidence-Grounded Reasoning modules
from knowbase.facts_first.relational_structurer import (
    RelationalStructurer, get_relational_structurer, extract_unified,
)
from knowbase.facts_first.reasoning_composer import (
    ReasoningComposer, get_reasoning_composer,
)
# Tranches 3-5
from knowbase.facts_first.temporal_pipeline import (
    TemporalStructurer, TemporalComposer, Channel1TemporalVerifier,
)
from knowbase.facts_first.comparison_pipeline import (
    ComparisonStructurer, ComparisonComposer, Channel1ComparisonVerifier,
)
from knowbase.facts_first.causal_pipeline import (
    CausalStructurer, CausalComposer, Channel1CausalVerifier,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResponse:
    """Réponse complète du pipeline Tranche 1 list."""
    question: str
    routing_decision: str  # "list_path" | "deferred_to_v3" | "abstain_unanswerable"
    analyzer: AnalyzerResult
    evidence_bundle: Optional[EvidenceBundle] = None
    facts_first: Optional[dict] = None
    composer: Optional[ComposerResult] = None
    verifier: Optional[VerifierReport] = None
    channel2: Optional[Channel2Report] = None  # Couche C — NLI faithfulness
    self_correction: Optional[dict] = None  # Couche B — diagnostic retry
    answer_text: str = ""
    total_latency_ms: int = 0
    diagnostic: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "question": self.question,
            "routing_decision": self.routing_decision,
            "analyzer": self.analyzer.to_dict(),
            "answer_text": self.answer_text,
            "total_latency_ms": self.total_latency_ms,
            "diagnostic": self.diagnostic,
        }
        if self.evidence_bundle is not None:
            d["evidence"] = {
                "n_qdrant_hits": self.evidence_bundle.n_qdrant_hits,
                "n_neo4j_enriched": self.evidence_bundle.n_neo4j_enriched,
                "n_chunk_fallback": self.evidence_bundle.n_chunk_fallback,
                "n_rejected_invalid_quote": self.evidence_bundle.n_rejected_invalid_quote,
                "answerability_hint": self.evidence_bundle.answerability_hint,
                "doc_ids": self.evidence_bundle.doc_ids(),
            }
        if self.facts_first is not None:
            d["facts_first"] = self.facts_first
        if self.composer is not None:
            d["composer"] = self.composer.to_dict()
        if self.verifier is not None:
            d["verifier"] = self.verifier.to_dict()
        return d


class FactsFirstPipeline:
    """Orchestrator pour les Tranches 1 list + 2 factual.

    Routing :
      - primary_type=list → list_path (CH-41.1+2+3)
      - primary_type=factual → factual_path (CH-41 Tranche 2 + D-FF13)
      - autre → deferred_to_v3 (Tranches 3-5 non livrées)
    """

    def __init__(
        self,
        analyzer: QuestionAnalyzer,
        evidence_collector: EvidenceCollector,
        list_structurer: ListStructurer,
        list_composer: ListComposer,
        list_verifier: Channel1ListVerifier,
        factual_structurer: Optional[FactualStructurer] = None,
        factual_composer: Optional[FactualComposer] = None,
        factual_verifier: Optional[Channel1FactualVerifier] = None,
        temporal_structurer: Optional[TemporalStructurer] = None,
        temporal_composer: Optional[TemporalComposer] = None,
        temporal_verifier: Optional[Channel1TemporalVerifier] = None,
        comparison_structurer: Optional[ComparisonStructurer] = None,
        comparison_composer: Optional[ComparisonComposer] = None,
        comparison_verifier: Optional[Channel1ComparisonVerifier] = None,
        causal_structurer: Optional[CausalStructurer] = None,
        causal_composer: Optional[CausalComposer] = None,
        causal_verifier: Optional[Channel1CausalVerifier] = None,
        self_corrector: Optional[SelfCorrector] = None,
        channel2_verifier: Optional[Channel2NLIVerifier] = None,
        evidence_rerouter: Optional[EvidenceRerouter] = None,
        # CH-47 — Evidence-Grounded Reasoning V4.1 (P0 modules)
        relational_structurer: Optional[RelationalStructurer] = None,
        reasoning_composer: Optional[ReasoningComposer] = None,
        tenant_id: str = "default",
        domain_pack: Optional[str] = None,
    ) -> None:
        self.analyzer = analyzer
        self.evidence_collector = evidence_collector
        self.structurer = list_structurer  # legacy alias
        self.list_structurer = list_structurer
        self.composer = list_composer  # legacy alias
        self.list_composer = list_composer
        self.verifier = list_verifier  # legacy alias
        self.list_verifier = list_verifier
        self.factual_structurer = factual_structurer
        self.factual_composer = factual_composer
        self.factual_verifier = factual_verifier
        self.temporal_structurer = temporal_structurer
        self.temporal_composer = temporal_composer
        self.temporal_verifier = temporal_verifier
        self.comparison_structurer = comparison_structurer
        self.comparison_composer = comparison_composer
        self.comparison_verifier = comparison_verifier
        self.causal_structurer = causal_structurer
        self.causal_composer = causal_composer
        self.causal_verifier = causal_verifier
        # Couches transverses (CH-41 architecture transverse)
        self.self_corrector = self_corrector
        self.channel2_verifier = channel2_verifier
        # CH-42.3 — Evidence-aware rerouter (domain-agnostic, exploite signaux KG)
        self.evidence_rerouter = evidence_rerouter
        # CH-47 — Evidence-Grounded Reasoning modules (lazy si non fournis)
        self.relational_structurer = relational_structurer
        self.reasoning_composer = reasoning_composer
        self.tenant_id = tenant_id
        self.domain_pack = domain_pack

    def answer(
        self,
        question: str,
        doc_ids_scope: Optional[list[str]] = None,
        top_k_evidence: Optional[int] = None,
    ) -> PipelineResponse:
        """Exécute le pipeline complet pour une question.

        Routing : list → list_path (Tranche 1) ; factual → factual_path (Tranche 2) ;
        autre → deferred_to_v3.
        """
        t0 = time.time()
        # CH-44.b — instrumentation profonde latence par stage
        timing: dict[str, int] = {}

        # CH-46 L3 — Parallélisation Analyzer ∥ rerouter_preview_retrieval.
        # Les 2 stages sont indépendants (le retrieval preview se fait sur
        # la question brute pour inspecter signaux KG, sans dépendre du
        # primary_type). On les lance en parallèle pour gagner ~5-8s wall.
        rerouter_decision: Optional[RerouterDecision] = None
        if self.evidence_rerouter:
            t_par = time.time()
            with ThreadPoolExecutor(max_workers=2) as executor:
                fut_analyzer = executor.submit(self.analyzer.analyze, question)
                fut_preview = executor.submit(
                    self.evidence_collector.collect,
                    question=question, doc_ids=doc_ids_scope, top_k=top_k_evidence,
                    mode="single", graph_traversal=None,
                )
                analyzer_res = fut_analyzer.result()
                preview_evidence = fut_preview.result()
            # Approxime les 2 timings : on ne sait pas l'ordre exact, mais le wall
            # parallèle = max(analyzer, preview). Pour la traçabilité, on log les 2
            # comme si séquentiels (utile au debug) mais on ajoute le wall paral.
            timing["analyzer_ms"] = analyzer_res.latency_ms
            timing["rerouter_preview_retrieval_ms"] = int((time.time() - t_par) * 1000) - analyzer_res.latency_ms if analyzer_res.latency_ms else 0
            timing["analyzer_plus_preview_parallel_wall_ms"] = int((time.time() - t_par) * 1000)
            t_dec = time.time()
            rerouter_decision = self.evidence_rerouter.reroute(analyzer_res, preview_evidence)
            timing["rerouter_decision_ms"] = int((time.time() - t_dec) * 1000)
            if rerouter_decision.was_promoted:
                logger.info(
                    "[Pipeline] Rerouter promoted %s → %s : %s",
                    rerouter_decision.original_type,
                    rerouter_decision.promoted_type,
                    rerouter_decision.rationale,
                )
        else:
            # Path sans rerouter : Analyzer seul
            t_a = time.time()
            analyzer_res = self.analyzer.analyze(question)
            timing["analyzer_ms"] = int((time.time() - t_a) * 1000)

        # Type final = promoted si rerouter a tranché, sinon analyzer
        ptype = (
            rerouter_decision.final_type
            if rerouter_decision is not None
            else analyzer_res.primary_type
        )

        # CH-47 — V4.1 Reasoning mode : route vers _answer_reasoning pour les types
        # qui régressent fortement (causal/comparison/temporal). Activable via env.
        if REASONING_MODE_ENABLED and ptype in REASONING_MODE_TYPES:
            return self._answer_reasoning(
                question, analyzer_res, doc_ids_scope, top_k_evidence, t0,
                primary_type=ptype, rerouter_decision=rerouter_decision, timing=timing,
            )

        if ptype == "list":
            return self._answer_list(question, analyzer_res, doc_ids_scope, top_k_evidence, t0,
                                     rerouter_decision=rerouter_decision, timing=timing)
        if ptype == "factual" and self.factual_structurer:
            return self._answer_factual(question, analyzer_res, doc_ids_scope, top_k_evidence, t0,
                                        rerouter_decision=rerouter_decision, timing=timing)
        if ptype == "temporal" and self.temporal_structurer:
            return self._answer_generic(
                question, analyzer_res, doc_ids_scope, top_k_evidence, t0,
                routing_label="temporal_path",
                structurer=self.temporal_structurer,
                composer=self.temporal_composer,
                verifier=self.temporal_verifier,
                rejected_attr="rejected_events",
                collect_mode="single",
                graph_traversal="LIFECYCLE_RELATION",  # SUPERSEDES, EVOLVES_FROM
                rerouter_decision=rerouter_decision, timing=timing,
            )
        if ptype == "comparison" and self.comparison_structurer:
            return self._answer_generic(
                question, analyzer_res, doc_ids_scope, top_k_evidence, t0,
                routing_label="comparison_path",
                structurer=self.comparison_structurer,
                composer=self.comparison_composer,
                verifier=self.comparison_verifier,
                rejected_attr="rejected_sides",
                collect_mode="exhaustive",  # multi-query pour avoir les ≥2 sides
                graph_traversal="LOGICAL_RELATION",  # CONTRADICTS, REAFFIRMS
                rerouter_decision=rerouter_decision, timing=timing,
            )
        if ptype == "causal" and self.causal_structurer:
            return self._answer_generic(
                question, analyzer_res, doc_ids_scope, top_k_evidence, t0,
                routing_label="causal_path",
                structurer=self.causal_structurer,
                composer=self.causal_composer,
                verifier=self.causal_verifier,
                rejected_attr="rejected_steps",
                collect_mode="single",
                graph_traversal=None,
                rerouter_decision=rerouter_decision, timing=timing,
            )

        return PipelineResponse(
            question=question,
            routing_decision="deferred_to_v3",
            analyzer=analyzer_res,
            answer_text="",
            total_latency_ms=int((time.time() - t0) * 1000),
            diagnostic={"reason": f"primary_type={ptype} not handled", "timing_ms": timing},
        )

    def _answer_generic(
        self,
        question: str,
        analyzer_res: AnalyzerResult,
        doc_ids_scope: Optional[list[str]],
        top_k_evidence: Optional[int],
        t0: float,
        routing_label: str,
        structurer,
        composer,
        verifier,
        rejected_attr: str,
        collect_mode: str = "single",
        graph_traversal: Optional[str] = None,
        rerouter_decision: Optional[RerouterDecision] = None,
        timing: Optional[dict] = None,
    ) -> PipelineResponse:
        """Générique pour temporal/comparison/causal — pattern réutilisé avec couches transverses + Couche A."""
        if timing is None:
            timing = {}
        timing["collect_mode"] = collect_mode
        t_ev = time.time()
        evidence = self.evidence_collector.collect(
            question=question, doc_ids=doc_ids_scope, top_k=top_k_evidence,
            mode=collect_mode, graph_traversal=graph_traversal,
        )
        timing["main_retrieval_ms"] = int((time.time() - t_ev) * 1000)
        if evidence.answerability_hint == "unanswerable" and not evidence.claims:
            language = analyzer_res.language or "en"
            ab_msg = composer._abstention_message(language) if hasattr(composer, "_abstention_message") else (
                "La réponse à votre question n'a pas été trouvée dans les documents disponibles."
                if language.startswith("fr") else
                "The answer to your question was not found in the available documents."
            )
            return PipelineResponse(
                question=question, routing_decision="abstain_unanswerable",
                analyzer=analyzer_res, evidence_bundle=evidence,
                answer_text=ab_msg,
                total_latency_ms=int((time.time() - t0) * 1000),
                diagnostic={"reason": "no_evidence_collected", "timing_ms": timing},
            )

        t_s = time.time()
        structurer_res = structurer.structure(
            question=question, evidence=evidence,
            language=analyzer_res.language,
            domain_pack=self.domain_pack, tenant_id=self.tenant_id,
        )
        timing["structurer_ms"] = int((time.time() - t_s) * 1000)
        facts_first = structurer_res.facts_first_json
        t_c = time.time()
        composer_res = composer.compose(facts_first)
        timing["composer_ms"] = int((time.time() - t_c) * 1000)
        t_v = time.time()
        verifier_report = verifier.verify(
            question=question, facts_first=facts_first,
            composer_output=composer_res.to_dict(),
        )
        timing["verifier_ms"] = int((time.time() - t_v) * 1000)

        # Couche B — SelfCorrector (transverse)
        self_correction_diag = None
        if self.self_corrector:
            decision = self.self_corrector.decide(verifier_report)
            self_correction_diag = {
                "should_retry": decision.should_retry,
                "actionable_codes": decision.actionable_codes,
                "retry_executed": False, "retry_outcome": None,
            }
            if decision.should_retry:
                t_retry = time.time()
                retry_res = structurer.structure(
                    question=question, evidence=evidence,
                    language=analyzer_res.language,
                    domain_pack=self.domain_pack, tenant_id=self.tenant_id,
                    feedback_for_retry=decision.feedback_message,
                )
                retry_ff = retry_res.facts_first_json
                retry_composer = composer.compose(retry_ff)
                retry_verifier = verifier.verify(
                    question=question, facts_first=retry_ff,
                    composer_output=retry_composer.to_dict(),
                )
                timing["selfcorrector_retry_ms"] = int((time.time() - t_retry) * 1000)
                selected_res, selected_report, decision_reason = SelfCorrector.select_better(
                    structurer_res, retry_res, verifier_report, retry_verifier
                )
                self_correction_diag["retry_executed"] = True
                self_correction_diag["retry_outcome"] = decision_reason
                if selected_res is retry_res:
                    structurer_res = retry_res
                    facts_first = retry_ff
                    composer_res = retry_composer
                    verifier_report = retry_verifier

        # Couche C — Channel 2 NLI (transverse)
        channel2_report = None
        if self.channel2_verifier:
            t_n = time.time()
            channel2_report = self.channel2_verifier.verify(
                composer_output=composer_res.to_dict(),
                facts_first=facts_first,
            )
            timing["channel2_nli_ms"] = int((time.time() - t_n) * 1000)

        rejected_count = len(getattr(structurer_res, rejected_attr, []) or [])
        return PipelineResponse(
            question=question, routing_decision=routing_label,
            analyzer=analyzer_res, evidence_bundle=evidence,
            facts_first=facts_first, composer=composer_res,
            verifier=verifier_report,
            channel2=channel2_report,
            self_correction=self_correction_diag,
            answer_text=composer_res.answer_text,
            total_latency_ms=int((time.time() - t0) * 1000),
            diagnostic={
                "structurer_rejected_count": rejected_count,
                "structurer_parse_error": structurer_res.parse_error,
                "composer_parse_error": composer_res.parse_error,
                "verifier_passed": verifier_report.passed,
                "verifier_severity": verifier_report.severity,
                "channel2_score": channel2_report.overall_score if channel2_report else None,
                "channel2_verdict": channel2_report.overall_verdict if channel2_report else None,
                "rerouter": rerouter_decision.to_dict() if rerouter_decision else None,
                "timing_ms": timing,
            },
        )

    def _answer_list(
        self,
        question: str,
        analyzer_res: AnalyzerResult,
        doc_ids_scope: Optional[list[str]],
        top_k_evidence: Optional[int],
        t0: float,
        rerouter_decision: Optional[RerouterDecision] = None,
        timing: Optional[dict] = None,
    ) -> PipelineResponse:
        if timing is None:
            timing = {}
        # Couche A — list = mode "single" par défaut (gain latence ~50%).
        # Mode "exhaustive" (multi-query 3× retrieval) + graph "LOGICAL_RELATION"
        # restent opt-in via Domain Pack pour corpus où multi-query a un ROI prouvé
        # (clé list_collect_mode dans config tenant).
        list_collect_mode = "single"
        list_graph_traversal: Optional[str] = None
        if isinstance(self.domain_pack, dict):
            list_collect_mode = self.domain_pack.get("list_collect_mode", "single")
            list_graph_traversal = self.domain_pack.get("list_graph_traversal")
        timing["list_collect_mode"] = list_collect_mode
        t_ev = time.time()
        evidence = self.evidence_collector.collect(
            question=question, doc_ids=doc_ids_scope, top_k=top_k_evidence,
            mode=list_collect_mode,
            graph_traversal=list_graph_traversal,
        )
        timing["main_retrieval_ms"] = int((time.time() - t_ev) * 1000)
        if evidence.answerability_hint == "unanswerable" and not evidence.claims:
            language = analyzer_res.language or "en"
            ab_msg = self.list_composer._abstention_message(language)
            return PipelineResponse(
                question=question, routing_decision="abstain_unanswerable",
                analyzer=analyzer_res, evidence_bundle=evidence,
                answer_text=ab_msg,
                total_latency_ms=int((time.time() - t0) * 1000),
                diagnostic={"reason": "no_evidence_collected", "timing_ms": timing},
            )
        t_s = time.time()
        structurer_res = self.list_structurer.structure(
            question=question, evidence=evidence,
            language=analyzer_res.language,
            domain_pack=self.domain_pack, tenant_id=self.tenant_id,
        )
        timing["structurer_ms"] = int((time.time() - t_s) * 1000)
        facts_first = structurer_res.facts_first_json
        t_c = time.time()
        composer_res = self.list_composer.compose(facts_first)
        timing["composer_ms"] = int((time.time() - t_c) * 1000)
        t_v = time.time()
        verifier_report = self.list_verifier.verify(
            question=question, facts_first=facts_first,
            composer_output=composer_res.to_dict(),
        )
        timing["verifier_ms"] = int((time.time() - t_v) * 1000)

        # Couche B — SelfCorrector retry (transverse)
        self_correction_diag = None
        if self.self_corrector:
            decision = self.self_corrector.decide(verifier_report)
            self_correction_diag = {
                "should_retry": decision.should_retry,
                "actionable_codes": decision.actionable_codes,
                "retry_executed": False,
                "retry_outcome": None,
            }
            if decision.should_retry:
                t_retry = time.time()
                retry_res = self.list_structurer.structure(
                    question=question, evidence=evidence,
                    language=analyzer_res.language,
                    domain_pack=self.domain_pack, tenant_id=self.tenant_id,
                    feedback_for_retry=decision.feedback_message,
                )
                retry_ff = retry_res.facts_first_json
                retry_composer = self.list_composer.compose(retry_ff)
                retry_verifier = self.list_verifier.verify(
                    question=question, facts_first=retry_ff,
                    composer_output=retry_composer.to_dict(),
                )
                timing["selfcorrector_retry_ms"] = int((time.time() - t_retry) * 1000)
                selected_res, selected_report, decision_reason = SelfCorrector.select_better(
                    structurer_res, retry_res, verifier_report, retry_verifier
                )
                self_correction_diag["retry_executed"] = True
                self_correction_diag["retry_outcome"] = decision_reason
                if selected_res is retry_res:
                    structurer_res = retry_res
                    facts_first = retry_ff
                    composer_res = retry_composer
                    verifier_report = retry_verifier

        # Couche C — Channel 2 NLI verifier (transverse)
        channel2_report = None
        if self.channel2_verifier:
            t_n = time.time()
            channel2_report = self.channel2_verifier.verify(
                composer_output=composer_res.to_dict(),
                facts_first=facts_first,
            )
            timing["channel2_nli_ms"] = int((time.time() - t_n) * 1000)

        return PipelineResponse(
            question=question, routing_decision="list_path",
            analyzer=analyzer_res, evidence_bundle=evidence,
            facts_first=facts_first, composer=composer_res,
            verifier=verifier_report,
            channel2=channel2_report,
            self_correction=self_correction_diag,
            answer_text=composer_res.answer_text,
            total_latency_ms=int((time.time() - t0) * 1000),
            diagnostic={
                "structurer_rejected_count": len(structurer_res.rejected_items),
                "structurer_parse_error": structurer_res.parse_error,
                "composer_parse_error": composer_res.parse_error,
                "verifier_passed": verifier_report.passed,
                "verifier_severity": verifier_report.severity,
                "channel2_score": channel2_report.overall_score if channel2_report else None,
                "channel2_verdict": channel2_report.overall_verdict if channel2_report else None,
                "rerouter": rerouter_decision.to_dict() if rerouter_decision else None,
                "timing_ms": timing,
            },
        )

    def _answer_factual(
        self,
        question: str,
        analyzer_res: AnalyzerResult,
        doc_ids_scope: Optional[list[str]],
        top_k_evidence: Optional[int],
        t0: float,
        rerouter_decision: Optional[RerouterDecision] = None,
        timing: Optional[dict] = None,
    ) -> PipelineResponse:
        if timing is None:
            timing = {}
        # Couche A — factual = mode single (default) sans graph
        # (single-fact ne nécessite pas multi-query ni graph traversal — éviter overhead)
        t_ev = time.time()
        evidence = self.evidence_collector.collect(
            question=question, doc_ids=doc_ids_scope, top_k=top_k_evidence,
            mode="single",
        )
        timing["main_retrieval_ms"] = int((time.time() - t_ev) * 1000)
        if evidence.answerability_hint == "unanswerable" and not evidence.claims:
            language = analyzer_res.language or "en"
            ab_msg = self.factual_composer._abstention_message(language)
            return PipelineResponse(
                question=question, routing_decision="abstain_unanswerable",
                analyzer=analyzer_res, evidence_bundle=evidence,
                answer_text=ab_msg,
                total_latency_ms=int((time.time() - t0) * 1000),
                diagnostic={"reason": "no_evidence_collected", "timing_ms": timing},
            )
        t_s = time.time()
        structurer_res = self.factual_structurer.structure(
            question=question, evidence=evidence,
            language=analyzer_res.language,
            analyzer_confidence=analyzer_res.primary_confidence,
            domain_pack=self.domain_pack, tenant_id=self.tenant_id,
        )
        timing["structurer_ms"] = int((time.time() - t_s) * 1000)
        facts_first = structurer_res.facts_first_json
        t_c = time.time()
        composer_res = self.factual_composer.compose(facts_first)
        timing["composer_ms"] = int((time.time() - t_c) * 1000)
        t_v = time.time()
        verifier_report = self.factual_verifier.verify(
            question=question, facts_first=facts_first,
            composer_output=composer_res.to_dict(),
        )
        timing["verifier_ms"] = int((time.time() - t_v) * 1000)

        # Couche B — SelfCorrector retry (transverse)
        self_correction_diag = None
        if self.self_corrector:
            decision = self.self_corrector.decide(verifier_report)
            self_correction_diag = {
                "should_retry": decision.should_retry,
                "actionable_codes": decision.actionable_codes,
                "retry_executed": False,
                "retry_outcome": None,
            }
            if decision.should_retry:
                t_retry = time.time()
                retry_res = self.factual_structurer.structure(
                    question=question, evidence=evidence,
                    language=analyzer_res.language,
                    analyzer_confidence=analyzer_res.primary_confidence,
                    domain_pack=self.domain_pack, tenant_id=self.tenant_id,
                    feedback_for_retry=decision.feedback_message,
                )
                retry_ff = retry_res.facts_first_json
                retry_composer = self.factual_composer.compose(retry_ff)
                retry_verifier = self.factual_verifier.verify(
                    question=question, facts_first=retry_ff,
                    composer_output=retry_composer.to_dict(),
                )
                timing["selfcorrector_retry_ms"] = int((time.time() - t_retry) * 1000)
                selected_res, selected_report, decision_reason = SelfCorrector.select_better(
                    structurer_res, retry_res, verifier_report, retry_verifier
                )
                self_correction_diag["retry_executed"] = True
                self_correction_diag["retry_outcome"] = decision_reason
                if selected_res is retry_res:
                    structurer_res = retry_res
                    facts_first = retry_ff
                    composer_res = retry_composer
                    verifier_report = retry_verifier

        # Couche C — Channel 2 NLI verifier (transverse)
        channel2_report = None
        if self.channel2_verifier:
            t_n = time.time()
            channel2_report = self.channel2_verifier.verify(
                composer_output=composer_res.to_dict(),
                facts_first=facts_first,
            )
            timing["channel2_nli_ms"] = int((time.time() - t_n) * 1000)

        return PipelineResponse(
            question=question, routing_decision="factual_path",
            analyzer=analyzer_res, evidence_bundle=evidence,
            facts_first=facts_first, composer=composer_res,
            verifier=verifier_report,
            channel2=channel2_report,
            self_correction=self_correction_diag,
            answer_text=composer_res.answer_text,
            total_latency_ms=int((time.time() - t0) * 1000),
            diagnostic={
                "structurer_rejected_count": len(structurer_res.rejected_facts),
                "structurer_parse_error": structurer_res.parse_error,
                "composer_parse_error": composer_res.parse_error,
                "verifier_passed": verifier_report.passed,
                "verifier_severity": verifier_report.severity,
                "used_d_ff13_fallback": structurer_res.used_fallback,
                "fallback_mode": structurer_res.fallback_mode,
                "channel2_score": channel2_report.overall_score if channel2_report else None,
                "channel2_verdict": channel2_report.overall_verdict if channel2_report else None,
                "rerouter": rerouter_decision.to_dict() if rerouter_decision else None,
                "timing_ms": timing,
            },
        )


    # ========================================================================
    # CH-47 — V4.1 Evidence-Grounded Reasoning path
    # ========================================================================

    def _answer_reasoning(
        self,
        question: str,
        analyzer_res: AnalyzerResult,
        doc_ids_scope: Optional[list[str]],
        top_k_evidence: Optional[int],
        t0: float,
        primary_type: str,
        rerouter_decision: Optional[RerouterDecision] = None,
        timing: Optional[dict] = None,
    ) -> PipelineResponse:
        """Path V4.1 reasoning_mode (CH-47) pour types régressés (causal/comparison/temporal).

        Pipeline :
          1. Retrieval (mode=single, chunks)
          2. extract_unified() : atomic_facts + relational_facts + reasoning_graph (1 LLM call Mistral-Small)
          3. ReasoningComposer.compose() : reasoning_steps + answer + citations (Qwen2.5-72B)
          4. (optionnel) Channel 2 NLI sur reasoning_steps avec seuils calibrés (CH-47.3)

        Cf ADR §10.4 D-CH47.1 à D-CH47.4.
        """
        if timing is None:
            timing = {}

        # 1. Retrieval (mode single, comme list/factual)
        t_ev = time.time()
        evidence = self.evidence_collector.collect(
            question=question, doc_ids=doc_ids_scope, top_k=top_k_evidence,
            mode="single",
        )
        timing["main_retrieval_ms"] = int((time.time() - t_ev) * 1000)

        if evidence.answerability_hint == "unanswerable" and not evidence.claims:
            language = analyzer_res.language or "en"
            ab_msg = (
                "La réponse à votre question n'a pas été trouvée dans les documents disponibles."
                if language.startswith("fr") else
                "The answer to your question was not found in the available documents."
            )
            return PipelineResponse(
                question=question, routing_decision="abstain_unanswerable",
                analyzer=analyzer_res, evidence_bundle=evidence,
                answer_text=ab_msg,
                total_latency_ms=int((time.time() - t0) * 1000),
                diagnostic={"reason": "no_evidence_collected", "timing_ms": timing,
                            "reasoning_mode": True},
            )

        # 2. extract_unified : atomic_facts + relational_facts (1 call)
        chunks = []
        for c in evidence.claims[:12]:
            chunks.append({
                "id": c.claim_id or f"C{len(chunks)}",
                "doc_id": c.doc_id,
                "quote": (c.quote or "")[:1500],
            })

        rel_struct = self.relational_structurer or get_relational_structurer()
        t_s = time.time()
        unified = extract_unified(
            question=question, evidence_chunks=chunks,
            language=analyzer_res.language or "en",
            structurer=rel_struct,
        )
        timing["structurer_ms"] = int((time.time() - t_s) * 1000)
        timing["reasoning_mode"] = True

        if unified.parse_error or not unified.atomic_facts:
            language = analyzer_res.language or "en"
            ab_msg = (
                f"Aucun fait extractif trouvé dans les documents pour cette question (motif: "
                f"{unified.parse_error or 'no_atomic_facts'})."
                if language.startswith("fr") else
                f"No extractable facts found in documents for this question (reason: "
                f"{unified.parse_error or 'no_atomic_facts'})."
            )
            return PipelineResponse(
                question=question, routing_decision="reasoning_path_abstain",
                analyzer=analyzer_res, evidence_bundle=evidence,
                answer_text=ab_msg,
                total_latency_ms=int((time.time() - t0) * 1000),
                diagnostic={"reason": "structurer_unified_failed",
                            "parse_error": unified.parse_error,
                            "timing_ms": timing, "reasoning_mode": True},
            )

        # 3. ReasoningComposer
        rc = self.reasoning_composer or get_reasoning_composer()
        t_c = time.time()
        comp = rc.compose(
            question=question,
            atomic_facts=unified.atomic_facts,
            relational_facts=unified.relational_facts,
            reasoning_graph=unified.reasoning_graph,
            primary_type=primary_type,
        )
        timing["composer_ms"] = int((time.time() - t_c) * 1000)

        # 4. (optionnel) Channel 2 NLI — laissé au router runtime_v4 ou désactivé pour ce path.
        # Le Channel 1 Verifier intégré dans ReasoningComposer (validation IDs) tient lieu de
        # garde-fou minimal. Channel 2 NLI fine-grained sur reasoning_steps = chantier futur.
        timing["channel2_nli_ms"] = 0

        # Construit facts_first_v2 (extension v1 — atomic + relational + graph)
        ff_v2 = {
            "schema_version": "facts_first_v2",
            "primary_type": primary_type,
            "answerability": unified.answerability,
            "coverage_state": "not_applicable",
            "language": analyzer_res.language or "en",
            "atomic_facts": unified.atomic_facts,
            "relational_facts": unified.relational_facts,
            "reasoning_graph": unified.reasoning_graph,
            # Pour compatibilité router runtime_v4 (qui lit facts_first.{type}_specific) :
            f"{primary_type}_specific": {
                "facts": unified.atomic_facts,  # alias atomic comme "facts"
                "reasoning_summary": (comp.answer or "")[:500],
            },
        }

        return PipelineResponse(
            question=question,
            routing_decision="reasoning_path",
            analyzer=analyzer_res,
            evidence_bundle=evidence,
            facts_first=ff_v2,
            composer=None,  # ReasoningComposer ne renvoie pas le format ComposerResult standard
            verifier=None,
            channel2=None,
            self_correction=None,
            answer_text=comp.answer or "",
            total_latency_ms=int((time.time() - t0) * 1000),
            diagnostic={
                "reasoning_mode": True,
                "n_atomic_facts": len(unified.atomic_facts),
                "n_relational_facts": len(unified.relational_facts),
                "n_reasoning_steps": comp.n_steps,
                "n_steps_rejected": comp.n_steps_rejected,
                "answerability": unified.answerability,
                "abstention_reason": comp.abstention_reason,
                "reasoning_steps": comp.reasoning_steps,
                "citations": comp.citations,
                "reasoning_confidence": comp.reasoning_confidence,
                "structurer_model": unified.model,
                "composer_model": comp.model,
                "rerouter": rerouter_decision.to_dict() if rerouter_decision else None,
                "timing_ms": timing,
            },
        )


# Backward compatibility alias (Tranche 1 only callers)
FactsFirstListPipeline = FactsFirstPipeline
