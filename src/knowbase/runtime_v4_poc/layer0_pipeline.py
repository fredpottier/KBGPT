"""Layer 0 — Cheap Certainty Pipeline (CH-49.POC Phase 1.A).

Architecture minimale validation principle "60-80% questions = pas besoin reasoning" :
  1. Retrieval (reuse V4.1 EvidenceCollector)
  2. Extraction directe Llama-Turbo (prompt minimal, pas de Structurer relational)
  3. Q↔A Alignment Verifier (DeepSeek-V3.1)
  4. Decision : ANSWER / ABSTAIN selon align result

Pas de Layer 1/2 dans le POC. Si Layer 0 ABSTAIN avec raison "needs reasoning", on log
le cas pour analyse (futur escalation trigger).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from knowbase.runtime_v4_poc.qa_alignment_verifier import QAAlignmentVerifier, QAAlignmentResult
from knowbase.runtime_v4_poc.operators import TemporalActiveVersionOperator, TemporalActiveResult

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """You are a documentary assistant. Answer the user's question using ONLY the evidence chunks provided.

Rules:
- If the answer is clearly supported by the chunks, give a concise direct answer with citations [doc=ID]
- If multiple chunks contradict, mention both with citations
- If the chunks don't contain the answer, respond exactly: "La réponse à votre question n'a pas été trouvée dans les documents disponibles."
- Stay concise: 1-3 sentences max
- Always include [doc=...] citations when claiming a fact

Format your answer as plain text, no JSON.
"""


@dataclass
class Layer0Response:
    """Réponse Layer 0 POC."""
    question: str
    decision: str  # ANSWER | ABSTAIN
    answer: str
    abstention_reason: Optional[str] = None
    qa_alignment: Optional[str] = None  # ALIGNED | MISALIGNED | ABSTAIN_OK
    qa_reason: Optional[str] = None
    n_chunks_used: int = 0
    doc_ids_cited: list[str] = None
    latency_breakdown_ms: dict = None
    layer: str = "layer0"


class Layer0Pipeline:
    """Pipeline minimal cheap certainty.

    Reuse :
        - EvidenceCollector (knowbase.facts_first.evidence_collector)
        - RuntimeLLMClient (knowbase.runtime_v3.llm_client) pour extraction
        - QAAlignmentVerifier (DeepSeek-V3.1)
    """

    def __init__(
        self,
        evidence_collector: Any,
        llm_client: Any,
        qa_verifier: Optional[QAAlignmentVerifier] = None,
        temporal_active_op: Optional[TemporalActiveVersionOperator] = None,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.llm_client = llm_client
        self.qa_verifier = qa_verifier or QAAlignmentVerifier()
        self.temporal_active_op = temporal_active_op

    def answer(self, question: str, top_k_claims: int = 12) -> Layer0Response:
        """Pipeline Layer 0 + escalation operators (temporal_active_version)."""
        timings = {}

        # 0. ESCALATION CHECK — temporal_active_version operator (déterministe)
        # Si la question demande "version active à date X", short-circuit Layer 0.
        if self.temporal_active_op is not None:
            t0 = time.time()
            top_result = self.temporal_active_op.execute(question)
            timings["operator_temporal_ms"] = int((time.time() - t0) * 1000)
            if top_result.triggered and top_result.decision == "ANSWER":
                logger.info(
                    f"Layer1 temporal_active_version triggered for question='{question[:80]}': "
                    f"active_doc={top_result.active_doc_id} ({top_result.active_publication_date})"
                )
                # Verifier alignment quand même (anti-biais déterministe)
                t0 = time.time()
                align = self.qa_verifier.verify(question, top_result.answer)
                timings["qa_align_ms"] = int((time.time() - t0) * 1000)
                # Merge timings
                merged = dict(top_result.latency_breakdown_ms)
                merged.update(timings)
                doc_ids = self._extract_doc_ids(top_result.answer)
                return Layer0Response(
                    question=question,
                    decision="ANSWER",
                    answer=top_result.answer,
                    qa_alignment=align.decision,
                    qa_reason=align.reason,
                    n_chunks_used=top_result.cypher_n_hits,
                    doc_ids_cited=doc_ids,
                    latency_breakdown_ms=merged,
                    layer="layer1_temporal_active",
                )
            # Sinon (NOT_APPLICABLE ou ABSTAIN), retomber sur Layer 0 normal
            if top_result.triggered and top_result.decision == "ABSTAIN":
                logger.info(
                    f"Layer1 temporal_active_version triggered but ABSTAIN "
                    f"(reason={top_result.abstention_reason}). Falling back to Layer 0."
                )

        # 1. Retrieval — reuse V4.1 EvidenceCollector
        t0 = time.time()
        bundle = self.evidence_collector.collect(
            question=question,
            top_k=top_k_claims,
            mode="single",
        )
        timings["retrieval_ms"] = int((time.time() - t0) * 1000)

        n_claims = len(bundle.claims)
        if n_claims == 0:
            return Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="Aucune preuve trouvée pour cette question.",
                abstention_reason=f"no_evidence (answerability_hint={bundle.answerability_hint})",
                n_chunks_used=0,
                doc_ids_cited=[],
                latency_breakdown_ms=timings,
            )

        # Format claims pour prompt
        chunks_text = self._format_claims(bundle.claims)

        # 2. Extraction directe via Llama-Turbo
        t0 = time.time()
        prompt_messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nEvidence chunks:\n{chunks_text}\n\nAnswer:"},
        ]
        try:
            answer_text = self.llm_client.chat_completion(
                messages=prompt_messages,
                temperature=0.1,
                max_tokens=500,
            )
        except Exception as exc:
            logger.error(f"Layer0 extraction failed: {exc}")
            return Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="Erreur du pipeline.",
                abstention_reason=f"llm_error: {exc}",
                n_chunks_used=len(evidence.chunks if hasattr(evidence, "chunks") else []),
                doc_ids_cited=[],
                latency_breakdown_ms=timings,
            )
        timings["extraction_ms"] = int((time.time() - t0) * 1000)

        # 3. Q↔A Alignment Verifier (DeepSeek-V3.1)
        t0 = time.time()
        align = self.qa_verifier.verify(question, answer_text)
        timings["qa_align_ms"] = int((time.time() - t0) * 1000)

        # 4. Decision
        doc_ids = self._extract_doc_ids(answer_text)
        n_chunks = n_claims

        if align.decision == "MISALIGNED":
            return Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer="La réponse extraite ne correspond pas précisément à la question. Réessai avec un raisonnement plus poussé recommandé.",
                abstention_reason=f"qa_misaligned: {align.reason}",
                qa_alignment=align.decision,
                qa_reason=align.reason,
                n_chunks_used=n_chunks,
                doc_ids_cited=doc_ids,
                latency_breakdown_ms=timings,
            )

        if align.decision == "ABSTAIN_OK":
            return Layer0Response(
                question=question,
                decision="ABSTAIN",
                answer=answer_text,
                abstention_reason=f"abstain_correct: {align.reason}",
                qa_alignment=align.decision,
                qa_reason=align.reason,
                n_chunks_used=n_chunks,
                doc_ids_cited=doc_ids,
                latency_breakdown_ms=timings,
            )

        # ALIGNED → return answer
        return Layer0Response(
            question=question,
            decision="ANSWER",
            answer=answer_text,
            qa_alignment=align.decision,
            qa_reason=align.reason,
            n_chunks_used=n_chunks,
            doc_ids_cited=doc_ids,
            latency_breakdown_ms=timings,
        )

    @staticmethod
    def _format_claims(claims: list) -> str:
        """Format les claims du retrieval pour prompt."""
        out = []
        for c in claims[:15]:
            quote = (c.quote or "").strip()
            if not quote:
                continue
            page = f" p.{c.page_no}" if c.page_no else ""
            out.append(f"[doc={c.doc_id}{page}] {quote[:500]}")
        return "\n\n".join(out)

    @staticmethod
    def _extract_doc_ids(answer: str) -> list[str]:
        import re
        return list(set(re.findall(r"\[doc=([^\]]+)\]", answer or "")))
