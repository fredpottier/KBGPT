"""Bench A3.8 — BRAS RAG CLASSIQUE (baseline comparatif vs OSMOSIS runtime_v6).

Objectif (demande Fred 29/05/2026) : mesurer si OSMOSIS répond MIEUX qu'un système
RAG vanille sur le MÊME gold-set, avec les MÊMES métriques et le MÊME LLM de synthèse.
C'est le test qui légitime (ou non) la complexité KG + Parse + Plan + Evaluate.

DIFFÉRENCE UNIQUE vs OSMOSIS : le retrieval.
    - OSMOSIS : KG (Neo4j claims) + Parse/Plan multi-aspect + RRF + cross-encoder + Evaluate.
    - RAG classique (ici) : embed question → Qdrant top-K chunks bruts → synthèse directe.
      AUCUN KG, AUCUN planner, AUCUN evaluate, AUCUN re-rank custom. Juste
      "retrieve passages / generate answer", l'archi RAG standard de la littérature.

IDENTIQUE des deux côtés (pour un comparatif honnête) :
    - gold-set 50q (benchmark/questions/gold_set_a38_50q.json)
    - LLM de synthèse (Novita deepseek-v3.2 via TaskType.LONG_TEXT_SUMMARY)
    - métriques déterministes (exact_id_recall + abstention_correct) — décisionnelles
    - juge LLM recalibré (orienté rappel) — diagnostic secondaire bruité
    - corpus (collection Qdrant knowbase_chunks_v2, même tenant)

Le run JSON produit a la MÊME structure que bench_a38_runtime_v6 → réutilisable par
le frontend et les scripts de comparaison.

Usage :
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_classic_rag.py'
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_classic_rag.py --limit 5'
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_classic_rag.py --top-k 12'
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bench_rag")

# Réutilise tout le harness du bench OSMOSIS (gold-set, métriques, juge, agrégation)
_spec = importlib.util.spec_from_file_location(
    "bench_a38_runtime_v6", str(Path(__file__).parent / "bench_a38_runtime_v6.py")
)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


# ============================================================================
# Prompt RAG classique — strong baseline, PAS un strawman
# ============================================================================

# RAG standard : faithfulness (réponds depuis le contexte uniquement) + abstention
# honnête (dis-le si l'info n'y est pas) + préservation des identifiants exacts.
# Domain-agnostic : aucun token corpus-spécifique.
_RAG_SYSTEM_PROMPT = """You are a question-answering assistant over a corpus of technical documents.
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

Write a concise, direct answer. Quality over verbosity."""


# Marqueurs d'abstention spécifiques au bras RAG (en plus de ceux du bench OSMOSIS)
_RAG_ABSTENTION_MARKERS = (
    "insufficient_context",
    "does not contain",
    "no information",
    "cannot be answered",
    "not supported by the context",
    "not contained in the context",
)


def _rag_is_abstention(answer: str) -> bool:
    if not answer:
        return False
    low = answer.lower()
    if low.strip().startswith("insufficient_context"):
        return True
    # Réutilise aussi les marqueurs génériques du bench OSMOSIS (FR + EN)
    if any(m.lower() in low for m in bench._ABSTENTION_MARKERS):
        return True
    return any(m in low for m in _RAG_ABSTENTION_MARKERS)


# ============================================================================
# Classic RAG pipeline : embed → Qdrant top-K → synthèse
# ============================================================================


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
                task_type=TaskType.LONG_TEXT_SUMMARY,  # = Novita deepseek-v3.2 (même que OSMOSIS)
                messages=[
                    {"role": "system", "content": _RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=1500,
            )
            dt = time.perf_counter() - t0
            answer_text = (raw or "").strip()
            mode = "ABSTENTION" if _rag_is_abstention(answer_text) else "REASONED"
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


# ============================================================================
# Bench runner (mêmes métriques que le bench OSMOSIS)
# ============================================================================


def run_bench_rag(rag: ClassicRAG, gold_path: Path, limit: Optional[int]) -> List[Dict[str, Any]]:
    with open(gold_path, "r", encoding="utf-8") as f:
        questions = json.load(f)
    if limit:
        questions = questions[:limit]
    logger.info("Bench RAG: %d questions", len(questions))

    results: List[Dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        logger.info("[RAG %d/%d] type=%s id=%s", i, len(questions),
                    q.get("primary_type"), q.get("id"))
        run = rag.answer(q["question"])
        gt = q.get("ground_truth", {})
        gt_answer = gt.get("answer", "")
        if gt_answer and run.get("ok"):
            judge = bench.llm_judge(
                q["question"], run["answer_text"], gt_answer,
                answerability=gt.get("answerability", "answerable"),
                false_premise=gt.get("false_premise", False),
                mode=run.get("mode"),
            )
        else:
            judge = {"score": 0.0, "reasoning": "no_ground_truth_or_run_failed"}
        det = bench.deterministic_metrics(q, run)
        results.append({
            "id": q["id"],
            "primary_type": q.get("primary_type"),
            "language": q.get("language"),
            "question": q["question"],
            "ground_truth_answer": gt_answer,
            "run": run,
            "judge_score": judge["score"],
            "judge_reasoning": judge["reasoning"],
            "judge_attempts": judge.get("attempts"),
            "judge_used_fallback": judge.get("used_fallback", False),
            "exact_id_recall": det["exact_id_recall"],
            "n_expected_ids": det["n_expected_ids"],
            "abstention_correct": det["abstention_correct"],
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="A3.8 bench RAG classique (baseline)")
    parser.add_argument("--gold-50q", type=Path,
                        default=Path("benchmark/questions/gold_set_a38_50q.json"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("data/benchmark/a38_classic_rag"))
    parser.add_argument("--collection", default="knowbase_chunks_v2")
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    rag = ClassicRAG(
        collection=args.collection,
        top_k=args.top_k,
        score_threshold=args.score_threshold,
    )

    t0 = time.perf_counter()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    results = run_bench_rag(rag, args.gold_50q, args.limit)
    agg = bench.aggregate_50q(results) if results else {}
    total_duration = time.perf_counter() - t0

    # Rapport (même format que bench OSMOSIS, sans gates CP)
    print("\n" + "=" * 70)
    print(f"A3.8 BENCH — BRAS RAG CLASSIQUE (baseline) — {timestamp}")
    print(f"  retrieval = Qdrant {args.collection} top-{args.top_k} (vector seul, no KG)")
    print("=" * 70)
    if agg:
        print(f"\n  n={agg['n_total']} run_ok={agg['n_run_ok']} failed={agg['n_run_failed']}")
        eir = agg.get("exact_id_recall_mean")
        if eir is not None:
            print(f"  ★ exact_id_recall : {eir:.3f}  (n={agg['n_with_expected_ids']} q avec identifiants) [DÉTERMINISTE]")
        print(f"  ★ abstention_correct_rate : {agg.get('abstention_correct_rate', 0):.1%} [DÉTERMINISTE]")
        if agg.get("exact_id_recall_per_type"):
            parts = [f"{t}={d['mean']:.2f}(n{d['n']})"
                     for t, d in sorted(agg["exact_id_recall_per_type"].items())]
            print(f"    exact_id_recall/type : {', '.join(parts)}")
        print(f"  C1 (LLM-judge, bruité) : {agg['C1_mean']:.3f}  "
              f"[valid={agg['n_judge_valid']}/{agg['n_total']}, "
              f"judge_failed={agg['n_judge_failed']} ({agg['judge_failure_rate']:.1%})]")
        print(f"  Latency : p50={agg['latency_p50_s']:.1f}s p95={agg['latency_p95_s']:.1f}s")
        print("  Per type (juge LLM):")
        for t, st in sorted(agg["per_type"].items()):
            print(f"    {t:20s} n={st['n']:2d} mean={st['mean']:.3f}")

    print(f"\nTotal duration: {total_duration:.1f}s")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_file = args.output_dir / f"run_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "arm": "classic_rag",
            "config": {
                "collection": args.collection,
                "top_k": args.top_k,
                "score_threshold": args.score_threshold,
                "synthesis_task": "LONG_TEXT_SUMMARY",
            },
            "total_duration_s": total_duration,
            "agg_50q": agg,
            "results_50q": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
