"""
Pipeline Runtime V2 — Orchestrateur 5 étapes (Vision §3, version sans Subject Resolver).

Subject Resolver (étape 1 de Vision §3) est déféré : son intégration nécessite
soit un sujet explicite passé par le user soit un retrieval pré-pipeline.
Pour V2-S4 minimaliste, on saute cette étape — l'Anchor Filter scanne tout le KG.

Pipeline effectif :
  Question
    → Anchor Extractor (V2-S2)
    → Anchor Filter (V2-S2)
    → Current Resolver (V2-S3) si CURRENT_DEFAULT
    → Retrieval Qdrant intra-scope (V2-S4)
    → Conflict Detector intra-anchor (V2-S4, si POINT/CURRENT)
    → Evolution Builder (V2-S4, si RANGE)
    → PipelineResponse
"""
from __future__ import annotations

import logging
import re
from datetime import date as date_cls
from typing import Optional

from neo4j import Driver

from knowbase.anchor import AnchorExtractor, AnchorFilter, AnchorType, ResolvedAnchor
from knowbase.current import CurrentResolver, CurrentResolverDecision
from knowbase.runtime_v2.conflict_detector import ConflictDetector
from knowbase.runtime_v2.synthesis import ResponseSynthesizer, EvolutionSynthesizer
from knowbase.runtime_v2.question_subject_resolver import QuestionSubjectResolver
from knowbase.runtime_v2.models import (
    ConflictReport,
    EvidenceClaim,
    EvolutionPoint,
    PipelineDecision,
    PipelineResponse,
)
from knowbase.runtime_v2.retriever import ClaimRetriever
from knowbase.api.services.query_decomposer import decompose_with_context, QueryPlan
from knowbase.runtime_v2.premise_validator import (
    validate_premise as _validate_premise,
    build_false_premise_response as _build_false_premise_response,
)
from knowbase.runtime_v2.hallucination_guard import (
    check_hallucination as _check_hallucination,
    build_hallucination_warning as _build_hallu_warning,
)
from knowbase.runtime_v2.lifecycle_filter import (
    apply_lifecycle_filter as _apply_lifecycle_filter,
)
from knowbase.runtime_v2.faithfulness_judge import (
    judge_faithfulness as _judge_faithfulness,
    should_regenerate as _should_regenerate,
    build_unsupported_warning as _build_unsupported_warning,
)

logger = logging.getLogger(__name__)


class RuntimeV2Pipeline:
    """Orchestrateur du pipeline Runtime V2 anchor-driven.

    Args:
        driver: Neo4j driver
        qdrant_client: Qdrant client
        embedder: SentenceTransformer
        vllm_url: vLLM URL (pour AnchorExtractor)
        tenant_id: tenant courant
    """

    def __init__(
        self,
        driver: Driver,
        qdrant_client,
        embedder,
        vllm_url: str,
        tenant_id: str = "default",
        collection_name: str = "knowbase_chunks_v2",
        vllm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
    ) -> None:
        self.driver = driver
        self.tenant_id = tenant_id
        self.anchor_extractor = AnchorExtractor(vllm_url=vllm_url, model_id=vllm_model)
        self.anchor_filter = AnchorFilter(driver=driver, tenant_id=tenant_id)
        self.current_resolver = CurrentResolver(driver=driver, tenant_id=tenant_id)
        self.retriever = ClaimRetriever(
            qdrant_client=qdrant_client,
            embedder=embedder,
            driver=driver,
            collection_name=collection_name,
            tenant_id=tenant_id,
        )
        self.conflict_detector = ConflictDetector(driver=driver, tenant_id=tenant_id)
        self.synthesizer = ResponseSynthesizer(vllm_url=vllm_url, model_id=vllm_model)
        # P5 polish — synthèse multi-mode (RANGE narration chronologique)
        self.evolution_synthesizer = EvolutionSynthesizer(vllm_url=vllm_url, model_id=vllm_model)
        # P5 polish — Subject Resolver V2 vrai (LLM + embedding cosine)
        self.subject_resolver = QuestionSubjectResolver(
            driver=driver,
            embedder=embedder,
            vllm_url=vllm_url,
            tenant_id=tenant_id,
            vllm_model=vllm_model,
        )

    def _emit_structured_log(
        self,
        request_id: str,
        question: str,
        response: PipelineResponse,
        latency_ms: float,
    ) -> None:
        """Émet un log JSON structuré pour Loki/Grafana (ADR_RUNTIME_V2_OPERATIONAL)."""
        try:
            import json as _json
            from datetime import datetime as _dt

            entry = {
                "ts": _dt.utcnow().isoformat() + "Z",
                "request_id": request_id,
                "event": "runtime_v2.answer",
                "question_len": len(question),
                "decision": response.decision.value,
                "anchor_type": response.anchor.anchor_type.value,
                "n_authoritative_docs": len(response.authoritative_doc_ids or []),
                "n_claims": len(response.claims or []),
                "n_conflicts": len(response.conflicts or []),
                "n_unresolved_conflicts": sum(
                    1 for c in (response.conflicts or [])
                    if not c.is_resolved_by_lifecycle
                ),
                "n_evolution_points": len(response.evolution_points or []),
                "trust_score": response.trust_score,
                "latency_ms": round(latency_ms, 1),
                "has_synthesis": bool(response.synthesized_answer),
            }
            # Format Loki-friendly : 1 ligne JSON
            logger.info(f"RUNTIME_V2_METRIC {_json.dumps(entry, default=str)}")
        except Exception as exc:
            logger.warning(f"Failed to emit structured log: {exc}")

    def answer(
        self,
        question: str,
        audit_mode: bool = False,
        as_of: Optional[date_cls] = None,
        top_k_claims: int = 10,
    ) -> PipelineResponse:
        """Execute le pipeline pour une question.

        Args:
            question: question utilisateur en langage naturel
            audit_mode: si True, retourne un AUDIT_REPORT avec les contradictions
                non résolues par lifecycle (utilisé par le toggle Audit du frontend)
            as_of: date pour le Current Resolver (default = today)
            top_k_claims: top-K claims à retourner

        Returns:
            PipelineResponse structurée selon la décision.
        """
        import time as _time
        import uuid as _uuid

        diagnostic = {}
        _t_start = _time.time()
        _request_id = _uuid.uuid4().hex[:12]
        # CH-32 latency profiling — ms par étape
        _stage_ms: dict[str, float] = {}
        def _mark(stage: str, t0: float) -> None:
            _stage_ms[stage] = round((_time.time() - t0) * 1000, 1)

        # Étape 2 — Anchor Extractor
        _t_anchor = _time.time()
        anchor = self.anchor_extractor.extract(question)
        _mark("anchor_extractor", _t_anchor)
        diagnostic["anchor"] = {
            "type": anchor.anchor_type.value,
            "scope": anchor.scope.model_dump(exclude_none=True),
            "extraction_method": anchor.extraction_method,
        }
        logger.info(
            "Pipeline V2 — anchor_type=%s scope=%s",
            anchor.anchor_type.value,
            anchor.scope.model_dump(exclude_none=True),
        )

        # Étape 3 — Anchor Filter
        _t_af = _time.time()
        filter_result = self.anchor_filter.filter(anchor)
        _mark("anchor_filter", _t_af)
        diagnostic["filter"] = {
            "method": filter_result.method,
            "n_matched": filter_result.n_matched,
            "matched_doc_ids": filter_result.matched_doc_ids,
        }

        # P5 polish — Subject Resolver V2 vrai (LLM + embedding cosine vs primary_subject KG)
        # Remplace topic_with_coherence léger. Cf VISION_RECENTREE §3 étape 1.
        _t_sr = _time.time()
        try:
            sr_result = self.subject_resolver.resolve(question, cosine_threshold=0.55, top_k=5)
            subject_extraction = sr_result.extraction
            topic_doc_ids = sr_result.consolidated_doc_ids
            sr_ambiguous = sr_result.is_ambiguous
            sr_ambig_reason = sr_result.ambiguity_reason
        except Exception as sr_exc:
            logger.warning(f"QuestionSubjectResolver failed, falling back to retriever.topic_with_coherence: {sr_exc}")
            fallback = self.retriever.topic_with_coherence(question, top_k_chunks=30, top_k_docs=6)
            topic_doc_ids = fallback["doc_ids"]
            sr_ambiguous = not fallback["topic_consistent"] and fallback["topic_signature"] == "mixed"
            sr_ambig_reason = fallback["ambiguity_reason"]
            subject_extraction = None

        _mark("subject_resolver", _t_sr)

        diagnostic["subject_resolver"] = {
            "method": "QuestionSubjectResolver V2" if subject_extraction else "fallback_topic_coherence",
            "subject_label": subject_extraction.subject_label if subject_extraction else None,
            "subject_confidence": subject_extraction.confidence if subject_extraction else None,
            "n_consolidated_docs": len(topic_doc_ids),
            "top_docs": topic_doc_ids[:3],
            "is_ambiguous": sr_ambiguous,
            "ambiguity_reason": sr_ambig_reason,
        }

        # Si CURRENT_DEFAULT et sujet **vraiment** ambigu (LLM a flagué la question elle-même)
        # → escalade explicite. La pluralité d'aliases dans le KG ne suffit pas (data quality).
        question_truly_ambiguous = (
            subject_extraction is not None and subject_extraction.is_ambiguous
        )
        if (
            anchor.anchor_type == AnchorType.CURRENT_DEFAULT
            and question_truly_ambiguous
            and len(topic_doc_ids) >= 2
        ):
            return PipelineResponse(
                decision=PipelineDecision.ESCALATE_AMBIGUOUS,
                question=question,
                anchor=anchor,
                escalation_message=(
                    f"La question pourrait porter sur plusieurs sujets distincts. "
                    f"{sr_ambig_reason or ''} Voulez-vous préciser ?"
                ),
                alternatives=[{"doc_id": d, "confidence": 0.5} for d in topic_doc_ids[:5]],
                diagnostic=diagnostic,
            )

        # Si POINT / RANGE et Anchor Filter retourne une liste vide → fallback Qdrant topic
        if (
            filter_result.matched_doc_ids is not None
            and len(filter_result.matched_doc_ids) == 0
        ):
            if topic_doc_ids:
                # Fallback : la question portait un anchor explicite mais aucun doc ne matche
                # → on dégrade vers le sujet implicite + Current Resolver
                logger.info(
                    "Anchor %s returned 0 docs — falling back to topic pre-retrieval (%d docs)",
                    anchor.anchor_type.value,
                    len(topic_doc_ids),
                )
                filter_result.matched_doc_ids = topic_doc_ids
                anchor.anchor_type = AnchorType.CURRENT_DEFAULT
                diagnostic["filter"]["fallback_to_topic"] = True
            else:
                return PipelineResponse(
                    decision=PipelineDecision.ESCALATE_NO_DOCS,
                    question=question,
                    anchor=anchor,
                    escalation_message=(
                        f"Aucune information dans le corpus pour ce cadre "
                        f"({anchor.scope.model_dump(exclude_none=True)}). "
                        f"Voulez-vous élargir le scope ?"
                    ),
                    diagnostic=diagnostic,
                )

        # Étape 4 — Current Resolver si CURRENT_DEFAULT
        authoritative_doc_ids: list[str]
        cr_alternatives: list[dict] = []
        decision: PipelineDecision

        if anchor.anchor_type == AnchorType.CURRENT_DEFAULT:
            # CURRENT_DEFAULT : Anchor Filter ne restreint pas → on utilise
            # le pré-retrieval Qdrant (sujet implicite) comme scope du Current Resolver.
            # Si le pré-retrieval n'a rien retourné → on tombe sur tout le corpus.
            cr_candidate_ids = (
                filter_result.matched_doc_ids
                if filter_result.matched_doc_ids is not None
                else (topic_doc_ids if topic_doc_ids else None)
            )
            cr_result = self.current_resolver.resolve(
                candidate_doc_ids=cr_candidate_ids,
                as_of=as_of,
            )
            diagnostic["current_resolver"] = {
                "decision": cr_result.decision.value,
                "n_phase1": cr_result.n_filtered_in_phase1,
                "top_confidence": cr_result.top_candidate.confidence
                if cr_result.top_candidate
                else None,
            }

            if cr_result.decision == CurrentResolverDecision.NOT_FOUND:
                return PipelineResponse(
                    decision=PipelineDecision.ESCALATE_NO_DOCS,
                    question=question,
                    anchor=anchor,
                    escalation_message="Aucun document actif pour ce sujet à la date courante.",
                    diagnostic=diagnostic,
                )

            if cr_result.decision == CurrentResolverDecision.ESCALATE_AMBIGUOUS:
                return PipelineResponse(
                    decision=PipelineDecision.ESCALATE_AMBIGUOUS,
                    question=question,
                    anchor=anchor,
                    escalation_message=(
                        f"Plusieurs sources actives sur ce sujet sans hiérarchie claire. "
                        f"Précisez votre demande (top_confidence={cr_result.top_candidate.confidence:.2f})."
                    ),
                    alternatives=[
                        {"doc_id": c.doc_id, "confidence": c.confidence}
                        for c in [cr_result.top_candidate, *cr_result.alternatives][:5]
                        if c
                    ],
                    diagnostic=diagnostic,
                )

            authoritative_doc_ids = [cr_result.top_candidate.doc_id]
            if cr_result.decision == CurrentResolverDecision.SUGGEST_WITH_ALTERNATIVES:
                cr_alternatives = [
                    {"doc_id": c.doc_id, "confidence": c.confidence}
                    for c in cr_result.alternatives[:5]
                ]
            decision = PipelineDecision.ANSWERED_AUTHORITATIVE

        elif anchor.anchor_type == AnchorType.POINT:
            authoritative_doc_ids = filter_result.matched_doc_ids or []
            decision = PipelineDecision.ANSWERED_SCOPED

        elif anchor.anchor_type == AnchorType.RANGE:
            authoritative_doc_ids = filter_result.matched_doc_ids or []
            # Intersect avec topic_doc_ids si le sujet a été résolu :
            # évite de mélanger CS-25 et EU dual-use juste parce qu'ils partagent
            # une fenêtre temporelle. On ne réduit que si l'intersection est non vide.
            if topic_doc_ids and authoritative_doc_ids:
                topic_set = set(topic_doc_ids)
                intersected = [d for d in authoritative_doc_ids if d in topic_set]
                if intersected:
                    diagnostic["filter"]["intersected_with_subject"] = True
                    diagnostic["filter"]["before_intersect"] = len(authoritative_doc_ids)
                    diagnostic["filter"]["after_intersect"] = len(intersected)
                    authoritative_doc_ids = intersected
            decision = PipelineDecision.ANSWERED_EVOLUTION

        else:
            return PipelineResponse(
                decision=PipelineDecision.NOT_FOUND,
                question=question,
                anchor=anchor,
                diagnostic=diagnostic,
            )

        # Étape 5/6 — Retrieval claims dans le scope
        if anchor.anchor_type == AnchorType.RANGE:
            # Evolution Builder : retrieve par doc, sortir une timeline
            chrono = self.retriever.retrieve_chronological(
                question, authoritative_doc_ids, top_k_per_doc=3
            )
            evolution_points = self._build_evolution_timeline(chrono)

            # P5 polish — synthèse RANGE multi-mode
            evolution_synthesis = self.evolution_synthesizer.synthesize(
                question=question,
                evolution_points=[
                    {
                        "doc_id": ep.doc_id,
                        "publication_date": ep.publication_date,
                        "claims": [{"text": c.text} for c in ep.claims],
                    }
                    for ep in evolution_points
                ],
            )

            return PipelineResponse(
                decision=decision,
                question=question,
                anchor=anchor,
                authoritative_doc_ids=authoritative_doc_ids,
                evolution_points=evolution_points,
                synthesized_answer=evolution_synthesis,
                trust_score=self._compute_trust_score(
                    anchor, filter_result.n_matched, len(evolution_points)
                ),
                diagnostic=diagnostic,
            )

        # POINT ou CURRENT_DEFAULT : retrieve top-K claims
        # CH-31.A+B — Decomposer V2 enrichi (always-on, domain-agnostic) :
        # answer_shape + HyDE + must_contain + KG subject expansion.
        subject_label_for_dec = (
            subject_extraction.subject_label if subject_extraction else None
        )
        subject_aliases_for_dec = (
            list(subject_extraction.alternative_subjects)
            if subject_extraction and subject_extraction.alternative_subjects
            else None
        )
        _t_dec = _time.time()
        try:
            plan: QueryPlan = decompose_with_context(
                question,
                subject_label=subject_label_for_dec,
                subject_aliases=subject_aliases_for_dec,
            )
        except Exception as dec_exc:
            logger.warning("Decomposer V2 failed, falling back to simple retrieve: %s", dec_exc)
            plan = None
        _mark("decomposer", _t_dec)

        def _retrieve_text_for(sq) -> str:
            """HyDE augmentation : concat question + hypothetical answer pour embedding."""
            if sq.hyde_text:
                return f"{sq.text}\n{sq.hyde_text}"
            return sq.text

        _t_retr = _time.time()
        if plan and len(plan.sub_queries) > 1:
            n_sub = len(plan.sub_queries)
            per_sub_k = max(3, (top_k_claims * 2 + n_sub - 1) // n_sub)
            merged: dict[str, "EvidenceClaim"] = {}
            sub_diag: list[dict] = []
            for sq in plan.sub_queries:
                sub_claims = self.retriever.retrieve(
                    _retrieve_text_for(sq),
                    doc_ids=authoritative_doc_ids,
                    top_k=per_sub_k,
                )
                for c in sub_claims:
                    prev = merged.get(c.claim_id)
                    if prev is None or c.score > prev.score:
                        merged[c.claim_id] = c
                sub_diag.append({
                    "id": sq.id,
                    "text": sq.text[:120],
                    "scope_filter": sq.scope_filter,
                    "answer_shape": sq.answer_shape,
                    "has_hyde": bool(sq.hyde_text),
                    "must_contain": sq.must_contain,
                    "n_retrieved": len(sub_claims),
                })
            claims = sorted(merged.values(), key=lambda c: c.score, reverse=True)[:top_k_claims]
            diagnostic["decomposer"] = {
                "version": "v2",
                "plan_type": plan.plan_type,
                "synthesis_strategy": plan.synthesis_strategy,
                "n_sub_queries": n_sub,
                "reasoning": plan.reasoning,
                "sub_queries": sub_diag,
                "n_unique_claims_after_merge": len(merged),
                "subject_label": subject_label_for_dec,
            }
            logger.info(
                "Pipeline V2 — decomposed plan=%s n_sub=%d → %d unique claims (top-%d kept)",
                plan.plan_type, n_sub, len(merged), len(claims),
            )
        else:
            # Plan simple (1 sub_query) : on bénéficie quand même de HyDE
            # et on capture answer_shape + must_contain pour CH-31.C.
            sq0 = plan.sub_queries[0] if (plan and plan.sub_queries) else None
            retrieve_text = _retrieve_text_for(sq0) if sq0 else question
            claims = self.retriever.retrieve(
                retrieve_text, doc_ids=authoritative_doc_ids, top_k=top_k_claims
            )
            diagnostic["decomposer"] = {
                "version": "v2",
                "plan_type": plan.plan_type if plan else "simple",
                "n_sub_queries": 1,
                "answer_shape": sq0.answer_shape if sq0 else "narrative",
                "has_hyde": bool(sq0 and sq0.hyde_text),
                "must_contain": sq0.must_contain if sq0 else [],
                "subject_label": subject_label_for_dec,
            }
        _mark("retrieve", _t_retr)

        # CH-33 — PHASE VERIF parallèle : LLM-filter (CH-31.C) + Premise Validator (CH-32.A).
        # Ces deux étapes sont indépendantes (filter agit sur claims, premise sur question
        # + retriever séparé). Lancées en parallèle via ThreadPoolExecutor pour gagner
        # max(filter, premise) au lieu de leur somme.
        from knowbase.runtime_v2.llm_filter import filter_claims as _llm_filter
        import concurrent.futures as _cf

        # Pré-calcul answer_shape + must_contain pour le filter
        dec = diagnostic.get("decomposer", {})
        if "sub_queries" in dec and dec["sub_queries"]:
            must_agg: list[str] = []
            shape_priority = [
                "factual_value", "entity_lookup", "boolean", "definition",
                "relationship", "enumeration", "narrative",
            ]
            shapes_present = []
            for sq in dec["sub_queries"]:
                must_agg.extend(sq.get("must_contain") or [])
                s = sq.get("answer_shape") or "narrative"
                shapes_present.append(s)
            seen = set()
            must_agg_dedup = []
            for t in must_agg:
                tn = t.strip().lower()
                if tn and tn not in seen:
                    seen.add(tn)
                    must_agg_dedup.append(t)
            answer_shape = next(
                (s for s in shape_priority if s in shapes_present),
                "narrative",
            )
            must_contain_agg = must_agg_dedup
        else:
            answer_shape = dec.get("answer_shape", "narrative")
            must_contain_agg = list(dec.get("must_contain") or [])
        eff_min_keep = 5 if answer_shape in {"factual_value", "definition", "boolean"} else 3

        def _run_filter():
            if not claims or audit_mode:
                return None
            return _llm_filter(
                question=question,
                claims=list(claims),
                answer_shape=answer_shape,
                must_contain=must_contain_agg,
                min_keep=eff_min_keep,
                max_input_claims=min(12, len(claims)),
            )

        def _run_premise():
            try:
                return _validate_premise(
                    question=question,
                    retriever=self.retriever,
                    doc_ids=authoritative_doc_ids,
                )
            except Exception as e:
                logger.warning("Premise validator failed inside parallel: %s", e)
                return None

        _t_parallel = _time.time()
        with _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="verif") as _ex:
            _fut_filt = _ex.submit(_run_filter)
            _fut_premise = _ex.submit(_run_premise)
            filt = _fut_filt.result()
            premise_validation = _fut_premise.result()
        _mark("verif_parallel", _t_parallel)

        # Post-process FILTER
        if filt is not None:
            claims = filt["kept"]
            diagnostic["llm_filter"] = {
                "n_input": filt["n_input"],
                "n_kept": filt["n_kept"],
                "n_dropped": filt["n_dropped"],
                "llm_called": filt["llm_called"],
                "fallback_reason": filt["fallback_reason"],
                "answer_shape_used": answer_shape,
                "must_contain_used": must_contain_agg,
                "grades": filt.get("grades", {}),
            }

        # Post-process PREMISE
        false_premise_response: Optional[str] = None
        if premise_validation is not None:
            diagnostic["premise_validator"] = {
                "n_presuppositions": premise_validation.n_presuppositions,
                "has_false_premise": premise_validation.has_false_premise,
                "presuppositions": [
                    {
                        "text": p.presupposition[:200],
                        "verdict": p.verdict,
                        "confidence": round(p.confidence, 2),
                        "reasoning": p.reasoning[:160],
                        "n_contradicting": len(p.contradicting_evidence),
                        "n_supporting": len(p.supporting_evidence),
                    }
                    for p in premise_validation.presuppositions
                ],
                "diagnostic": premise_validation.diagnostic,
            }
            if premise_validation.has_false_premise:
                false_premise_response = _build_false_premise_response(question, premise_validation)
        else:
            diagnostic["premise_validator"] = {"error": "internal_error_in_parallel"}

        # Conflict Detector intra-anchor
        # En mode normal : on consulte mais on filtre les résolus par lifecycle
        # En mode Audit : on remonte tous les conflicts (résolus ou non)
        all_conflicts = self.conflict_detector.detect(authoritative_doc_ids)

        if audit_mode:
            # AUDIT REPORT : on bypasse les claims, on rend les conflicts
            return PipelineResponse(
                decision=PipelineDecision.AUDIT_REPORT,
                question=question,
                anchor=anchor,
                authoritative_doc_ids=authoritative_doc_ids,
                claims=claims,
                conflicts=all_conflicts,
                trust_score=1.0 if not all_conflicts else 0.5,
                diagnostic=diagnostic,
            )

        # Mode normal : ne remonter que les conflicts non résolus par lifecycle
        unresolved_conflicts = [c for c in all_conflicts if not c.is_resolved_by_lifecycle]

        # CH-13 — Answer Gap Detector (avant synthèse, signal pré-LLM)
        from knowbase.runtime_v2.answer_gap_detector import detect_answer_gap
        retrieved_text = " ".join((c.text or "")[:600] for c in claims)
        gap_info = detect_answer_gap(question=question, retrieved_text=retrieved_text)

        # CH-37 C.1 — Lifecycle filter avant synthèse (démote DEPRECATED si current intent)
        _t_lifecycle = _time.time()
        try:
            lifecycle_result = _apply_lifecycle_filter(
                question=question,
                claims=claims,
                driver=self.driver,
                tenant_id=self.tenant_id,
            )
            if lifecycle_result["applied"]:
                claims = lifecycle_result["claims"]
                diagnostic["lifecycle_filter"] = {
                    "applied": True,
                    "current_intent": True,
                    "n_deprecated_demoted": lifecycle_result["n_deprecated_demoted"],
                    "lifecycle_map": lifecycle_result["lifecycle_map"],
                }
            else:
                diagnostic["lifecycle_filter"] = {
                    "applied": False,
                    "current_intent": lifecycle_result["current_intent"],
                }
        except Exception as lf_exc:
            logger.warning("Lifecycle filter failed: %s", lf_exc)
            diagnostic["lifecycle_filter"] = {"error": f"{type(lf_exc).__name__}"}
        _mark("lifecycle_filter", _t_lifecycle)

        # P2.1 — Synthèse LLM finale (réponse prose 2-4 phrases)
        _t_synth = _time.time()
        if false_premise_response:
            # Bypass synthesizer : on retourne directement le rejet de prémisse.
            synthesized = false_premise_response
            diagnostic["synthesis_bypassed"] = "false_premise"
        else:
            synthesized = self.synthesizer.synthesize(
                question=question,
                claims=[c.model_dump() for c in claims],
                unresolved_conflicts=[uc.model_dump() for uc in unresolved_conflicts],
            )
        _mark("synthesizer", _t_synth)

        # CH-14 — récupérer entropy depuis last_metrics du synthesizer
        from knowbase.runtime_v2.entropy import is_low_confidence
        synth_metrics = getattr(self.synthesizer, "last_metrics", {}) or {}
        synth_entropy = synth_metrics.get("entropy")

        # CH-32.B — Faithfulness NLI judge post-synthèse.
        # Skip si false_premise (réponse pré-formatée, pas de claims factuels à juger)
        # ou si réponse < 30 chars.
        faithfulness_report = None
        regenerated = False
        _t_faith = _time.time()
        if not false_premise_response and synthesized and len(synthesized) >= 30:
            try:
                faithfulness_report = _judge_faithfulness(
                    answer=synthesized,
                    claims=claims,
                )
                # Régénération conditionnelle (CH-33 : politique équilibrée)
                if _should_regenerate(faithfulness_report):
                    logger.info(
                        "Faithfulness %.2f (%s) below threshold — regenerating with strict prompt",
                        faithfulness_report.overall_faithfulness,
                        faithfulness_report.overall_verdict,
                    )
                    # Régénération via RuntimeLLMClient direct avec instruction stricte
                    try:
                        from knowbase.runtime_v2.llm_client import get_runtime_llm_client
                        strict_system = (
                            "You are a documentary synthesis assistant. STRICT MODE: "
                            "answer the question USING ONLY information explicitly present in the "
                            "evidence claims provided. If the evidence does not contain the answer, "
                            "say so plainly and DO NOT restate the question's assumption as fact. "
                            "Do NOT invent values, dates, identifiers. Cite each factual statement "
                            "with [doc=<doc_id>]. Match the question's language. 2-4 sentences max."
                        )
                        # Liste les claims UNSUPPORTED de la réponse précédente pour
                        # que le LLM les évite explicitement à la régénération.
                        unsupported_block = ""
                        unsup = [
                            ac for ac in faithfulness_report.atomic_claims
                            if ac.verdict == "UNSUPPORTED"
                        ]
                        if unsup:
                            unsupported_block = (
                                "\n\nThe previous draft contained statements NOT supported by "
                                "the evidence. Do NOT repeat them:\n"
                                + "\n".join(f"  - {ac.claim[:200]}" for ac in unsup[:5])
                            )
                        ev_block = "\n".join(
                            f"[{i+1}] doc={c.doc_id} {(c.text or '')[:500]}"
                            for i, c in enumerate(claims[:8])
                        )
                        strict_user = (
                            f"Question: {question}\n\n"
                            f"Evidence:\n{ev_block}\n"
                            f"{unsupported_block}\n\n"
                            f"Answer strictly from the evidence above. If the question presumes a "
                            f"fact the evidence does not support, flag this explicitly rather than "
                            f"restating the presumption."
                        )
                        # Régénération sur le modèle synthesizer (Qwen-72B) pour
                        # garder la qualité user-facing — pas Mistral-Small.
                        regen = get_runtime_llm_client().chat_completion(
                            messages=[
                                {"role": "system", "content": strict_system},
                                {"role": "user", "content": strict_user},
                            ],
                            temperature=0.0,
                            max_tokens=350,
                            timeout=60.0,
                        )
                        if regen and len(regen.strip()) >= 20:
                            # CH-33 fix : ne PAS écraser la réponse initiale si
                            # la régen produit une abstention (faux négatif du
                            # faithfulness judge sur des inférences implicites).
                            # Détection : pattern lexical d'abstention (FR/EN).
                            regen_clean = regen.strip()
                            abstention_markers = [
                                "ne fournit pas",
                                "ne contient pas",
                                "n'est pas explicitement mentionn",
                                "n'est pas directement mentionn",
                                "n'est pas précis",
                                "n'est pas clairement indiqu",
                                "ne précise pas",
                                "ne mentionne pas",
                                "does not provide",
                                "does not contain",
                                "is not explicitly",
                                "is not directly mentioned",
                                "is not specified",
                                "is not stated",
                                "does not specify",
                                "does not mention",
                            ]
                            regen_low = regen_clean.lower()
                            regen_is_abstention = any(m in regen_low for m in abstention_markers)
                            initial_was_abstention = any(m in (synthesized or "").lower() for m in abstention_markers)

                            # Garder la régen seulement si elle ne dégrade pas (CH-33 fix v2 + CH-36 B.3) :
                            # - Si la PRESUPPOSITION de la question est SUPPORTED par
                            #   l'evidence ET initial substantiel ET régen abstient
                            #   → garder initial (cas T7 : inférence implicite faux négatif)
                            # - Si la presupposition est NEUTRAL (incertain, pas contredite)
                            #   et initial substantiel → garder initial (CH-36 B.3 fix :
                            #   un premise NEUTRAL ne doit pas forcer abstention quand l'initial cite
                            #   des doc_ids et que la régen abstient. C'était le bug majeur diagnostiqué
                            #   sur le cas "428/2009 abrogé/remplacé" où l'evidence dit "is repealed"
                            #   en EN et la presupposition FR n'était pas matchée.)
                            # - Si la presupposition est explicitement CONTRADICTS
                            #   → laisser la régen abstenir (cas T6 : fausse prémisse)
                            # - Si initial déjà abstentif → toujours adopter la régen
                            premise_supports = False
                            premise_explicitly_contradicts = False
                            if premise_validation and premise_validation.presuppositions:
                                premise_supports = any(
                                    p.verdict == "SUPPORTS" and p.confidence >= 0.5
                                    for p in premise_validation.presuppositions
                                )
                                premise_explicitly_contradicts = any(
                                    p.verdict == "CONTRADICTS" and p.confidence >= 0.5
                                    for p in premise_validation.presuppositions
                                )
                            # Heuristique : initial cite des doc_ids → c'est substantiel et evidence-locked
                            initial_cites_docs = bool(re.search(r"\[doc=", synthesized or ""))
                            # Skip régen quand :
                            # - initial substantiel (pas abstention) ET cite des docs
                            # - régen produit abstention
                            # - premise n'est pas EXPLICITEMENT contredite
                            should_skip_regen = (
                                regen_is_abstention
                                and not initial_was_abstention
                                and not premise_explicitly_contradicts
                                and (premise_supports or initial_cites_docs)
                            )
                            if should_skip_regen:
                                logger.info(
                                    "Regen produced abstention but initial substantive + premise OK — keeping initial."
                                )
                                regenerated = False
                                diagnostic.setdefault(
                                    "faithfulness_regen_skip_reason",
                                    "regen_abstention_initial_substantive_premise_ok",
                                )
                            else:
                                synthesized = regen_clean
                                regenerated = True
                                if regen_is_abstention:
                                    diagnostic.setdefault(
                                        "faithfulness_regen_adopted_reason",
                                        "premise_unsupported_or_initial_already_abstention",
                                    )
                            # Pas de re-judge post-regen (CH-33 : économie ~5-7s).
                    except Exception as regen_exc:
                        logger.warning("Strict regeneration failed: %s", regen_exc)

                diagnostic["faithfulness"] = {
                    "verdict": faithfulness_report.overall_verdict,
                    "score": round(faithfulness_report.overall_faithfulness, 3),
                    "n_supported": faithfulness_report.n_supported,
                    "n_unsupported": faithfulness_report.n_unsupported,
                    "n_neutral": faithfulness_report.n_neutral,
                    "n_factual": faithfulness_report.n_factual,
                    "regenerated": regenerated,
                    "fallback_reason": faithfulness_report.fallback_reason,
                    "atomic_claims": [
                        {
                            "claim": ac.claim[:160],
                            "verdict": ac.verdict,
                            "confidence": round(ac.confidence, 2),
                            "reasoning": ac.reasoning[:120],
                        }
                        for ac in faithfulness_report.atomic_claims
                    ],
                }
            except Exception as fj_exc:
                logger.warning("Faithfulness judge failed: %s", fj_exc)
                diagnostic["faithfulness"] = {"error": f"{type(fj_exc).__name__}: {fj_exc}"}
        _mark("faithfulness_judge", _t_faith)

        # CH-36 B.4 / CH-37 C.3 — Hallucination guard (lexical, déterministe, ~5ms)
        # Vérifie que les tokens factuels critiques (regulation_id, dates, valeurs+unité,
        # articles, CS codes, NPA refs) présents dans la réponse existent dans les chunks.
        # Si hallucination détectée, on AJOUTE un avertissement à la réponse (pas de regen
        # automatique pour éviter de détruire les bons cas — l'utilisateur voit le warning).
        _t_hallu = _time.time()
        if synthesized and claims:
            try:
                hallu_report = _check_hallucination(synthesized, claims)
                diagnostic["hallucination_guard"] = {
                    "n_total_factual": hallu_report.n_total_factual,
                    "n_verified": hallu_report.n_verified,
                    "n_hallucinated": hallu_report.n_hallucinated,
                    "has_hallucination": hallu_report.has_hallucination,
                    "confidence": round(hallu_report.confidence, 3),
                    "hallucinated_tokens": [
                        {"token": t.token, "type": t.token_type}
                        for t in hallu_report.hallucinated[:10]
                    ],
                }
                # Si hallucination détectée ET réponse non-abstentive,
                # injecter un warning visible dans la réponse synthétisée.
                if hallu_report.has_hallucination:
                    is_substantive = not any(
                        m in (synthesized or "").lower()
                        for m in [
                            "ne fournit pas", "ne contient pas", "n'est pas explicitement",
                            "does not provide", "does not contain", "is not specified",
                        ]
                    )
                    if is_substantive:
                        warning = _build_hallu_warning(hallu_report)
                        if warning:
                            synthesized = f"{synthesized}\n\n{warning}"
            except Exception as hg_exc:
                logger.warning("Hallucination guard failed: %s", hg_exc)
                diagnostic["hallucination_guard"] = {"error": f"{type(hg_exc).__name__}"}
        _mark("hallucination_guard", _t_hallu)

        # Total + breakdown
        _stage_ms["TOTAL_pipeline_ms"] = round((_time.time() - _t_start) * 1000, 1)
        diagnostic["latency_ms"] = _stage_ms
        logger.info(
            "Pipeline V2 latency_ms: %s",
            ", ".join(f"{k}={v}" for k, v in _stage_ms.items()),
        )

        return PipelineResponse(
            decision=decision,
            question=question,
            anchor=anchor,
            authoritative_doc_ids=authoritative_doc_ids,
            claims=claims,
            conflicts=unresolved_conflicts,
            alternatives=cr_alternatives,
            synthesized_answer=synthesized,
            synthesis_entropy=synth_entropy,
            synthesis_low_confidence=is_low_confidence(synth_entropy),
            answer_gap_score=gap_info.get("gap_score"),
            answer_gap_classification=gap_info.get("classification"),
            answer_gap_missing_terms=gap_info.get("missing", [])[:10],
            trust_score=self._compute_trust_score(
                anchor, len(authoritative_doc_ids), len(claims), len(unresolved_conflicts)
            ),
            trust_breakdown={
                "anchor_confidence": anchor.confidence,
                "n_claims_retrieved": len(claims),
                "n_unresolved_conflicts": len(unresolved_conflicts),
                "n_resolved_conflicts": len(all_conflicts) - len(unresolved_conflicts),
            },
            diagnostic=diagnostic,
        )

    @staticmethod
    def _build_evolution_timeline(
        chrono: dict[str, list[EvidenceClaim]]
    ) -> list[EvolutionPoint]:
        """Construit la timeline triée par publication_date."""
        points: list[EvolutionPoint] = []
        for doc_id, claims in chrono.items():
            pub_date = claims[0].publication_date if claims else None
            points.append(
                EvolutionPoint(
                    doc_id=doc_id,
                    publication_date=pub_date,
                    claims=claims,
                )
            )
        # Tri chronologique (None à la fin)
        points.sort(key=lambda p: (p.publication_date or "9999"))
        return points

    @staticmethod
    def _compute_trust_score(
        anchor: ResolvedAnchor,
        n_docs_in_scope: int,
        n_claims_or_points: int,
        n_unresolved_conflicts: int = 0,
    ) -> float:
        """Score de confiance composite simple.

        - Élevé : anchor confidence haute + 1+ claims/points + 0 unresolved conflict
        - Diminué par : conflicts non résolus, peu de claims, anchor confidence basse
        """
        base = anchor.confidence
        if n_claims_or_points == 0:
            return base * 0.3
        if n_unresolved_conflicts > 0:
            return base * 0.5
        if n_docs_in_scope == 1:
            return min(1.0, base * 1.05)
        return base
