"""CH-49 — Analyse détaillée des 12 questions multi_hop sur Robust × gold v5."""
import json
from pathlib import Path

GOLD = json.loads(Path("/app/benchmark/questions/gold_set_v5.json").read_text(encoding="utf-8"))
gv5_by_sid = {q["source_id"]: q for q in GOLD}

CH48 = json.loads(Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json").read_text(encoding="utf-8"))
ch46_paths = [
    Path("/app/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
    Path("/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
]
CH46 = json.loads(next(p for p in ch46_paths if p.exists()).read_text(encoding="utf-8"))
ch46_by_oid = {s.get("original_id"): s for s in CH46["per_sample"]}

# Charge le post-score
POST = json.loads(Path("/app/data/audit/ch49_post_score_v5_robust.json").read_text(encoding="utf-8"))
post_by_oid = {r["original_id"]: r for r in POST["CH-48"]}

# Filtre primary_type=multi_hop
mh = []
for s in CH48["per_sample"]:
    oid = s.get("original_id")
    if not oid or oid not in gv5_by_sid:
        continue
    if gv5_by_sid[oid]["primary_type"] != "multi_hop":
        continue
    mh.append({
        "oid": oid,
        "gold": gv5_by_sid[oid],
        "ch48": s,
        "ch46": ch46_by_oid.get(oid),
        "post": post_by_oid.get(oid),
    })

print(f"Multi_hop questions Robust × gold v5 : {len(mh)}\n")

for i, item in enumerate(mh, 1):
    g = item["gold"]
    s48 = item["ch48"]
    s46 = item["ch46"]
    gt = g["ground_truth"]
    post = item["post"]

    print("=" * 95)
    print(f"[{i}/{len(mh)}] {item['oid']} (source_task={g['source_task']}, source_cat={g['source_category']})")
    print(f"primary_type={g['primary_type']} flags={g['flags']}")
    print(f"Q: {g['question'][:200]}")
    print(f"\nGOLD answer (reference):")
    print(f"  {(gt.get('answer') or '')[:300]}")
    if gt.get("exact_identifiers"):
        print(f"GOLD exact_identifiers: {gt['exact_identifiers']}")
    print(f"GOLD supporting_doc_ids: {gt.get('supporting_doc_ids', [])}")
    if gt.get("chain"):
        print(f"GOLD chain ({len(gt['chain'])} steps): " + " → ".join(c.get('text', '')[:50] for c in gt['chain'][:3]))

    print(f"\n--- CH-48 ANSWER ---")
    print(f"{(s48.get('answer') or '')[:400]}")
    if post:
        sc = post["scored"]
        print(f"\nstructured_avg CH-48: {sc['structured_avg']:.3f}")
        print(f"  exact_match: {sc.get('exact_match', {})}")
        print(f"  citation: {sc.get('citation', {})}")
        if sc.get("item_recall", {}).get("applicable"):
            print(f"  item_recall: {sc['item_recall']}")
    print(f"judge CH-48: {(s48.get('evaluation') or {}).get('score')}")

    if s46:
        print(f"\n--- CH-46 ANSWER ---")
        print(f"{(s46.get('answer') or '')[:300]}")
        print(f"judge CH-46: {(s46.get('evaluation') or {}).get('score')}")
    print()
