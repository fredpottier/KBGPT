"""CH-48 — Analyse détaillée des questions d'un type donné sur Robust × gold_v4.

Usage : docker exec knowbase-app python /app/scripts/ch48_analyze_type.py <type>
"""
import json
import sys
from pathlib import Path

GOLD = json.loads(Path("/app/benchmark/questions/gold_set_v4.json").read_text(encoding="utf-8"))
gold_by_sid = {q.get("source_id"): q for q in GOLD if q.get("source_id")}

CH48 = json.loads(Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json").read_text(encoding="utf-8"))

ch46_paths = [
    Path("/app/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
    Path("/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
]
CH46 = json.loads(next(p for p in ch46_paths if p.exists()).read_text(encoding="utf-8"))
ch46_by_oid = {s.get("original_id"): s for s in CH46["per_sample"]}

target_type = sys.argv[1] if len(sys.argv) > 1 else "factual"

filtered = []
for s in CH48["per_sample"]:
    oid = s.get("original_id")
    if not oid or oid not in gold_by_sid:
        continue
    g = gold_by_sid[oid]
    if g.get("primary_type") != target_type:
        continue
    filtered.append({
        "oid": oid,
        "gold": g,
        "ch48": s,
        "ch46": ch46_by_oid.get(oid),
    })

print(f"Type='{target_type}' | {len(filtered)} questions (subset Robust × gold)\n")

for i, item in enumerate(filtered, 1):
    g = item["gold"]
    s48 = item["ch48"]
    s46 = item["ch46"]
    sm48 = s48.get("structured_metrics") or {}
    sm46 = (s46.get("structured_metrics") or {}) if s46 else {}
    ev48 = s48.get("evaluation") or {}
    gt = g.get("ground_truth") or {}

    print("=" * 95)
    print(f"[{i}/{len(filtered)}] {item['oid']}")
    print(f"Q: {g.get('question','')}")
    print(f"\nGOLD reference answer:")
    ref = gt.get("answer", "") or ""
    print(f"  {ref[:400]}{'...' if len(ref) > 400 else ''}")
    if gt.get("exact_identifiers"):
        print(f"\nGOLD exact_identifiers: {gt.get('exact_identifiers')}")
    if gt.get("supporting_doc_ids"):
        print(f"GOLD supporting_doc_ids: {gt.get('supporting_doc_ids')}")
    if gt.get("answerability"):
        print(f"GOLD answerability: {gt.get('answerability')}")
    if gt.get("false_premise"):
        print(f"GOLD false_premise: {gt.get('false_premise')}")

    print(f"\n--- CH-48 ANSWER ---")
    print(f"{(s48.get('answer') or '')[:500]}")
    print(f"\nstructured_metrics CH-48:")
    print(f"  item_recall={sm48.get('item_recall')}")
    print(f"  exact_match={sm48.get('exact_match')}")
    print(f"  citation={sm48.get('citation')}")
    print(f"  coverage={sm48.get('coverage')}")
    print(f"  structured_avg={sm48.get('structured_avg')} applicable={sm48.get('applicable')}")
    print(f"judge CH-48: score={ev48.get('score')} | reason={(ev48.get('judge_reason') or '')[:200]}")

    if s46:
        print(f"\n--- CH-46 ANSWER (Qwen-72B) ---")
        print(f"{(s46.get('answer') or '')[:500]}")
        print(f"structured_avg CH-46: {sm46.get('structured_avg')} judge={(s46.get('evaluation') or {}).get('score')}")
    print()
