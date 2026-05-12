"""
Runtime V3 Pipeline — CH-39.3.

5 stages clean :
1. Hybrid retrieve (reuse runtime_v2.retriever — proven)
2. Cross-encoder rerank (already in retriever.py via RERANK_ENABLED)
3. Agentic synthesis (1 LLM call, structured JSON output)
4. NLI faithfulness judge (mDeBERTa-v3 multilingual)
5. Regen conditional (1× max if UNFAITHFUL with score < 0.5)

Total ~250 lines vs 951 in runtime_v2.
NO hardcoded lists, NO domain-specific regex, NO multi-LLM stages.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from neo4j import Driver

# Reuse proven retriever from v2 (hybrid + rerank GPU, domain-agnostic)
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.runtime_v3.synthesis import (
    SynthesisOutput,
    synthesize as _synthesize,
    regenerate_with_feedback as _regenerate,
)
from knowbase.runtime_v3.nli_judge import (
    FaithfulnessReport,
    judge_faithfulness as _judge_faithfulness,
    should_regenerate as _should_regenerate,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineV3Response:
    """Response unifiée pipeline V3 — output JSON structuré."""
    question: str
    decision: str  # ANSWER | REJECT_FALSE_PREMISE | ABSTAIN
    answer: str
    false_premise_detected: bool = False
    false_premise_correction: Optional[str] = None
    abstention_reason: Optional[str] = None
    doc_ids_cited: list[str] = field(default_factory=list)
    subject: str = ""
    presupposition_check: str = ""
    confidence: float = 0.0
    # Faithfulness
    faithfulness_score: float = 0.0
    faithfulness_verdict: str = "UNKNOWN"
    n_claims_supported: int = 0
    n_claims_unsupported: int = 0
    # Diagnostics
    n_chunks_retrieved: int = 0
    chunks_used: list[dict] = field(default_factory=list)  # CH-39 — exposé pour bench RAGAS
    regenerated: bool = False
    latency_breakdown_ms: dict = field(default_factory=dict)


class RuntimeV3Pipeline:
    """Pipeline V3 minimaliste — 5 stages, vraiment domain-agnostic."""

    def __init__(
        self,
        qdrant_client,
        embedder,
        driver: Driver,
        collection_name: str = "knowbase_chunks_v2",
        tenant_id: str = "default",
        top_k_retrieve: int = 10,
        regen_threshold: float = 0.5,
    ) -> None:
        self.driver = driver
        self.tenant_id = tenant_id
        self.top_k_retrieve = top_k_retrieve
        self.regen_threshold = regen_threshold
        self.retriever = ClaimRetriever(
            qdrant_client=qdrant_client,
            embedder=embedder,
            driver=driver,
            collection_name=collection_name,
            tenant_id=tenant_id,
        )

    def answer(self, question: str, top_k: Optional[int] = None) -> PipelineV3Response:
        """Pipeline 5 stages.

        Args:
            question: question utilisateur
            top_k: override pour nb chunks retrieved (default self.top_k_retrieve)

        Returns:
            PipelineV3Response avec answer + diagnostic.
        """
        latencies: dict[str, float] = {}
        t_start = time.time()
        top_k = top_k or self.top_k_retrieve

        # ── Stage 1+2 : Hybrid retrieve + rerank GPU ──────────────────────
        t = time.time()
        try:
            claims = self.retriever.retrieve(question=question, doc_ids=None, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            logger.error("[V3] retrieve failed: %s", exc)
            claims = []
        latencies["retrieve_rerank"] = round((time.time() - t) * 1000, 1)

        # Enrich with metadata (lifecycle_status, publication_date) from Neo4j
        if claims:
            t = time.time()
            try:
                self._enrich_metadata(claims)
            except Exception as exc:
                logger.warning("[V3] metadata enrichment failed: %s", exc)
            latencies["enrich_metadata"] = round((time.time() - t) * 1000, 1)

        # ── Stage 3 : Agentic synthesis ──────────────────────────────────
        t = time.time()
        synth = _synthesize(question=question, claims=claims)
        latencies["synthesis"] = round((time.time() - t) * 1000, 1)

        # Si synthesis a abstenu ou détecté fausse prémisse, pas besoin de juger
        if synth.decision in {"ABSTAIN", "REJECT_FALSE_PREMISE"}:
            return self._build_response(
                question=question, synth=synth, faith=None, regenerated=False,
                claims=claims, latencies=latencies, t_start=t_start,
            )

        # ── Stage 4 : NLI faithfulness judge ──────────────────────────────
        t = time.time()
        faith = _judge_faithfulness(answer=synth.answer, claims=claims)
        latencies["faithfulness_nli"] = round((time.time() - t) * 1000, 1)

        # ── Stage 5 : Regen conditionnel ──────────────────────────────────
        regenerated = False
        if _should_regenerate(faith, threshold=self.regen_threshold):
            logger.info("[V3] regenerating (faith=%.2f)", faith.overall_score)
            t = time.time()
            unsupported_claims = [
                cv.claim for cv in faith.claim_verdicts if cv.verdict == "UNSUPPORTED"
            ][:3]
            feedback = (
                f"NLI faithfulness verdict: {faith.overall_verdict} (score {faith.overall_score:.2f}). "
                f"{faith.n_unsupported}/{faith.n_claims} claims unsupported. "
            )
            if unsupported_claims:
                feedback += f"Notably unsupported: {' | '.join(unsupported_claims)}"
            synth_regen = _regenerate(
                question=question, claims=claims,
                previous_output=synth, faithfulness_feedback=feedback,
            )
            latencies["regenerate"] = round((time.time() - t) * 1000, 1)

            # Re-judge if regen produced substantive answer
            if synth_regen.decision == "ANSWER":
                t = time.time()
                faith_regen = _judge_faithfulness(answer=synth_regen.answer, claims=claims)
                latencies["faithfulness_nli_regen"] = round((time.time() - t) * 1000, 1)
                # Décision pragmatique : la régen est meilleure si soit
                # 1. Le NLI score s'améliore, OU
                # 2. Le LLM régen a haute confiance (≥0.7) ET cite des doc_ids présents
                #    dans les claims retournés (le NLI cross-lingual peut faire faux négatif
                #    sur entailment implicite, mais la confiance LLM + citations est un signal
                #    indépendant valide).
                retrieved_doc_ids = {getattr(c, "doc_id", None) for c in claims}
                cites_real_docs = any(
                    d in retrieved_doc_ids for d in (synth_regen.doc_ids_cited or [])
                )
                regen_is_better = (
                    faith_regen.overall_score > faith.overall_score
                    or (synth_regen.confidence >= 0.7 and cites_real_docs)
                )
                if regen_is_better:
                    synth = synth_regen
                    faith = faith_regen
                    regenerated = True
                    logger.info(
                        "[V3] regen accepted: score %.2f→%.2f, conf %.2f, cites_real=%s",
                        faith.overall_score, faith_regen.overall_score,
                        synth_regen.confidence, cites_real_docs,
                    )
                else:
                    logger.info("[V3] regen rejected, keeping original")
            else:
                # Regen abstient/rejette → c'est probablement le bon comportement
                synth = synth_regen
                regenerated = True

        return self._build_response(
            question=question, synth=synth, faith=faith, regenerated=regenerated,
            claims=claims, latencies=latencies, t_start=t_start,
        )

    def _enrich_metadata(self, claims: list[Any]) -> None:
        """Charge lifecycle_status + publication_date des doc_ids depuis Neo4j.

        Modifie les claims en place (ajoute attrs si claim est un objet, ou keys
        si claim est un dict).
        """
        doc_ids = list({getattr(c, "doc_id", None) for c in claims if getattr(c, "doc_id", None)})
        if not doc_ids:
            return
        with self.driver.session() as session:
            rows = session.run(
                """
                MATCH (dc:DocumentContext)
                WHERE dc.tenant_id = $tenant_id AND dc.doc_id IN $doc_ids
                RETURN dc.doc_id AS doc_id,
                       coalesce(dc.lifecycle_status, 'UNKNOWN') AS lifecycle_status,
                       dc.publication_date AS publication_date
                """,
                tenant_id=self.tenant_id, doc_ids=doc_ids,
            ).data()
        meta_map = {r["doc_id"]: r for r in rows}
        for c in claims:
            did = getattr(c, "doc_id", None)
            if did and did in meta_map:
                m = meta_map[did]
                # Ajout attribut si pas déjà présent (Pydantic objects support extras)
                try:
                    setattr(c, "lifecycle_status", m["lifecycle_status"])
                    if m.get("publication_date"):
                        setattr(c, "publication_date", m["publication_date"])
                except Exception:
                    pass

    def _build_response(
        self,
        question: str,
        synth: SynthesisOutput,
        faith: Optional[FaithfulnessReport],
        regenerated: bool,
        claims: list,
        latencies: dict,
        t_start: float,
    ) -> PipelineV3Response:
        latencies["TOTAL_pipeline_ms"] = round((time.time() - t_start) * 1000, 1)
        # Expose chunks used (truncated text) for bench compatibility
        chunks_used = []
        for c in claims[:10]:
            ctext = getattr(c, "text", None) or ""
            chunks_used.append({
                "doc_id": getattr(c, "doc_id", "unknown"),
                "text": ctext[:1500],
                "score": float(getattr(c, "score", 0.0)),
            })
        # Compose user-facing answer if synth.answer is empty :
        # - REJECT_FALSE_PREMISE → use false_premise_correction
        # - ABSTAIN → use abstention_reason
        final_answer = synth.answer
        if not final_answer:
            if synth.decision == "REJECT_FALSE_PREMISE" and synth.false_premise_correction:
                final_answer = (
                    f"⚠️ La question contient une prémisse non confirmée par les sources. "
                    f"{synth.false_premise_correction}"
                )
            elif synth.decision == "ABSTAIN" and synth.abstention_reason:
                final_answer = (
                    f"Les documents fournis ne permettent pas de répondre : "
                    f"{synth.abstention_reason}"
                )
            else:
                final_answer = "Aucune réponse disponible."
        return PipelineV3Response(
            question=question,
            decision=synth.decision,
            answer=final_answer,
            chunks_used=chunks_used,
            false_premise_detected=synth.false_premise_detected,
            false_premise_correction=synth.false_premise_correction,
            abstention_reason=synth.abstention_reason,
            doc_ids_cited=synth.doc_ids_cited,
            subject=synth.subject,
            presupposition_check=synth.presupposition_check,
            confidence=synth.confidence,
            faithfulness_score=faith.overall_score if faith else 0.0,
            faithfulness_verdict=faith.overall_verdict if faith else "SKIPPED",
            n_claims_supported=faith.n_supported if faith else 0,
            n_claims_unsupported=faith.n_unsupported if faith else 0,
            n_chunks_retrieved=len(claims),
            regenerated=regenerated,
            latency_breakdown_ms=latencies,
        )
