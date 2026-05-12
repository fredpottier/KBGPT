"""POC Phase 1.C — Bench 30q stratifié POC vs baseline V4.1.

30 questions stratifiées (5/type) sur le subset Robust × gold v5 :
  - 5 factual (TEMP_active possible escalation)
  - 5 list
  - 5 temporal (escalation expected)
  - 5 causal
  - 5 unanswerable
  - 5 multi_hop

Compare :
  - POC : /api/runtime_v4_poc/answer
  - V4.1 : on lit les résultats du Robust CH-48 déjà effectué (cache)

Métriques :
  - structured_avg (post-score sur gold v5)
  - judge_score (déjà calculé pour V4.1, à recalculer pour POC via Llama-3.3-70B)
  - latency
  - layer (layer0 | layer1_temporal_active)
"""
from __future__ import annotations
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path

import requests

API_POC = "http://knowbase-app:8000/api/runtime_v4_poc/answer"
GOLD_V5 = json.loads(Path("/app/benchmark/questions/gold_set_v5.json").read_text(encoding="utf-8"))
gv5_by_sid = {q["source_id"]: q for q in GOLD_V5}

CH48_RB = json.loads(
    Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json")
    .read_text(encoding="utf-8")
)
ch48_by_oid = {s.get("original_id"): s for s in CH48_RB["per_sample"]}

SEED = 42
N_PER_TYPE = 5
TYPES = ["factual", "list", "temporal", "causal", "unanswerable", "multi_hop"]


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def fuzzy_in(needle: str, haystack: str) -> bool:
    n = normalize(needle); h = normalize(haystack)
    if not n: return False
    if n in h: return True
    n_tok = set(re.findall(r"\w+", n))
    if len(n_tok) <= 2: return False
    h_tok = set(re.findall(r"\w+", h))
    return len(n_tok & h_tok) / len(n_tok) >= 0.6


def score_sample(answer: str, gold: dict) -> dict:
    gt = gold.get("ground_truth") or {}
    out = {}
    # exact_match
    eids = gt.get("exact_identifiers") or []
    if eids:
        n = sum(1 for x in eids if normalize(x) in normalize(answer))
        out["exact_match"] = n / len(eids)
    # citation
    docs = gt.get("supporting_doc_ids") or []
    if docs:
        cited_marker = set(re.findall(r"\[doc=([^\]]+)\]", answer))
        cited_text = sum(1 for d in docs if d and d in answer)
        n_cited = sum(1 for d in docs if d in cited_marker) + cited_text
        out["citation"] = min(n_cited, len(docs)) / len(docs)
    # item_recall
    items = gt.get("list_items_expected") or []
    if items:
        n = sum(1 for it in items if fuzzy_in(it, answer))
        out["item_recall"] = n / len(items)
    # Abstain correct
    if gt.get("answerability") == "unanswerable":
        markers = ["pas trouv", "not found", "non disponible", "not available"]
        is_abstain = any(m in normalize(answer) for m in markers)
        out["abstain_correct"] = 1.0 if is_abstain else 0.0

    valid = [v for v in out.values() if v is not None]
    out["structured_avg"] = sum(valid) / len(valid) if valid else 0.0
    return out


def stratified_sample() -> list[dict]:
    """Sélectionne 5 questions par type depuis gold v5 ∩ Robust CH-48."""
    rng = random.Random(SEED)
    by_type = defaultdict(list)
    for s in CH48_RB["per_sample"]:
        oid = s.get("original_id")
        if not oid or oid not in gv5_by_sid:
            continue
        gold = gv5_by_sid[oid]
        if gold["primary_type"] in TYPES:
            by_type[gold["primary_type"]].append((oid, gold, s))
    sample = []
    for t in TYPES:
        pool = by_type[t]
        rng.shuffle(pool)
        sample.extend(pool[:N_PER_TYPE])
    return sample


def main():
    sample = stratified_sample()
    print(f"Bench POC 30q stratifié — {len(sample)} questions\n")

    rows = []
    for i, (oid, gold, ch48_sample) in enumerate(sample, 1):
        q = gold["question"]
        ptype = gold["primary_type"]
        print(f"[{i}/{len(sample)}] {oid} ({ptype})")
        print(f"  Q: {q[:120]}")

        # POC call
        t0 = time.time()
        try:
            resp = requests.post(API_POC, json={"question": q, "top_k_claims": 12}, timeout=120)
            wall = int((time.time() - t0) * 1000)
            data = resp.json() if resp.status_code == 200 else None
        except Exception as exc:
            print(f"  POC EXC {exc}")
            data = None
            wall = int((time.time() - t0) * 1000)

        if data:
            poc_struct = score_sample(data.get("answer", ""), gold)
            poc_decision = data.get("decision", "?")
            poc_layer = data.get("layer", "?")
            print(f"  POC: layer={poc_layer} decision={poc_decision} struct_avg={poc_struct['structured_avg']:.3f} wall={wall}ms")
            print(f"       answer: {(data.get('answer') or '')[:160]}")
        else:
            poc_struct = {"structured_avg": 0.0}
            poc_decision = "ERROR"
            poc_layer = "?"

        # V4.1 baseline (cached)
        v41_struct = (ch48_sample.get("structured_metrics") or {}).get("structured_avg") or 0.0
        v41_judge = (ch48_sample.get("evaluation") or {}).get("score") or 0.0
        v41_answer = ch48_sample.get("answer", "")
        # Recalcul structured_avg V4.1 sur gold v5 pour comparaison équitable
        v41_struct_v5 = score_sample(v41_answer, gold).get("structured_avg", 0.0)

        delta = poc_struct["structured_avg"] - v41_struct_v5
        print(f"  V4.1: struct_avg(v5)={v41_struct_v5:.3f} judge={v41_judge:.2f}")
        print(f"  Δ struct_avg POC-V4.1 = {delta:+.3f}\n")

        rows.append({
            "oid": oid, "primary_type": ptype,
            "poc_layer": poc_layer, "poc_decision": poc_decision,
            "poc_struct": poc_struct["structured_avg"],
            "poc_wall_ms": wall,
            "poc_breakdown": data.get("latency_breakdown_ms") if data else None,
            "v41_struct_v5": v41_struct_v5,
            "v41_judge": v41_judge,
            "delta_struct": delta,
            "question": q[:120],
            "poc_answer": (data.get("answer") or "")[:200] if data else "",
        })

    # Aggregations
    print("\n" + "=" * 90)
    print("AGGREGATE par primary_type")
    print("=" * 90)
    print(f"{'type':12s} | {'n':>3s} | {'POC struct':>11s} | {'V4.1 struct(v5)':>15s} | {'Δ':>9s} | {'POC mean ms':>12s}")
    print("-" * 90)
    by_t = defaultdict(list)
    for r in rows:
        by_t[r["primary_type"]].append(r)
    for t in TYPES:
        rs = by_t[t]
        if not rs: continue
        avg_poc = sum(r["poc_struct"] for r in rs) / len(rs)
        avg_v41 = sum(r["v41_struct_v5"] for r in rs) / len(rs)
        delta = avg_poc - avg_v41
        avg_ms = sum(r["poc_wall_ms"] for r in rs) / len(rs)
        arrow = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "·")
        print(f"{t:12s} | {len(rs):>3d} | {avg_poc:>11.3f} | {avg_v41:>15.3f} | {arrow}{delta:>+8.3f} | {avg_ms:>10.0f}ms")

    print("-" * 90)
    g_poc = sum(r["poc_struct"] for r in rows) / len(rows)
    g_v41 = sum(r["v41_struct_v5"] for r in rows) / len(rows)
    g_delta = g_poc - g_v41
    g_ms = sum(r["poc_wall_ms"] for r in rows) / len(rows)
    print(f"{'GLOBAL':12s} | {len(rows):>3d} | {g_poc:>11.3f} | {g_v41:>15.3f} | {g_delta:>+9.3f} | {g_ms:>10.0f}ms")

    # Distribution layers POC
    layer_count = defaultdict(int)
    for r in rows:
        layer_count[r["poc_layer"]] += 1
    print(f"\nLayers POC: {dict(layer_count)}")

    # Persist
    out = Path("/app/data/audit/ch49_poc_bench_30q.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "summary": {
        "global_poc_struct": g_poc, "global_v41_struct_v5": g_v41, "delta": g_delta,
        "mean_latency_ms": g_ms, "layer_count": dict(layer_count),
    }}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Persisted → {out}")


if __name__ == "__main__":
    main()
