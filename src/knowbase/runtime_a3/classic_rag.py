"""
classic_rag.py — Pipeline RAG vanille (vector retrieval seul + synthèse directe).

Extrait de app/scripts/bench_a38_classic_rag.py (bras comparatif du bench) pour
être réutilisable par l'API : le toggle « Knowledge Graph » du chat (A/B RAG seul
vs RAG+KG voulu par Fred) appelait runtime_v6 dans tous les cas depuis le
branchement du chat sur runtime_a3 (31/05) — le flag était ignoré. Désormais
`use_kg=false` route vers ce pipeline.

Strong baseline, PAS un strawman : faithfulness (contexte uniquement) +
abstention honnête + préservation des identifiants exacts. Domain-agnostic.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# RAG standard : faithfulness (réponds depuis le contexte uniquement) + abstention
# honnête (dis-le si l'info n'y est pas) + préservation des identifiants exacts.
RAG_SYSTEM_PROMPT = """You are a question-answering assistant over a corpus of technical documents.
Answer the user's QUESTION using ONLY the provided CONTEXT passages.

RULES:
- Be factual and precise. Preserve EXACT identifiers, codes, names, numbers and dates
  verbatim as they appear in the context (do not normalize or paraphrase them).
- Cite the passages you rely on as [Source N] (N = passage number).
- Use ONLY the context. Do NOT use outside/prior knowledge and do NOT guess.
- If the context does NOT contain the information needed to answer, reply EXACTLY with:
  INSUFFICIENT_CONTEXT: <short reason>
- If the question is based on a premise that the context does not support (false or
  unverifiable premise), say so explicitly instead of inventing an answer.
- Answer in the language of the QUESTION (keep verbatim quotes in their source language).

Write a concise, direct answer. Quality over verbosity."""


# Marqueurs d'abstention (EN + FR génériques + spécifiques RAG)
ABSTENTION_MARKERS = (
    "insufficient_context",
    "does not contain",
    "no information",
    "cannot be answered",
    "not supported by the context",
    "not contained in the context",
    "ne contient pas",
    "aucune information",
    "ne permet pas de répondre",
)


def rag_is_abstention(answer: str) -> bool:
    if not answer:
        return False
    low = answer.lower()
    if low.strip().startswith("insufficient_context"):
        return True
    return any(m in low for m in ABSTENTION_MARKERS)


class ClassicRAG:
    """Pipeline RAG vanille : vector retrieval seul + synthèse LLM directe."""

    def __init__(
        self,
        collection: str = "knowbase_chunks_v2",
        top_k: int = 12,
        score_threshold: Optional[float] = None,
    ):
        self._collection = collection
        self._top_k = top_k
        self._score_threshold = score_threshold
        self._embedder = None
        self._search = None
        self._router = None

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda text: mgr.encode([text])[0].tolist()
        return self._embedder

    def _get_search(self):
        if self._search is None:
            from knowbase.common.clients.qdrant_client import search_with_tenant_filter
            self._search = search_with_tenant_filter
        return self._search

    def _get_router(self):
        if self._router is None:
            from knowbase.common.llm_router import LLMRouter
            self._router = LLMRouter()
        return self._router

    def retrieve(self, question: str, tenant_id: str) -> List[Dict[str, Any]]:
        vector = self._get_embedder()(question)
        hits = self._get_search()(
            collection_name=self._collection,
            query_vector=vector,
            tenant_id=tenant_id,
            limit=self._top_k,
            score_threshold=self._score_threshold,
        )
        passages: List[Dict[str, Any]] = []
        for h in hits:
            payload = h.get("payload", {}) or {}
            text = payload.get("text") or payload.get("content") or ""
            if not text:
                continue
            passages.append({
                "doc": (payload.get("document") or payload.get("source_name")
                        or payload.get("document_id") or payload.get("doc_id") or ""),
                "heading": payload.get("heading") or payload.get("title") or "",
                "text": text[:1200],  # borne par passage
                "score": h.get("score"),
            })
        return passages

    def _build_context(self, passages: List[Dict[str, Any]]) -> str:
        blocks = []
        for i, p in enumerate(passages, 1):
            head = f" — {p['heading']}" if p["heading"] else ""
            doc = f" (doc: {p['doc']})" if p["doc"] else ""
            blocks.append(f"[Source {i}]{doc}{head}\n{p['text']}")
        return "\n\n".join(blocks)

    def answer(self, question: str, tenant_id: str = "default") -> Dict[str, Any]:
        from knowbase.common.llm_router import TaskType
        t0 = time.perf_counter()
        try:
            passages = self.retrieve(question, tenant_id)
            if not passages:
                dt = time.perf_counter() - t0
                return {
                    "ok": True, "duration_s": dt,
                    "answer_text": "INSUFFICIENT_CONTEXT: no passage retrieved.",
                    "mode": "ABSTENTION", "n_retrieved": 0,
                    "citation_coverage_rate": None, "n_cited_claims": 0,
                    "conflict_pending_warning": None,
                }
            context = self._build_context(passages)
            user = (
                f"QUESTION: {question}\n\n"
                f"CONTEXT ({len(passages)} passages):\n{context}\n\n"
                "Answer now, following the rules."
            )
            raw = self._get_router().complete(
                task_type=TaskType.LONG_TEXT_SUMMARY,  # = même LLM de synthèse qu'OSMOSIS
                messages=[
                    {"role": "system", "content": RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=1500,
            )
            dt = time.perf_counter() - t0
            answer_text = (raw or "").strip()
            mode = "ABSTENTION" if rag_is_abstention(answer_text) else "REASONED"
            return {
                "ok": True, "duration_s": dt,
                "answer_text": answer_text, "mode": mode,
                "n_retrieved": len(passages),
                "citation_coverage_rate": None, "n_cited_claims": 0,
                "conflict_pending_warning": None,
            }
        except Exception as exc:
            dt = time.perf_counter() - t0
            logger.exception("classic_rag answer failed")
            return {
                "ok": False, "duration_s": dt, "error": str(exc)[:300],
                "answer_text": "", "mode": "ERROR", "n_retrieved": 0,
                "citation_coverage_rate": None, "n_cited_claims": 0,
                "conflict_pending_warning": None,
            }
