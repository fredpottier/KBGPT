"""
CH-47 Phase 0.B — Appelle l'API V4 sur les 5 top-deltas et capture facts_first complet.

Permet de classifier (1) Structurer abdique vs (2) Composer rate.

Usage : docker exec knowbase-app python /app/scripts/ch47_phase0b_capture.py
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"
INPUT = Path("/app/data/audit/ch47_mock_r3_top5.json")
OUTPUT = Path("/app/data/audit/ch47_phase0b_facts_first.json")


def classify_hypothesis(facts_first: dict | None, decision: str, n_chunks: int) -> dict:
    """Détermine si on est dans Hypothèse (1) Structurer abdique ou (2) Composer rate."""
    if not facts_first:
        return {"hypothesis": "unknown", "reason": "facts_first absent"}

    answerability = facts_first.get("answerability")
    coverage = facts_first.get("coverage_state")

    # Compter les facts/items extraits
    n_items = 0
    for ts in ["list_specific", "factual_specific", "temporal_specific", "comparison_specific", "causal_specific"]:
        spec = facts_first.get(ts) or {}
        for k in ("items", "facts", "timeline", "compared_facts", "causal_chains"):
            n_items += len(spec.get(k) or [])

    if n_chunks == 0:
        return {"hypothesis": "(0) retrieval_empty", "reason": "0 chunks retrieved"}

    if answerability == "unanswerable" and n_items == 0:
        return {"hypothesis": "(1) structurer_abdicates", "reason": f"answerability=unanswerable + 0 items extracted"}

    if answerability == "answerable" and n_items > 0 and decision == "ABSTAIN":
        return {"hypothesis": "(2) composer_fails_with_facts", "reason": f"answerable + {n_items} items but ABSTAIN"}

    if answerability == "answerable" and n_items > 0 and decision == "ANSWER":
        return {"hypothesis": "(2b) composer_short_answer", "reason": f"answerable + {n_items} items, ANSWER but short"}

    if answerability == "unanswerable" and n_items > 0:
        return {"hypothesis": "(1b) ambiguous", "reason": f"unanswerable but {n_items} items extracted"}

    return {"hypothesis": "other", "reason": f"answerability={answerability}, items={n_items}, decision={decision}"}


def main():
    candidates = json.loads(INPUT.read_text(encoding="utf-8"))
    print(f"Loaded {len(candidates)} candidates for Phase 0.B")
    results = []

    for i, c in enumerate(candidates, 1):
        qid = c["question_id"]
        cat = c["category"]
        question = c["question"]
        print(f"\n[{i}/{len(candidates)}] {qid} ({cat}) Δ={c['delta']:.2f}")
        print(f"  Q: {question[:140]}")

        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 12}, timeout=300)
            wall = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}")
                continue
            data = resp.json()
        except Exception as exc:
            print(f"  EXC {exc}")
            continue

        ff = data.get("facts_first") or {}
        decision = data.get("decision")
        n_chunks = data.get("n_chunks_retrieved", 0)
        answer = data.get("answer", "")
        chunks_used = data.get("chunks_used") or []

        cls = classify_hypothesis(ff, decision, n_chunks)
        print(f"  decision={decision} | n_chunks={n_chunks} | wall={wall}ms")
        print(f"  → {cls['hypothesis']}: {cls['reason']}")

        # Compact facts_first preview
        ff_preview = {
            "schema_version": ff.get("schema_version"),
            "answerability": ff.get("answerability"),
            "coverage_state": ff.get("coverage_state"),
            "primary_type": ff.get("primary_type"),
        }
        for ts in ["list_specific", "factual_specific", "temporal_specific", "comparison_specific", "causal_specific"]:
            spec = ff.get(ts) or {}
            for k in ("items", "facts", "timeline", "compared_facts", "causal_chains"):
                arr = spec.get(k)
                if arr:
                    ff_preview[f"{ts}.{k}_count"] = len(arr)

        print(f"  facts_first preview: {ff_preview}")

        results.append({
            "question_id": qid,
            "category": cat,
            "delta": c["delta"],
            "question": question,
            "v3_score": c["v3_score"],
            "v3_answer_full": c.get("v3_answer_full", ""),
            "v4_score": c["v4_score"],
            "v4_answer_full_runned_now": answer,
            "v4_decision": decision,
            "v4_n_chunks_retrieved": n_chunks,
            "v4_facts_first": ff,
            "v4_chunks_used_preview": chunks_used[:5],  # 5 premiers pour inspection
            "v4_wall_ms": wall,
            "ground_truth": c.get("ground_truth"),
            "hypothesis": cls,
        })

    # Stats
    print(f"\n=== HYPOTHÈSES ===")
    from collections import Counter
    hcounts = Counter(r["hypothesis"]["hypothesis"] for r in results)
    for h, n in hcounts.most_common():
        print(f"  {h}: {n}/{len(results)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUTPUT}")


if __name__ == "__main__":
    main()
