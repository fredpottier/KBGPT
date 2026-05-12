"""CH-48 — Analyse déviation au gold-set v4 sur subset Robust × gold (63 questions).

Compare CH-46_POSTOPT (Qwen-72B DeepInfra) vs CH-48_LLAMA_TURBO_TOGETHER (Llama-Turbo)
sur les 63 questions communes au gold_set_v4.

Métriques de déviation déjà disponibles :
  - structured_metrics.item_recall : couverture des items attendus (listes)
  - structured_metrics.exact_match : match identifiers exacts
  - structured_metrics.citation : citations [doc=...] présentes
  - structured_metrics.coverage : couverture sémantique
  - structured_metrics.structured_avg : moyenne agrégée

L'idéal absolu = 1.000 sur structured_avg. La distance à 1.000 = déviation au gold.
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

GOLD_PATH = Path("/app/benchmark/questions/gold_set_v4.json")
CH48_PATHS = [
    Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
    Path("/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
]
CH48_PATH = next((p for p in CH48_PATHS if p.exists()), CH48_PATHS[0])
CH46_PATHS = [
    Path("/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
    Path("/app/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
]

gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
gold_by_source_id = {q.get("source_id"): q for q in gold if q.get("source_id")}
print(f"Gold-set v4 : {len(gold)} questions ({len(gold_by_source_id)} avec source_id)")

ch48 = json.loads(CH48_PATH.read_text(encoding="utf-8"))
ch46_path = next((p for p in CH46_PATHS if p.exists()), None)
ch46 = json.loads(ch46_path.read_text(encoding="utf-8"))
print(f"CH-48 : {len(ch48['per_sample'])} samples | CH-46 : {len(ch46['per_sample'])} samples")


def build_index(samples: list, gold_by_sid: dict) -> dict:
    """Index samples par original_id + lookup gold."""
    out = {}
    for s in samples:
        oid = s.get("original_id")
        if oid and oid in gold_by_sid:
            out[oid] = {"sample": s, "gold": gold_by_sid[oid]}
    return out


idx48 = build_index(ch48["per_sample"], gold_by_source_id)
idx46 = build_index(ch46["per_sample"], gold_by_source_id)
common = set(idx48.keys()) & set(idx46.keys())
print(f"\nIntersection CH-46 ∩ CH-48 ∩ gold : {len(common)} questions")


def get_metrics(sample: dict) -> dict:
    sm = sample.get("structured_metrics") or {}
    judge = (sample.get("evaluation") or {}).get("score")
    return {
        "item_recall": sm.get("item_recall"),
        "exact_match": sm.get("exact_match"),
        "citation": sm.get("citation"),
        "coverage": sm.get("coverage"),
        "structured_avg": sm.get("structured_avg"),
        "applicable": sm.get("applicable"),
        "judge": judge,
    }


# Agrégation globale et par primary_type
def aggregate(idx: dict, common_ids: set) -> tuple[dict, dict]:
    by_type = defaultdict(lambda: defaultdict(list))
    overall = defaultdict(list)
    for oid in common_ids:
        s = idx[oid]["sample"]
        g = idx[oid]["gold"]
        ptype = g.get("primary_type") or "?"
        m = get_metrics(s)
        for k, v in m.items():
            if isinstance(v, (int, float)):
                overall[k].append(v)
                by_type[ptype][k].append(v)
    return overall, by_type


ov48, bt48 = aggregate(idx48, common)
ov46, bt46 = aggregate(idx46, common)

print("\n" + "=" * 90)
print("DÉVIATION AU GOLD (idéal = 1.000) — moyenne sur 63 questions communes")
print("=" * 90)
print(f"{'metric':20s} | {'CH-46':>8s} | {'CH-48':>8s} | {'Δ':>10s} | {'écart idéal CH-48':>18s}")
print("-" * 90)
for k in ["structured_avg", "item_recall", "exact_match", "citation", "coverage", "judge"]:
    v46 = statistics.mean(ov46[k]) if ov46[k] else 0
    v48 = statistics.mean(ov48[k]) if ov48[k] else 0
    delta = v48 - v46
    deviation = 1.0 - v48
    arrow = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "·")
    print(f"{k:20s} | {v46:>8.3f} | {v48:>8.3f} | {arrow}{delta:>+8.3f} | {deviation:>+8.3f} (manque)")

print("\n" + "=" * 90)
print("DÉVIATION PAR PRIMARY_TYPE — structured_avg moyen")
print("=" * 90)
print(f"{'primary_type':20s} | {'n':>3s} | {'CH-46':>8s} | {'CH-48':>8s} | {'Δ':>10s} | {'idéal-CH48':>10s}")
print("-" * 90)
all_types = sorted(set(list(bt48.keys()) + list(bt46.keys())))
for t in all_types:
    n = len(bt48[t].get("structured_avg", []))
    if n == 0:
        continue
    v48 = statistics.mean(bt48[t]["structured_avg"])
    v46 = statistics.mean(bt46[t].get("structured_avg") or [0])
    delta = v48 - v46
    dev = 1.0 - v48
    arrow = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "·")
    print(f"{t:20s} | {n:>3d} | {v46:>8.3f} | {v48:>8.3f} | {arrow}{delta:>+8.3f} | {dev:>+8.3f}")

# Top-10 questions avec plus grande dégradation CH-48 vs CH-46
print("\n" + "=" * 90)
print("TOP-10 questions où CH-48 dévie davantage que CH-46 (régressions)")
print("=" * 90)
deltas = []
for oid in common:
    m48 = get_metrics(idx48[oid]["sample"])
    m46 = get_metrics(idx46[oid]["sample"])
    if m48["structured_avg"] is not None and m46["structured_avg"] is not None:
        deltas.append({
            "oid": oid,
            "ptype": idx48[oid]["gold"].get("primary_type"),
            "d_struct": m48["structured_avg"] - m46["structured_avg"],
            "ch46_struct": m46["structured_avg"],
            "ch48_struct": m48["structured_avg"],
            "question": idx48[oid]["gold"].get("question", "")[:100],
        })
deltas.sort(key=lambda x: x["d_struct"])
print(f"{'oid':35s} | {'type':12s} | {'CH-46':>6s} | {'CH-48':>6s} | {'Δ':>6s}")
print("-" * 90)
for d in deltas[:10]:
    print(f"{d['oid']:35s} | {d['ptype'] or '?':12s} | {d['ch46_struct']:>6.3f} | {d['ch48_struct']:>6.3f} | {d['d_struct']:>+6.3f}")

print("\n" + "=" * 90)
print("TOP-10 questions où CH-48 s'améliore le plus")
print("=" * 90)
print(f"{'oid':35s} | {'type':12s} | {'CH-46':>6s} | {'CH-48':>6s} | {'Δ':>6s}")
print("-" * 90)
for d in deltas[-10:][::-1]:
    print(f"{d['oid']:35s} | {d['ptype'] or '?':12s} | {d['ch46_struct']:>6.3f} | {d['ch48_struct']:>6.3f} | {d['d_struct']:>+6.3f}")
