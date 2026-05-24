"""P2.4-PRE Recall audit — pour chaque question factual, mesurer rank du claim
attendu dans BM25 top-100 / Vector top-50 / RRF top-50 / CE top-5.

Objectif : classifier scénario A/B/C/D par question pour le diagnostic
régression factual Config C.

- Scénario A : claim ∈ RRF top-50 mais ∉ CE top-5 → CE perd signal BM25
- Scénario B : claim ∈ BM25/Vector top-50 mais ∉ RRF top-50 → fusion RRF casse
- Scénario C : claim ∉ BM25/Vector top-50 → tokenisation/indexation cassée
- Scénario D : claim ∈ BM25 top-100 mais > top-50 → augmenter N candidats

Usage:
    docker exec knowbase-app sh -c 'cd /app && python -u scripts/p2_recall_audit.py'

Domain-agnostic strict.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("p2_recall_audit")


def _escape_lucene(text: str) -> str:
    """Échappement Lucene minimaliste (cf execute.py)."""
    special = r'+-&|!(){}[]^"~*?:\/'
    return "".join("\\" + c if c in special else c for c in text)


def _normalize(text: str) -> str:
    """Normalise pour matching tolerant."""
    return re.sub(r"\s+", " ", text.lower().strip())


def find_expected_claims(neo4j_client, question: str, ground_truth_answer: str,
                         tenant_id: str = "default", limit: int = 30) -> List[Dict[str, Any]]:
    """Identifie les claims plausiblement attendus pour répondre à la question.

    Stratégie : extraire les tokens "rares" de la ground_truth + question (codes,
    transactions, mots techniques), faire un OR full-text query Neo4j sur ces
    tokens, retourner les top-N claims candidats.

    Retourne liste de dict {claim_id, text_excerpt, subject_canonical, score}.
    """
    # Extraire tokens : identifiants formels (codes ALL_CAPS, slash-paths,
    # noms propres avec chiffres) — heuristique domain-agnostic
    tokens: List[str] = []
    text = f"{question} {ground_truth_answer}"

    # Identifiants formels (codes, transactions, IDs)
    formal_ids = re.findall(r"[A-Z]{2,}[\w/_]{1,}|/[A-Z]+/\w+|\w+_\w+|\d{3,}", text)
    tokens.extend(formal_ids)

    # Mots longs (>= 6 chars, hors stopwords) — heuristique vocabulaire spécifique
    words = re.findall(r"\b[A-Za-z][A-Za-z]{5,}\b", text)
    stopwords_fr = {"comment", "quelle", "quelles", "quels", "utilise", "permet",
                    "fournit", "existent", "transaction", "options", "objets",
                    "module", "client", "scenario", "fonctionnel"}
    stopwords_en = {"which", "what", "where", "exist", "provides", "transaction"}
    tokens.extend([w for w in words if w.lower() not in (stopwords_fr | stopwords_en)])

    if not tokens:
        return []

    # Dédup + escape Lucene + OR query
    seen = set()
    unique_tokens = []
    for t in tokens:
        tl = t.lower()
        if tl not in seen and len(t) >= 3:
            seen.add(tl)
            unique_tokens.append(t)

    # Lucene OR query (joindre les tokens avec OR, sans quotes — quotes = phrase search)
    lucene_query = " OR ".join(_escape_lucene(t) for t in unique_tokens[:15])

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

    return [
        {
            "claim_id": r["claim_id"],
            "text": (r.get("text") or "")[:200],
            "subject_canonical": r.get("subject_canonical"),
            "predicate": r.get("predicate"),
            "score": r.get("score", 0.0),
        }
        for r in rows
    ]


def retrieval_ranks(neo4j_client, embedder, reranker, question: str,
                    expected_claim_ids: List[str],
                    tenant_id: str = "default",
                    as_of: str = "2026-05-24") -> Dict[str, Any]:
    """Retourne les rangs des claims attendus dans chaque retrieval method."""
    from knowbase.runtime_a3.execute import (
        CYPHER_KG_CLAIMS_BM25_ONLY,
        CYPHER_KG_CLAIMS_VECTOR_ONLY,
    )

    out: Dict[str, Any] = {
        "expected_claim_ids": expected_claim_ids,
        "bm25_top50": None,
        "vector_top50": None,
        "rrf_top50": None,
        "ce_top5": None,
    }

    # 1. BM25 top-50
    try:
        escaped = _escape_lucene(question)
        bm25_rows = neo4j_client.execute_query(
            CYPHER_KG_CLAIMS_BM25_ONLY,
            query_text=escaped, tenant_id=tenant_id, as_of=as_of,
        )
        out["bm25_top50"] = [r["claim_id"] for r in bm25_rows]
    except Exception as e:
        out["bm25_top50_error"] = str(e)[:200]

    # 2. Vector top-50
    try:
        emb = embedder(f"query: {question}")
        vec_rows = neo4j_client.execute_query(
            CYPHER_KG_CLAIMS_VECTOR_ONLY,
            query_embedding=emb, tenant_id=tenant_id, as_of=as_of,
        )
        out["vector_top50"] = [r["claim_id"] for r in vec_rows]
    except Exception as e:
        out["vector_top50_error"] = str(e)[:200]

    # 3. RRF fusion
    if out.get("bm25_top50") and out.get("vector_top50"):
        rrf_k = 60
        scores: Dict[str, float] = {}
        for rank_i, cid in enumerate(out["bm25_top50"]):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_i + 1)
        for rank_i, cid in enumerate(out["vector_top50"]):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_i + 1)
        out["rrf_top50"] = [cid for cid, _ in sorted(scores.items(), key=lambda x: -x[1])[:50]]

    # 4. CE top-5 sur RRF top-50
    if out.get("rrf_top50") and reranker is not None:
        try:
            from knowbase.runtime_a3.execute import CYPHER_LOAD_CLAIMS_BY_IDS
            load_rows = neo4j_client.execute_query(
                CYPHER_LOAD_CLAIMS_BY_IDS,
                claim_ids=out["rrf_top50"], tenant_id=tenant_id,
            )
            # Build ClaimSummary-like dict with text
            claims_with_text = []
            for r in load_rows:
                c = r["c"]
                claims_with_text.append({
                    "claim_id": c.get("claim_id"),
                    "text": c.get("text", ""),
                })
            # Predict CE scores
            pairs = [(question, c["text"]) for c in claims_with_text]
            scores = reranker.predict(pairs, show_progress_bar=False)
            scored = sorted(zip(claims_with_text, scores), key=lambda x: -x[1])
            out["ce_top5"] = [c["claim_id"] for c, _ in scored[:5]]
            out["ce_top5_scores"] = [float(s) for _, s in scored[:5]]
        except Exception as e:
            out["ce_top5_error"] = str(e)[:200]

    # 5. Calculer rangs des claims attendus
    rank_summary = []
    for eid in expected_claim_ids:
        entry = {
            "claim_id": eid,
            "rank_bm25": (out["bm25_top50"].index(eid) + 1) if out.get("bm25_top50") and eid in out["bm25_top50"] else None,
            "rank_vector": (out["vector_top50"].index(eid) + 1) if out.get("vector_top50") and eid in out["vector_top50"] else None,
            "rank_rrf": (out["rrf_top50"].index(eid) + 1) if out.get("rrf_top50") and eid in out["rrf_top50"] else None,
            "rank_ce": (out["ce_top5"].index(eid) + 1) if out.get("ce_top5") and eid in out["ce_top5"] else None,
        }
        rank_summary.append(entry)
    out["rank_summary"] = rank_summary

    # 6. Classifier scénario par claim
    def classify(r):
        in_bm25 = r["rank_bm25"] is not None
        in_vec = r["rank_vector"] is not None
        in_rrf = r["rank_rrf"] is not None
        in_ce = r["rank_ce"] is not None
        if in_ce:
            return "OK (in CE top-5)"
        if in_rrf:
            return "A (in RRF top-50, lost by CE)"
        if in_bm25 or in_vec:
            return "B (in BM25/Vector top-50, lost by RRF fusion)"
        return "C/D (not in any top-50, indexation or N too low)"

    for r in rank_summary:
        r["scenario"] = classify(r)

    return out


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.clients.embeddings import EmbeddingModelManager
    from knowbase.common.clients.reranker import get_cross_encoder

    print("=" * 70)
    print("P2.4-PRE Recall Audit — 15 questions factual")
    print("=" * 70)

    # Init dépendances
    print("\nInit clients...")
    neo4j = get_neo4j_client()
    emb_mgr = EmbeddingModelManager()
    embedder = lambda text: emb_mgr.encode([text])[0].tolist()
    reranker = get_cross_encoder(model_name="BAAI/bge-reranker-v2-m3", device="cpu")

    # Load bench Config C results
    bench_path = ROOT / "data/benchmark/a38_runtime_v6/run_20260524_084344.json"
    with open(bench_path, "r", encoding="utf-8") as f:
        bench = json.load(f)
    factual = [r for r in bench["results_50q"] if r["primary_type"] == "factual"]
    print(f"\nLoaded {len(factual)} factual questions from Config C bench")

    audit_results = []
    for i, r in enumerate(factual, 1):
        qid = r["id"]
        question = r["question"]
        gt = r.get("ground_truth_answer", "")
        score = r["judge_score"]

        print(f"\n[{i}/{len(factual)}] {qid} score={score} | {question[:80]}")

        # Identifier candidats claim_id (search Neo4j full-text)
        candidates = find_expected_claims(neo4j, question, gt, limit=20)
        if not candidates:
            print("  → 0 candidate found via full-text search")
            audit_results.append({
                "id": qid, "question": question, "score": score,
                "candidates": [], "ranks": None, "verdict": "no_candidate_found",
            })
            continue

        # Top-3 candidats
        candidate_ids = [c["claim_id"] for c in candidates[:3]]
        print(f"  Top-3 candidates: {[c['claim_id'][:14] for c in candidates[:3]]}")
        for c in candidates[:3]:
            print(f"    - {c['claim_id'][:14]}  subj={c['subject_canonical']}  text={c['text'][:100]}")

        # Mesurer rangs
        ranks = retrieval_ranks(neo4j, embedder, reranker, question, candidate_ids)
        for r_entry in ranks["rank_summary"]:
            print(f"    {r_entry['claim_id'][:14]}: BM25={r_entry['rank_bm25']} Vec={r_entry['rank_vector']} RRF={r_entry['rank_rrf']} CE={r_entry['rank_ce']} → {r_entry['scenario']}")

        audit_results.append({
            "id": qid, "question": question, "score": score,
            "candidates_summary": [{"claim_id": c["claim_id"], "text_excerpt": c["text"][:150]} for c in candidates[:3]],
            "ranks": ranks["rank_summary"],
            "verdict": "audited",
        })

    # Persister
    out_path = ROOT / "data/benchmark/p2_recall_audit_20260524.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, ensure_ascii=False, indent=2)
    print(f"\nResults persisted: {out_path}")

    # Distribution scénarios
    scenarios = {}
    for r in audit_results:
        if r["verdict"] != "audited":
            scenarios[r["verdict"]] = scenarios.get(r["verdict"], 0) + 1
            continue
        # Prendre le best scenario (premier candidat trouvé en top-5)
        best = None
        for rk in r["ranks"]:
            if "OK" in rk["scenario"]:
                best = rk["scenario"]
                break
            if best is None or "A" in rk["scenario"]:
                best = rk["scenario"]
        scenarios[best] = scenarios.get(best, 0) + 1

    print("\n" + "=" * 70)
    print("DISTRIBUTION SCÉNARIOS")
    print("=" * 70)
    for s, n in sorted(scenarios.items(), key=lambda x: -x[1]):
        print(f"  {n:2d} : {s}")


if __name__ == "__main__":
    main()
