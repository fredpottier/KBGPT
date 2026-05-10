"""
CH-47 — Bench intermédiaire 60q sur catégories régressées (causal/temporal/comparison/lifecycle).

Sélectionne 60 questions stratifiées depuis le bench V3_S0_BASELINE qui régressaient le plus
en V4_CH46_POSTOPT. Appelle /api/runtime_v4/answer en sériel (V4_REASONING_MODE_ENABLED=true).

Capture pour chaque question :
  - V3_S0 score (référence)
  - V4_CH46 score (régression actuelle)
  - V4.1 routing_decision (reasoning_path ou V4 path)
  - V4.1 ANSWER vs ABSTAIN
  - V4.1 atomic_facts + relational_facts count

Output : data/audit/ch47_bench_60q.json
Rapport : récup ABSTAIN rate + delta vs V3 sur les mêmes questions.
"""
from __future__ import annotations
import json
import random
import time
from pathlib import Path
from collections import defaultdict
import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"

V3_BASELINE = Path("/app/data/benchmark/results/robustness_run_20260505_163544_V3_S0_BASELINE.json")
V4_CH46 = Path("/app/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json")
OUT = Path("/app/data/audit/ch47_bench_60q.json")

# Catégories régressées les plus fortes (cf ADR §10.1) à benchmarker
TARGET_CATEGORIES = [
    "causal_why",
    "hypothetical",
    "lifecycle_supersedes",
    "lifecycle_evolves_from",
    "lifecycle_filtering_active",
    "anchor_applicability_temporal",
    "multi_hop",
    "synthesis_large",
    "conditional",
    "temporal_evolution",
    "anchor_scope_hierarchy",
]
N_PER_CATEGORY = 6  # 11 cat × 6 = ~66, on capera à 60


def main():
    print(f"Loading V3_S0 baseline...")
    v3 = json.loads(V3_BASELINE.read_text(encoding="utf-8"))
    v3_by_qid = {s["question_id"]: s for s in v3["per_sample"]}

    print(f"Loading V4_CH46_POSTOPT...")
    v4 = json.loads(V4_CH46.read_text(encoding="utf-8"))
    v4_by_qid = {s["question_id"]: s for s in v4["per_sample"]}

    # Stratifier
    by_cat = defaultdict(list)
    for qid, s in v3_by_qid.items():
        cat = s.get("evaluation", {}).get("category") or s.get("category")
        if cat in TARGET_CATEGORIES:
            by_cat[cat].append(qid)

    rng = random.Random(42)
    selected = []
    for cat in TARGET_CATEGORIES:
        candidates = by_cat.get(cat, [])
        rng.shuffle(candidates)
        chosen = candidates[:N_PER_CATEGORY]
        selected.extend([(qid, cat) for qid in chosen])

    selected = selected[:60]
    print(f"Selected {len(selected)} questions across {len(set(c for _, c in selected))} categories")

    results = []
    for i, (qid, cat) in enumerate(selected, 1):
        v3_sample = v3_by_qid[qid]
        question = v3_sample.get("question", "")
        v3_score = v3_sample.get("evaluation", {}).get("score")
        if v3_score is None:
            v3_score = 0.0
        v4_sample = v4_by_qid.get(qid, {})
        v4_score = v4_sample.get("evaluation", {}).get("score")
        if v4_score is None:
            v4_score = 0.0

        print(f"\n[{i}/{len(selected)}] {qid} ({cat}) | V3={v3_score:.2f} V4_CH46={v4_score:.2f}")
        print(f"  Q: {question[:120]}")

        t0 = time.time()
        try:
            resp = requests.post(API, json={"question": question, "top_k_claims": 12}, timeout=300)
            wall = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}")
                results.append({"qid": qid, "category": cat, "error": f"http_{resp.status_code}"})
                continue
            data = resp.json()
        except Exception as exc:
            print(f"  EXC {exc}")
            results.append({"qid": qid, "category": cat, "error": str(exc)})
            continue

        primary = data.get("primary_type")
        routing = data.get("routing_decision")
        decision = data.get("decision")
        ff = data.get("facts_first") or {}
        n_atomic = len(ff.get("atomic_facts") or [])
        n_rel = len(ff.get("relational_facts") or [])
        is_reasoning = routing == "reasoning_path"
        answer = (data.get("answer") or "")[:300]

        flag = "✓R" if is_reasoning else " ·"
        print(f"  {flag} primary={primary} routing={routing} decision={decision} | atomic={n_atomic} rel={n_rel} | wall={wall}ms")
        results.append({
            "qid": qid, "category": cat, "question": question,
            "v3_score": v3_score, "v4_ch46_score": v4_score,
            "v41_decision": decision, "v41_routing": routing,
            "v41_primary": primary, "v41_is_reasoning": is_reasoning,
            "v41_n_atomic": n_atomic, "v41_n_relational": n_rel,
            "v41_wall_ms": wall,
            "v41_answer": data.get("answer"),
            "v41_doc_ids_cited": data.get("doc_ids_cited"),
        })

    # Stats
    print(f"\n=== STATS GLOBALES ({len(results)} questions) ===")
    n_ok = sum(1 for r in results if r.get("v41_decision") == "ANSWER")
    n_abst = sum(1 for r in results if r.get("v41_decision") == "ABSTAIN")
    n_reason = sum(1 for r in results if r.get("v41_is_reasoning"))
    n_err = sum(1 for r in results if "error" in r)
    print(f"ANSWER: {n_ok}/{len(results)} ({n_ok / max(len(results),1) * 100:.0f}%)")
    print(f"ABSTAIN: {n_abst}/{len(results)} ({n_abst / max(len(results),1) * 100:.0f}%)")
    print(f"REASONING_PATH activé: {n_reason}/{len(results)}")
    print(f"Erreurs: {n_err}/{len(results)}")

    # Stats par catégorie
    print(f"\n=== STATS PAR CATÉGORIE ===")
    print(f"{'category':<32} {'n':>3} {'V3 mean':>8} {'V4_CH46 mean':>12} {'V4.1 ANSWER%':>12} {'reasoning%':>10}")
    by_cat_stats = defaultdict(list)
    for r in results:
        if "error" in r:
            continue
        by_cat_stats[r["category"]].append(r)
    for cat in TARGET_CATEGORIES:
        items = by_cat_stats.get(cat, [])
        if not items:
            continue
        v3_mean = sum(it["v3_score"] for it in items) / len(items)
        v4_mean = sum(it["v4_ch46_score"] for it in items) / len(items)
        n_answer = sum(1 for it in items if it.get("v41_decision") == "ANSWER")
        n_reason_cat = sum(1 for it in items if it.get("v41_is_reasoning"))
        print(f"{cat:<32} {len(items):>3} {v3_mean:>8.2f} {v4_mean:>12.2f} "
              f"{n_answer/len(items)*100:>11.0f}% {n_reason_cat/len(items)*100:>9.0f}%")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUT}")


if __name__ == "__main__":
    main()
