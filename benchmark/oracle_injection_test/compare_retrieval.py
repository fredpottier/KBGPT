"""
Compare retrieval dense-only vs hybrid (BM25+vector RRF) sur 20 cas oracle.

Pour chaque question :
1. Retrieval mode A (dense-only) → top_k claims
2. Retrieval mode B (hybrid RRF) → top_k claims
3. Métrique : un chunk "correct" est-il dans le top-K ?
   Heuristique = au moins 1 des search_terms du test_case apparaît dans le text d'un claim

Sortie : tableau comparatif + score gain.
"""
from __future__ import annotations

import os
import sys
import json
import time
import importlib.util
import types
from pathlib import Path
from datetime import datetime, timezone

# ─── Bypass package __init__ pour éviter le circular import ────────────────
sys.path.insert(0, "/app/src")
spec_m = importlib.util.spec_from_file_location("models_lite", "/app/src/knowbase/runtime_v2/models.py")
models = importlib.util.module_from_spec(spec_m); spec_m.loader.exec_module(models)
sys.modules["knowbase.runtime_v2.models"] = models
# Rebuild Pydantic models pour éviter "not fully defined"
for cls_name in dir(models):
    cls = getattr(models, cls_name)
    if hasattr(cls, "model_rebuild"):
        try:
            cls.model_rebuild()
        except Exception:
            pass
fake_pkg = types.ModuleType("knowbase.runtime_v2"); fake_pkg.models = models
sys.modules["knowbase.runtime_v2"] = fake_pkg
spec_r = importlib.util.spec_from_file_location("retriever_lite", "/app/src/knowbase/runtime_v2/retriever.py")
retriever_mod = importlib.util.module_from_spec(spec_r); spec_r.loader.exec_module(retriever_mod)

ClaimRetriever = retriever_mod.ClaimRetriever

# ─── Load 20 test cases ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from test_cases import TEST_CASES  # noqa: E402

# ─── Setup clients ─────────────────────────────────────────────────────────
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
NEO4J_URL = os.environ.get("NEO4J_URL", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "graphiti_neo4j_pass")

print(f"[{datetime.now().isoformat(timespec='seconds')}] Loading clients...")
qdrant = QdrantClient(url=QDRANT_URL, timeout=30)
embedder = SentenceTransformer("intfloat/multilingual-e5-large", device="cpu")
neo4j_driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))


def has_correct_chunk(claims: list, search_terms: list[str], doc_ids_expected: list[str]) -> tuple[bool, dict]:
    """Détermine si au moins 1 chunk correct est dans la liste des claims."""
    n_doc_match = 0
    n_term_in_chunk = 0
    for c in claims:
        text_lower = (c.get("text") or "").lower()
        if c.get("doc_id") in doc_ids_expected:
            n_doc_match += 1
        for term in search_terms:
            if term.lower() in text_lower:
                n_term_in_chunk += 1
                break
    has_match = n_term_in_chunk > 0 and n_doc_match > 0
    return has_match, {
        "n_chunks": len(claims),
        "n_correct_doc": n_doc_match,
        "n_with_term": n_term_in_chunk,
    }


def retrieve_raw(retriever, question: str, doc_ids: list[str], top_k: int = 10) -> list[dict]:
    """Bypass de retriever.retrieve() pour éviter Pydantic — appelle Qdrant direct."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
    vec = retriever.embedder.encode(f"query: {question}").tolist()
    filters = [FieldCondition(key="tenant_id", match=MatchValue(value=retriever.tenant_id))]
    if doc_ids:
        filters.append(FieldCondition(key="doc_id", match=MatchAny(any=doc_ids)))
    qf = Filter(must=filters)
    fetch_k = max(top_k, retriever_mod.RERANK_PREFETCH) if retriever_mod.RERANK_ENABLED else top_k
    if retriever_mod.HYBRID_ENABLED:
        results = retriever._hybrid_search(question, vec, qf, fetch_k)
    else:
        results = retriever.qdrant.search(
            collection_name=retriever.collection,
            query_vector=vec, limit=fetch_k, query_filter=qf, with_payload=True,
        )
    if retriever_mod.RERANK_ENABLED and len(results) > top_k:
        results = retriever._rerank(question, results, top_k)
    out = []
    for r in results:
        p = dict(getattr(r, "payload", None) or {})
        out.append({
            "claim_id": p.get("claim_id") or p.get("chunk_id") or str(getattr(r, "id", "")),
            "doc_id": p.get("doc_id", "unknown"),
            "text": p.get("text") or p.get("passage_text") or "",
            "score": float(getattr(r, "score", 0.0)),
        })
    return out


def run_retrieval_for_case(retriever, tc: dict, top_k: int = 10, scoped: bool = False) -> dict:
    """Test : si scoped=True, doc_ids forcés (mesure retrieval pur sur le bon doc).
    Si scoped=False, retrieval all-corpus (réalité pipeline)."""
    t0 = time.time()
    claims = retrieve_raw(retriever, tc["question"],
                         doc_ids=tc["doc_ids"] if scoped else None, top_k=top_k)
    elapsed = time.time() - t0
    has_match, stats = has_correct_chunk(claims, tc["search_terms"], tc["doc_ids"])
    return {
        "qid": tc["qid"],
        "match": has_match,
        "latency_s": round(elapsed, 2),
        "n_chunks": len(claims),
        "stats": stats,
        "top_chunks": [
            {"doc_id": c["doc_id"], "text": (c["text"] or "")[:200], "score": round(c["score"], 4)}
            for c in claims[:5]
        ],
    }


def main():
    retriever_obj = ClaimRetriever(
        qdrant_client=qdrant, embedder=embedder, driver=neo4j_driver,
        collection_name="knowbase_chunks_v2", tenant_id="default",
    )

    results_a, results_b = [], []
    for i, tc in enumerate(TEST_CASES):
        print(f"\n[{i+1}/20] {tc['qid']}: {tc['question'][:80]}")

        # Mode A : dense-only, NO rerank (baseline)
        retriever_mod.HYBRID_ENABLED = False
        retriever_mod.RERANK_ENABLED = False
        ra = run_retrieval_for_case(retriever_obj, tc)
        # Mode B : hybrid + rerank (full A1+A4)
        retriever_mod.HYBRID_ENABLED = True
        retriever_mod.RERANK_ENABLED = True
        rb = run_retrieval_for_case(retriever_obj, tc)
        results_a.append(ra)
        results_b.append(rb)

        ma, mb = ra["match"], rb["match"]
        marker = "→" if ma == mb else ("📈" if mb else "📉")
        print(f"  Dense  : match={ma} (corr_doc={ra['stats']['n_correct_doc']}/{ra['n_chunks']}, with_term={ra['stats']['n_with_term']}) {ra['latency_s']}s")
        print(f"  Hybrid : match={mb} (corr_doc={rb['stats']['n_correct_doc']}/{rb['n_chunks']}, with_term={rb['stats']['n_with_term']}) {rb['latency_s']}s {marker}")

    # Aggregate
    n_match_a = sum(1 for r in results_a if r["match"])
    n_match_b = sum(1 for r in results_b if r["match"])
    avg_lat_a = sum(r["latency_s"] for r in results_a) / len(results_a)
    avg_lat_b = sum(r["latency_s"] for r in results_b) / len(results_b)

    # Per-case ranking quality : moyenne du n_correct_doc / 10
    avg_corr_a = sum(r["stats"]["n_correct_doc"] for r in results_a) / len(results_a) / 10
    avg_corr_b = sum(r["stats"]["n_correct_doc"] for r in results_b) / len(results_b) / 10

    print("\n" + "=" * 70)
    print(f"Baseline (dense, no rerank): {n_match_a}/20 hit ({n_match_a*5}%) | avg correct_doc/10 = {avg_corr_a:.2f} | latency {avg_lat_a:.2f}s")
    print(f"Hybrid + Rerank (A1+A4):     {n_match_b}/20 hit ({n_match_b*5}%) | avg correct_doc/10 = {avg_corr_b:.2f} | latency {avg_lat_b:.2f}s")
    print(f"Δ Hit rate: {(n_match_b - n_match_a) * 5:+d} pp | Δ correct_doc: {(avg_corr_b - avg_corr_a)*100:+.1f} pp")
    print("=" * 70)

    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(TEST_CASES),
        "summary": {
            "dense_only_hits": n_match_a,
            "hybrid_hits": n_match_b,
            "delta_pp": (n_match_b - n_match_a) * 5,
            "avg_latency_dense_s": round(avg_lat_a, 3),
            "avg_latency_hybrid_s": round(avg_lat_b, 3),
        },
        "per_case": [
            {"qid": tc["qid"], "question": tc["question"], "expected_docs": tc["doc_ids"],
             "dense": ra, "hybrid": rb}
            for tc, ra, rb in zip(TEST_CASES, results_a, results_b)
        ],
    }
    out_path = Path(__file__).parent / f"retrieval_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Saved → {out_path}")


if __name__ == "__main__":
    main()
