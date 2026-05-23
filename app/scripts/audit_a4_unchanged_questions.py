"""A4.4 — Audit des 18 questions inchangées post-A4 pour identifier la cause racine.

Test 3 hypothèses :
- H1 : Subject_resolver A3.9 ne trouve pas les nouveaux subject_canonical
       (path Entity manquant). Mesure : combien de claims sémantiquement
       pertinents sont MAINTENANT en KG mais PAS retournés par Execute ?
- H2 : Synthesize cite les mauvais claims malgré l'accès.
       Mesure : claims retournés par Execute vs claims cités dans answer_text.
- H5 : LLM-judge trop strict (sous-évalue abstentions).
       Mesure : reasoning du judge sur cas 0.0, comparer à GT.

Pour chaque des 18 inchangées :
1. Récupère claims sémantiquement pertinents (cosine sim ≥ 0.5)
2. Compte ceux maintenant rempli subject_canonical (post-A4.3)
3. Cross-check avec ce que le runtime a retourné (run_20260522_121240.json)
4. Classifie en cat :
   - A) Bien accédés ET cités, mais réponse mauvaise → variance Synthesize
   - B) Accédés, non cités → Synthesize filtre mal
   - C) Pas accédés (alors qu'en KG) → Subject_resolver rate
   - D) Pas en KG du tout → vraie absence

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/audit_a4_unchanged_questions.py'
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


SIMILARITY_THRESHOLD = 0.55  # un peu plus strict que A4.2-PRE (0.50)
TOP_K_PER_QUESTION = 20


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    n1 = sum(x * x for x in v1) ** 0.5
    n2 = sum(x * x for x in v2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    sim = dot / (n1 * n2)
    return max(0.0, min(1.0, sim))


def _claim_text(claim: Dict[str, Any]) -> str:
    parts = []
    if claim.get("subject_canonical"):
        parts.append(claim["subject_canonical"])
    if claim.get("predicate"):
        parts.append(str(claim["predicate"]).replace("_", " ").lower())
    if claim.get("text"):
        parts.append(claim["text"])
    elif claim.get("verbatim_quote"):
        parts.append(claim["verbatim_quote"])
    return " ".join(parts).strip()


def extract_cited_claim_ids(answer_text: str) -> Set[str]:
    """Extrait les claim_ids cités dans answer_text via [claim_id=...]."""
    return set(re.findall(r"\[claim_id=([a-z0-9_]+)\]", answer_text))


def claims_returned_by_execute(run_result: Dict[str, Any]) -> Set[str]:
    """Extrait les claim_ids retournés par Execute dans les iterations_trace."""
    claim_ids: Set[str] = set()
    iters = run_result.get("run", {}).get("iterations_trace", [])
    for it in iters:
        eo = it.get("execute_output", {})
        if isinstance(eo, dict):
            for res in eo.get("results", []):
                if isinstance(res, dict):
                    for c in res.get("claims", []):
                        if isinstance(c, dict) and c.get("claim_id"):
                            claim_ids.add(c["claim_id"])
    return claim_ids


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.common.clients.embeddings import EmbeddingModelManager

    neo = get_neo4j_client()
    mgr = EmbeddingModelManager()

    # Charge les deux runs
    pre_path = "/app/data/benchmark/a38_runtime_v6/run_20260522_085016.json"
    post_path = "/app/data/benchmark/a38_runtime_v6/run_20260522_121240.json"
    with open(pre_path) as f:
        pre = json.load(f)
    with open(post_path) as f:
        post = json.load(f)
    pre_by_id = {r["id"]: r for r in pre["results_50q"]}
    post_by_id = {r["id"]: r for r in post["results_50q"]}

    # Identifier les 18 inchangées (post score == pre score, et != 1.0 pour les intéressantes)
    common_ids = sorted(set(pre_by_id) & set(post_by_id))
    unchanged = []
    for qid in common_ids:
        ps = pre_by_id[qid].get("judge_score", 0)
        qs = post_by_id[qid].get("judge_score", 0)
        if abs(qs - ps) < 0.01:  # unchanged
            unchanged.append({
                "id": qid,
                "question": pre_by_id[qid]["question"],
                "score": qs,
                "type": pre_by_id[qid].get("primary_type"),
                "ground_truth": pre_by_id[qid].get("ground_truth_answer", ""),
                "post_run": post_by_id[qid],
            })

    print("\n" + "=" * 90)
    print(f"AUDIT A4.4 — Hypothèses H1/H2/H5 sur {len(unchanged)} questions inchangées")
    print("=" * 90)

    # Charge tous les claims du KG (avec leur subject_canonical post-A4.3)
    print(f"\n[1/4] Charge tous les claims du KG ...")
    t0 = time.perf_counter()
    rows = neo.execute_query(
        """
        MATCH (c:Claim {tenant_id: 'default'})
        RETURN c.claim_id AS claim_id,
               c.subject_canonical AS subject_canonical,
               c.predicate AS predicate,
               c.text AS text,
               c.verbatim_quote AS verbatim_quote,
               c.marginal AS marginal
        """,
    )
    all_claims = rows
    claim_by_id = {c["claim_id"]: c for c in all_claims}
    print(f"  → {len(all_claims)} claims loaded in {time.perf_counter()-t0:.1f}s")

    # Encoder tous les claim_text
    print(f"\n[2/4] Encoding all claims (Sentence Transformer e5-large) ...")
    t0 = time.perf_counter()
    claim_texts = [_claim_text(c) for c in all_claims]
    valid_idx = [i for i, t in enumerate(claim_texts) if t]
    valid_texts = [claim_texts[i] for i in valid_idx]
    BATCH = 32
    claim_vecs: List[List[float]] = []
    for batch_start in range(0, len(valid_texts), BATCH):
        batch = valid_texts[batch_start:batch_start + BATCH]
        vecs = [v.tolist() for v in mgr.encode(batch)]
        claim_vecs.extend(vecs)
    print(f"  → encoded {len(claim_vecs)} in {time.perf_counter()-t0:.1f}s")

    # Encoder questions
    print(f"\n[3/4] Encoding {len(unchanged)} questions ...")
    q_texts = [u["question"] for u in unchanged]
    q_vecs = [v.tolist() for v in mgr.encode(q_texts)]

    # Analyse par question
    print(f"\n[4/4] Per-question analysis ...")
    results = []
    cat_counts = Counter()
    for u_idx, u in enumerate(unchanged):
        q_vec = q_vecs[u_idx]
        # Top-K claims pertinents
        sims = []
        for local_i, claim_vec in enumerate(claim_vecs):
            sim = cosine_similarity(q_vec, claim_vec)
            sims.append((valid_idx[local_i], sim))
        sims.sort(key=lambda t: t[1], reverse=True)
        relevant = [(idx, s) for idx, s in sims if s >= SIMILARITY_THRESHOLD][:TOP_K_PER_QUESTION]
        relevant_claim_ids = {all_claims[idx]["claim_id"] for idx, _ in relevant}

        # Subdiviser : combien parmi pertinents ont subject_canonical maintenant
        n_relevant = len(relevant)
        n_with_subject = sum(
            1 for idx, _ in relevant
            if all_claims[idx]["subject_canonical"] is not None
        )
        n_was_null_now_filled = sum(
            1 for idx, _ in relevant
            if all_claims[idx]["subject_canonical"] is not None
            and all_claims[idx].get("marginal") is None  # was NULL, now filled (not marginal)
        )

        # Comparer aux claims retournés par Execute
        post_returned = claims_returned_by_execute(u["post_run"])
        n_pertinent_returned = len(relevant_claim_ids & post_returned)
        n_pertinent_NOT_returned = n_relevant - n_pertinent_returned

        # Comparer aux claims cités dans answer
        answer_text = u["post_run"].get("run", {}).get("answer_text", "")
        cited = extract_cited_claim_ids(answer_text)
        n_returned_cited = len(post_returned & cited)
        n_returned_NOT_cited = len(post_returned - cited)

        # Classification primaire
        # A) Bien accédés ET cités, mais réponse mauvaise (variance Synthesize)
        # B) Accédés, non cités (Synthesize filtre mal)
        # C) Pas accédés (alors qu'en KG) (Subject_resolver rate)
        # D) Pas en KG du tout (vraie absence)
        if n_pertinent_returned >= 2 and n_returned_cited >= 1:
            cat = "A_variance_synthesize"
        elif n_pertinent_returned >= 1 and n_returned_cited == 0:
            cat = "B_synthesize_misselection"
        elif n_relevant >= 1 and n_pertinent_returned == 0:
            cat = "C_resolver_misses_filled"
        else:
            cat = "D_no_relevant_in_kg"
        cat_counts[cat] += 1

        # Sauvegarde
        results.append({
            "id": u["id"],
            "score": u["score"],
            "type": u["type"],
            "n_relevant": n_relevant,
            "n_with_subject": n_with_subject,
            "n_pertinent_returned": n_pertinent_returned,
            "n_pertinent_NOT_returned": n_pertinent_NOT_returned,
            "n_returned_cited": n_returned_cited,
            "n_returned_NOT_cited": n_returned_NOT_cited,
            "n_returned_total": len(post_returned),
            "n_cited_total": len(cited),
            "category": cat,
            "judge_reasoning": pre_by_id[u["id"]].get("judge_reasoning", "")[:200],
            "post_judge_reasoning": u["post_run"].get("judge_reasoning", "")[:200],
        })

    # Affichage
    print(f"\n{'id':35s} {'sc':>4s} {'type':12s} {'rel':>4s} {'subj':>4s} {'ret':>4s} {'cit':>4s} {'cat'}")
    for r in results:
        print(
            f"  {r['id'][:33]:33s} {r['score']:.1f}  {(r['type'] or '')[:10]:10s} "
            f"{r['n_relevant']:>3d}  {r['n_with_subject']:>3d}  "
            f"{r['n_pertinent_returned']:>3d}  {r['n_returned_cited']:>3d}  "
            f"{r['category']}"
        )

    print(f"\n--- Distribution par catégorie ---")
    for cat, n in cat_counts.most_common():
        print(f"  {cat:35s} : {n}/{len(unchanged)} ({n/len(unchanged):.0%})")

    # Conclusions H1/H2/H5
    print(f"\n=== HYPOTHÈSES — Verdicts ===")
    cat_c = cat_counts.get("C_resolver_misses_filled", 0)
    cat_b = cat_counts.get("B_synthesize_misselection", 0)
    cat_a = cat_counts.get("A_variance_synthesize", 0)
    cat_d = cat_counts.get("D_no_relevant_in_kg", 0)

    print(f"\nH1 (subject_resolver A3.9 rate les claims backfillés) :")
    print(f"  Questions où ≥1 claim pertinent EN KG mais PAS retourné: {cat_c}/{len(unchanged)}")
    if cat_c >= len(unchanged) // 3:
        print(f"  → ✅ H1 SUPPORTÉE : le resolver ne trouve pas les claims backfillés")
    else:
        print(f"  → ❌ H1 non supportée à ce niveau")

    print(f"\nH2 (Synthesize cite mal malgré accès) :")
    print(f"  Questions où claims accédés mais 0 cité (cat B) : {cat_b}/{len(unchanged)}")
    if cat_b >= len(unchanged) // 4:
        print(f"  → ✅ H2 SUPPORTÉE : Synthesize sélectionne mal")
    else:
        print(f"  → ❌ H2 non supportée à ce niveau")

    # H5 : judge reasoning sur cas 0.0
    print(f"\nH5 (Judge trop strict) :")
    zero_cases = [r for r in results if r["score"] == 0.0]
    abstain_mentions = sum(
        1 for r in zero_cases
        if "abstain" in (r.get("post_judge_reasoning") or "").lower()
        or "no relevant" in (r.get("post_judge_reasoning") or "").lower()
    )
    print(f"  Questions score=0 avec mention 'abstain'/'no relevant' : {abstain_mentions}/{len(zero_cases)}")
    if abstain_mentions >= len(zero_cases) // 3:
        print(f"  → ✅ H5 SUPPORTÉE : le judge pénalise des abstentions")

    # Persist
    out_dir = Path("/app/data/benchmark/a44_validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"unchanged_audit_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "n_unchanged": len(unchanged),
            "cat_distribution": dict(cat_counts),
            "results": results,
        }, f, indent=2, default=str)
    print(f"\nDétails : {out_file}")


if __name__ == "__main__":
    main()
