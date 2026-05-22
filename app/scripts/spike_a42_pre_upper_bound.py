"""A4.2-PRE — Spike validation gain upper bound.

Pour chaque question A3.8 (20q), trace les claims sémantiquement proches
de la question via embeddings (claim_text vs question). Compte ceux avec
subject_canonical=NULL — ce sont les claims actuellement invisibles au
runtime_v6 mais qui pourraient devenir queryable si A4.2 livré.

Calcul upper bound théorique du gain :
- Pour chaque question, si ≥1 NULL pertinent existe → A4.2 pourrait la sauver
- Estimer combien des 15 fails à judge=0.0 ont ce profil
- Si < 4-5 questions sauvables → gain < +0.10pp → revoir priorité

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/spike_a42_pre_upper_bound.py'
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("spike_a42_pre")


# Seuil cosine similarity pour considérer un claim "pertinent" pour la question
SIMILARITY_THRESHOLD = 0.50
# Top-K claims candidats à inspecter par question
TOP_K_CANDIDATES = 30


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    n1 = sum(x * x for x in v1) ** 0.5
    n2 = sum(x * x for x in v2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    sim = dot / (n1 * n2)
    return max(0.0, min(1.0, sim))


def _claim_searchable_text(claim: Dict[str, Any]) -> str:
    """Concat des champs textuels pour scoring sémantique."""
    parts = []
    if claim.get("subject_canonical"):
        parts.append(claim["subject_canonical"])
    if claim.get("predicate"):
        parts.append(claim["predicate"].replace("_", " ").lower())
    if claim.get("text"):
        parts.append(claim["text"])
    elif claim.get("verbatim_quote"):
        parts.append(claim["verbatim_quote"])
    return " ".join(parts).strip()


def fetch_all_claims(neo4j) -> List[Dict[str, Any]]:
    """Charge tous les claims tenant=default avec leurs propriétés clés."""
    rows = neo4j.execute_query(
        """
        MATCH (c:Claim {tenant_id: 'default'})
        RETURN c.claim_id AS claim_id,
               c.subject_canonical AS subject_canonical,
               c.predicate AS predicate,
               c.text AS text,
               c.verbatim_quote AS verbatim_quote,
               c.claim_type AS claim_type
        """,
    )
    return rows


def encode_batch(texts: List[str], mgr) -> List[List[float]]:
    """Encode batch via Sentence Transformer manager."""
    vectors = mgr.encode(texts)
    return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.clients.embeddings import EmbeddingModelManager

    neo = get_neo4j_client()
    mgr = EmbeddingModelManager()

    # Charge gold-set + run A3.11 (pour connaître les fails actuels)
    with open("/app/benchmark/questions/gold_set_a38_50q.json") as f:
        gold = json.load(f)
    questions = gold[:20]

    # Charge le run A3.11 (post-stratification) pour comparer
    last_run_path = Path("/app/data/benchmark/a38_runtime_v6/run_20260522_085016.json")
    with open(last_run_path) as f:
        last_run = json.load(f)
    last_run_by_id = {r["id"]: r for r in last_run["results_50q"]}

    print("\n" + "=" * 80)
    print("A4.2-PRE SPIKE — Upper bound théorique gain")
    print("=" * 80)

    # Charge tous les claims (11622)
    print("\n[1/4] Loading all claims from KG...")
    t0 = time.perf_counter()
    all_claims = fetch_all_claims(neo)
    print(f"  → {len(all_claims)} claims loaded in {time.perf_counter()-t0:.1f}s")

    # Encoder claim_texts en batch
    print("\n[2/4] Encoding claim texts (Sentence Transformer e5-large)...")
    t0 = time.perf_counter()
    claim_texts = [_claim_searchable_text(c) for c in all_claims]
    # Filter empty
    valid_idx = [i for i, t in enumerate(claim_texts) if t]
    valid_texts = [claim_texts[i] for i in valid_idx]
    # Batch encoding
    BATCH = 32
    claim_vecs: List[List[float]] = []
    for batch_start in range(0, len(valid_texts), BATCH):
        batch = valid_texts[batch_start:batch_start + BATCH]
        vecs = encode_batch(batch, mgr)
        claim_vecs.extend(vecs)
        if batch_start % (BATCH * 10) == 0:
            print(f"  → encoded {len(claim_vecs)}/{len(valid_texts)}")
    print(f"  → encoded {len(claim_vecs)} claims in {time.perf_counter()-t0:.1f}s")

    # Encoder questions
    print("\n[3/4] Encoding questions...")
    question_texts = [q["question"] for q in questions]
    question_vecs = encode_batch(question_texts, mgr)
    print(f"  → encoded {len(question_vecs)} questions")

    # Pour chaque question : top-K claims par sim + count NULL pertinents
    print("\n[4/4] Computing top-K relevant claims per question...")
    results_per_q = []
    for q_idx, (q, q_vec) in enumerate(zip(questions, question_vecs)):
        sims = []
        for local_i, claim_vec in enumerate(claim_vecs):
            sim = cosine_similarity(q_vec, claim_vec)
            sims.append((valid_idx[local_i], sim))
        sims.sort(key=lambda t: t[1], reverse=True)
        topk = sims[:TOP_K_CANDIDATES]
        relevant_topk = [(idx, s) for idx, s in topk if s >= SIMILARITY_THRESHOLD]

        # Compter NULL parmi relevant
        n_null_relevant = 0
        n_filled_relevant = 0
        null_examples = []
        for idx, sim in relevant_topk:
            claim = all_claims[idx]
            if claim["subject_canonical"] is None:
                n_null_relevant += 1
                if len(null_examples) < 3:
                    null_examples.append({
                        "claim_id": claim["claim_id"],
                        "sim": round(sim, 3),
                        "text": (claim["text"] or claim["verbatim_quote"] or "")[:120],
                    })
            else:
                n_filled_relevant += 1

        # Status actuel du run (judge_score)
        judge_score = last_run_by_id.get(q["id"], {}).get("judge_score", None)

        results_per_q.append({
            "id": q["id"],
            "primary_type": q.get("primary_type"),
            "question_short": q["question"][:80],
            "n_relevant_topk": len(relevant_topk),
            "n_null_relevant": n_null_relevant,
            "n_filled_relevant": n_filled_relevant,
            "current_judge_score": judge_score,
            "null_examples": null_examples,
        })

    # Agrégation
    print("\n" + "=" * 80)
    print("RÉSULTATS")
    print("=" * 80)

    # Affichage par question
    print(f"\n{'id':35s} type        score  n_relev  n_NULL  n_FILL  potentiel_gain")
    n_savable = 0
    n_already_ok = 0
    for r in results_per_q:
        qid = r["id"][:33]
        typ = (r["primary_type"] or "")[:10]
        score = r["current_judge_score"] if r["current_judge_score"] is not None else 0.0
        n_rel = r["n_relevant_topk"]
        n_null = r["n_null_relevant"]
        n_fil = r["n_filled_relevant"]
        # Potentiel : la question est récupérable si actuellement <1.0 ET ≥1 NULL pertinent existe
        is_savable = (score < 1.0) and (n_null >= 1)
        if is_savable:
            n_savable += 1
        if score >= 1.0:
            n_already_ok += 1
        flag = "★ SAVABLE" if is_savable else ("OK" if score >= 1.0 else "  -")
        print(f"  {qid:33s} {typ:10s}  {score:.1f}    {n_rel:3d}    {n_null:3d}    {n_fil:3d}    {flag}")

    print(f"\n  Questions déjà à 1.0 : {n_already_ok}/20")
    print(f"  Questions 'SAVABLE' (score<1.0 ET ≥1 NULL pertinent) : {n_savable}/20")

    # Upper bound théorique
    # Hypothèse : si A4.2 livré parfaitement, chaque question SAVABLE pourrait monter à 0.5-1.0
    # Optimiste : toutes montent à 1.0 → +0.5pp ou +1.0pp par question
    # Réaliste : moitié monte à 0.5, moitié reste 0 → +0.25pp par question savable
    optimist_gain = (n_savable * 1.0) / 20  # toutes savables → 1.0
    realist_gain_05 = (n_savable * 0.5) / 20  # toutes savables → 0.5
    realist_gain_03 = (n_savable * 0.3) / 20  # toutes savables → 0.3 (env. 30% conversion)

    print(f"\nUpper bound théorique C1 (gain par rapport à 0.175 actuel) :")
    print(f"  - Optimiste (toutes savables → judge=1.0) : +{optimist_gain:.3f}pp")
    print(f"  - Réaliste (toutes savables → judge=0.5)  : +{realist_gain_05:.3f}pp")
    print(f"  - Conservateur (savables → judge=0.3 avg) : +{realist_gain_03:.3f}pp")

    # Gate decision
    print(f"\n  GATE BLOQUANT A4.2 (seuil +0.10pp) :")
    if realist_gain_05 >= 0.10:
        print(f"  ✅ PASS — gain réaliste >= +0.10pp → A4.2 peut démarrer avec confiance")
    elif realist_gain_03 >= 0.10:
        print(f"  ⚠ MARGINAL — gain conservateur >= +0.10pp, réaliste {realist_gain_05:.3f}pp")
        print(f"     A4.2 raisonnable mais surveiller le ROI")
    else:
        print(f"  ❌ FAIL — gain réaliste < +0.10pp → revoir priorité A4")
        print(f"     Le vrai levier est probablement ailleurs (retrieval Qdrant, prompt Synthesize, etc.)")

    # Examples qualitatifs
    print(f"\n--- Examples de claims NULL pertinents (top-3) ---")
    for r in results_per_q[:5]:
        if r["null_examples"]:
            print(f"\n  Q: {r['question_short']}")
            for ex in r["null_examples"]:
                print(f"    [{ex['claim_id']}] sim={ex['sim']:.2f} text={ex['text']!r}")

    # Persist
    out_dir = Path("/app/data/benchmark/a42_pre_spike")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"spike_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "top_k": TOP_K_CANDIDATES,
            "n_total_claims": len(all_claims),
            "n_savable_questions": n_savable,
            "gain_optimist": optimist_gain,
            "gain_realist_05": realist_gain_05,
            "gain_realist_03": realist_gain_03,
            "per_question": results_per_q,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nDétails : {out_file}")


if __name__ == "__main__":
    main()
