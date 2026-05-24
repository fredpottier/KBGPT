"""P2 — Option ε élargie : audit Synthesize sur factual + multi_hop.

Pour chaque question score < 1.0 :
1. Identifier claims attendus (recall audit full-text Neo4j sur tokens question+gt)
2. Récupérer top-50 retrieval (RRF + CE rerank top-5)
3. Extraire claim_ids cités par Synthesize dans answer_text
4. Classifier :
   - A. Synthesize bug : claims attendus ∈ top-5 retrieval MAIS pas dans claims cités par Synthesize
   - B. Retrieval miss : claims attendus ∉ top-50 retrieval
   - C. Synthesize choice : claims attendus ∈ top-5 ET cités, mais Synthesize n'a pas extrait la bonne info
   - D. Gold-set/extraction issue : claim attendu introuvable en KG

Usage:
    docker exec knowbase-app sh -c 'cd /app && python -u scripts/p2_synthesize_audit.py'
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("p2_synthesize_audit")

# Imports retardés pour éviter chargement modèle au démarrage
_LUCENE_SPECIAL = r'+-&|!(){}[]^"~*?:\/'


def _escape_lucene(text: str) -> str:
    return "".join("\\" + c if c in _LUCENE_SPECIAL else c for c in text)


def _extract_tokens(question: str, ground_truth: str) -> List[str]:
    """Extraction tokens de recherche : identifiants formels + mots longs."""
    text = f"{question} {ground_truth}"
    tokens: List[str] = []

    # Identifiants formels (codes, transactions, IDs, paths)
    formal = re.findall(r"[A-Z]{2,}[\w/_]*|/[A-Z]+/\w+|\w+_\w+|\d{3,}", text)
    tokens.extend(formal)

    # Mots longs ≥ 6 chars
    words = re.findall(r"\b[A-Za-z][A-Za-z]{5,}\b", text)
    stopwords = {"comment", "quelle", "quelles", "quels", "utilise", "permet",
                 "fournit", "existent", "transaction", "options", "objets",
                 "module", "client", "scenario", "fonctionnel", "ecosysteme",
                 "ecosystem", "informations", "documents", "documentation"}
    tokens.extend(w for w in words if w.lower() not in stopwords)

    # Dédup
    seen = set()
    unique = []
    for t in tokens:
        tl = t.lower()
        if tl not in seen and len(t) >= 3:
            seen.add(tl)
            unique.append(t)
    return unique[:15]


def find_expected_claims(neo4j_client, tokens: List[str],
                         tenant_id: str = "default", limit: int = 30) -> List[Dict[str, Any]]:
    if not tokens:
        return []
    lucene_query = " OR ".join(_escape_lucene(t) for t in tokens)
    try:
        rows = neo4j_client.execute_query(
            """
            CALL db.index.fulltext.queryNodes('claim_text_search', $q)
            YIELD node AS c, score
            WHERE c.tenant_id = $tenant_id
            RETURN c.claim_id AS claim_id,
                   c.text AS text,
                   c.subject_canonical AS subject_canonical,
                   c.predicate AS predicate,
                   score
            ORDER BY score DESC
            LIMIT $limit
            """,
            q=lucene_query, tenant_id=tenant_id, limit=limit,
        )
    except Exception as e:
        logger.warning("find_expected_claims failed: %s", e)
        return []
    return [{"claim_id": r["claim_id"], "text": (r.get("text") or "")[:200],
             "subject_canonical": r.get("subject_canonical"),
             "score": r.get("score", 0.0)} for r in rows]


def extract_cited_claim_ids(answer_text: str) -> List[str]:
    """Extrait les claim_ids cités via regex [claim_id=...]."""
    return re.findall(r"\[claim_id=([^\]]+)\]", answer_text or "")


def retrieval_with_ce(neo4j_client, embedder, reranker, question: str,
                     tenant_id: str = "default", as_of: str = "2026-05-24",
                     top_k_ce: int = 5) -> Dict[str, Any]:
    """Reproduit le pipeline retrieval réel : RRF top-50 → CE top-5.

    Note : on utilise la question brute (V6_HYBRID_QUERY_MODE=question) ici car
    on cherche à savoir où le claim attendu COULD BE, pas où il EST dans le
    pipeline réel (qui utilise sub_goal mode).
    """
    from knowbase.runtime_a3.execute import (
        CYPHER_KG_CLAIMS_BM25_ONLY,
        CYPHER_KG_CLAIMS_VECTOR_ONLY,
        CYPHER_LOAD_CLAIMS_BY_IDS,
    )

    out: Dict[str, Any] = {}
    try:
        escaped = _escape_lucene(question)
        bm25_rows = neo4j_client.execute_query(
            CYPHER_KG_CLAIMS_BM25_ONLY,
            query_text=escaped, tenant_id=tenant_id, as_of=as_of,
        )
        out["bm25_top50"] = [r["claim_id"] for r in bm25_rows]
    except Exception:
        out["bm25_top50"] = []

    try:
        emb = embedder(f"query: {question}")
        vec_rows = neo4j_client.execute_query(
            CYPHER_KG_CLAIMS_VECTOR_ONLY,
            query_embedding=emb, tenant_id=tenant_id, as_of=as_of,
        )
        out["vector_top50"] = [r["claim_id"] for r in vec_rows]
    except Exception:
        out["vector_top50"] = []

    # RRF
    rrf_k = 60
    scores: Dict[str, float] = {}
    for rank_i, cid in enumerate(out["bm25_top50"]):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_i + 1)
    for rank_i, cid in enumerate(out["vector_top50"]):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_i + 1)
    out["rrf_top50"] = [cid for cid, _ in sorted(scores.items(), key=lambda x: -x[1])[:50]]

    # CE top-K sur RRF top-50
    if out["rrf_top50"]:
        load_rows = neo4j_client.execute_query(
            CYPHER_LOAD_CLAIMS_BY_IDS,
            claim_ids=out["rrf_top50"], tenant_id=tenant_id,
        )
        texts = [(r["c"].get("text", ""), r["c"].get("claim_id")) for r in load_rows]
        pairs = [(question, t) for t, _ in texts]
        try:
            ce_scores = reranker.predict(pairs, show_progress_bar=False)
            scored = sorted(zip([cid for _, cid in texts], ce_scores), key=lambda x: -x[1])
            out["ce_top5"] = [cid for cid, _ in scored[:top_k_ce]]
        except Exception:
            out["ce_top5"] = []
    return out


def classify_question(question_result: Dict[str, Any], retrieval: Dict[str, Any],
                      expected_claim_ids: List[str]) -> Dict[str, Any]:
    """Classifie un cas score=0.0.

    Returns dict avec scenario, in_top5, in_top50, cited_by_synthesize.
    """
    cited = extract_cited_claim_ids(question_result["run"]["answer_text"])
    cited_short = [c[:14] for c in cited]

    # Pour chaque claim attendu (top-3 candidates)
    analysis = []
    for eid in expected_claim_ids:
        eid_short = eid[:14] if len(eid) > 14 else eid
        in_top5 = any(c.startswith(eid_short[:14]) or c[:14] == eid_short for c in retrieval.get("ce_top5", []))
        in_top50 = any(c.startswith(eid_short[:14]) or c[:14] == eid_short for c in retrieval.get("rrf_top50", []))
        cited_match = any(c.startswith(eid_short[:14]) or c[:14] == eid_short for c in cited)

        if cited_match:
            scenario = "CITED (Synthesize used it)"
        elif in_top5:
            scenario = "A1 (in CE top-5 but Synthesize didn't cite)"
        elif in_top50:
            scenario = "A2 (in RRF top-50 but lost by CE / sub_goal query)"
        else:
            scenario = "B (not in RRF top-50 — retrieval miss)"

        analysis.append({
            "claim_id": eid,
            "in_top5": in_top5,
            "in_top50": in_top50,
            "cited": cited_match,
            "scenario": scenario,
        })

    # Best scenario for question
    best = None
    for a in analysis:
        if a["cited"]:
            best = "CITED"; break
        if a["in_top5"]:
            best = "A1 (Synthesize bug)"; best_priority = 1; break
        if a["in_top50"]:
            best = "A2 (sub_goal query dilution)"; break
    if best is None:
        best = "B (retrieval miss / extraction gap)"

    return {
        "cited_claim_ids_short": cited_short,
        "analysis_per_expected": analysis,
        "best_scenario": best,
    }


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.clients.embeddings import EmbeddingModelManager
    from knowbase.common.clients.reranker import get_cross_encoder

    print("=" * 70)
    print("P2 Option ε étendue — Audit Synthesize factual + multi_hop")
    print("=" * 70)

    print("\nInit clients...")
    neo4j = get_neo4j_client()
    emb_mgr = EmbeddingModelManager()
    embedder = lambda text: emb_mgr.encode([text])[0].tolist()
    reranker = get_cross_encoder(model_name="BAAI/bge-reranker-v2-m3", device="cpu")

    # Load bench Config C
    bench_path = ROOT / "data/benchmark/a38_runtime_v6/run_20260524_084344.json"
    with open(bench_path, "r", encoding="utf-8") as f:
        bench = json.load(f)

    # Filtrer factual + multi_hop avec score < 1.0
    target = [r for r in bench["results_50q"]
              if r["primary_type"] in ("factual", "multi_hop") and r["judge_score"] < 1.0]
    print(f"\nQuestions à auditer (factual+multi_hop, score<1.0) : {len(target)}")

    audit = []
    for i, r in enumerate(target, 1):
        qid = r["id"]
        question = r["question"]
        gt = r.get("ground_truth_answer", "")
        score = r["judge_score"]
        ptype = r["primary_type"]

        print(f"\n[{i}/{len(target)}] {ptype:10s} {qid} score={score} | {question[:60]}")

        # 1. Identifier claims attendus
        tokens = _extract_tokens(question, gt)
        candidates = find_expected_claims(neo4j, tokens, limit=10)
        if not candidates:
            print("  → 0 candidate via full-text")
            audit.append({"id": qid, "type": ptype, "score": score, "verdict": "no_candidate"})
            continue

        candidate_ids = [c["claim_id"] for c in candidates[:3]]
        print(f"  Top-3 candidates: {[c[:14] for c in candidate_ids]}")

        # 2. Pipeline retrieval (question brute)
        retrieval = retrieval_with_ce(neo4j, embedder, reranker, question)

        # 3. Classification
        cls = classify_question(r, retrieval, candidate_ids)
        print(f"  Synthesize cited: {cls['cited_claim_ids_short'][:5]}")
        for a in cls["analysis_per_expected"]:
            print(f"    {a['claim_id'][:14]}: in_top5={a['in_top5']} in_top50={a['in_top50']} cited={a['cited']} → {a['scenario']}")
        print(f"  → Best: {cls['best_scenario']}")

        audit.append({
            "id": qid, "type": ptype, "score": score,
            "question": question,
            "ground_truth": gt[:200],
            "answer_text": r["run"]["answer_text"][:300],
            "candidates": [{"claim_id": c["claim_id"], "text": c["text"][:150]} for c in candidates[:3]],
            "analysis": cls,
        })

    # Distribution scénarios
    print("\n" + "=" * 70)
    print("DISTRIBUTION SCÉNARIOS")
    print("=" * 70)
    by_type_scenario = {}
    for r in audit:
        if r.get("verdict") == "no_candidate":
            key = (r["type"], "no_candidate")
        else:
            key = (r["type"], r["analysis"]["best_scenario"])
        by_type_scenario[key] = by_type_scenario.get(key, 0) + 1

    for (t, s), n in sorted(by_type_scenario.items()):
        print(f"  {t:10s} {s:50s} : {n}")

    # Persister
    out_path = ROOT / "data/benchmark/p2_synthesize_audit_20260524.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"\nResults persisted: {out_path}")


if __name__ == "__main__":
    main()
