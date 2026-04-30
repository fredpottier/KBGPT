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
from datetime import date as date_cls
from typing import Optional

from neo4j import Driver

from knowbase.anchor import AnchorExtractor, AnchorFilter, AnchorType, ResolvedAnchor
from knowbase.current import CurrentResolver, CurrentResolverDecision
from knowbase.runtime_v2.conflict_detector import ConflictDetector
from knowbase.runtime_v2.synthesis import ResponseSynthesizer
from knowbase.runtime_v2.models import (
    ConflictReport,
    EvidenceClaim,
    EvolutionPoint,
    PipelineDecision,
    PipelineResponse,
)
from knowbase.runtime_v2.retriever import ClaimRetriever

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

        # Étape 2 — Anchor Extractor
        anchor = self.anchor_extractor.extract(question)
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
        filter_result = self.anchor_filter.filter(anchor)
        diagnostic["filter"] = {
            "method": filter_result.method,
            "n_matched": filter_result.n_matched,
            "matched_doc_ids": filter_result.matched_doc_ids,
        }

        # Subject Resolver léger (P2.2) — pré-retrieval Qdrant + analyse de cohérence
        # Conformément à VISION §3 étape 1 : si les top docs partagent un cluster
        # sémantique cohérent → on a identifié le sujet implicite. Si mixed → ambigu.
        topic_info = self.retriever.topic_with_coherence(question, top_k_chunks=30, top_k_docs=6)
        topic_doc_ids = topic_info["doc_ids"]
        diagnostic["subject_resolver"] = {
            "n_topic_docs": len(topic_doc_ids),
            "top_topic_docs": topic_doc_ids[:3],
            "topic_consistent": topic_info["topic_consistent"],
            "topic_signature": topic_info["topic_signature"],
            "ambiguity_reason": topic_info["ambiguity_reason"],
        }

        # Si CURRENT_DEFAULT et sujet ambigu → escalade explicite
        # (sauf si l'Anchor Filter a déjà restreint le scope, auquel cas on continue)
        if (
            anchor.anchor_type == AnchorType.CURRENT_DEFAULT
            and not topic_info["topic_consistent"]
            and topic_info["topic_signature"] == "mixed"
            and len(topic_doc_ids) >= 3
        ):
            return PipelineResponse(
                decision=PipelineDecision.ESCALATE_AMBIGUOUS,
                question=question,
                anchor=anchor,
                escalation_message=(
                    f"La question pourrait porter sur plusieurs sujets distincts. "
                    f"{topic_info['ambiguity_reason']} Voulez-vous préciser ?"
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
            return PipelineResponse(
                decision=decision,
                question=question,
                anchor=anchor,
                authoritative_doc_ids=authoritative_doc_ids,
                evolution_points=evolution_points,
                trust_score=self._compute_trust_score(
                    anchor, filter_result.n_matched, len(evolution_points)
                ),
                diagnostic=diagnostic,
            )

        # POINT ou CURRENT_DEFAULT : retrieve top-K claims
        claims = self.retriever.retrieve(
            question, doc_ids=authoritative_doc_ids, top_k=top_k_claims
        )

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

        # P2.1 — Synthèse LLM finale (réponse prose 2-4 phrases)
        synthesized = self.synthesizer.synthesize(
            question=question,
            claims=[c.model_dump() for c in claims],
            unresolved_conflicts=[uc.model_dump() for uc in unresolved_conflicts],
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
