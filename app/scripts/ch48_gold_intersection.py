"""Identifie les questions du bench Robust qui sont dans gold_set_v4 (avec reference)."""
import json
from pathlib import Path

GOLD_PATH = Path("/app/benchmark/questions/gold_set_v4.json")

# Pas claire si le bench Robust ID matche les gold IDs. Inspectons.
gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
print(f"Gold-set v4 : {len(gold)} questions")
print(f"Gold[0] keys : {list(gold[0].keys())}")
print(f"Gold[0] id : {gold[0].get('id')} | source_id : {gold[0].get('source_id')}")

# Inventaire IDs gold
gold_ids = {q['id']: q for q in gold}
gold_source_ids = {q.get('source_id'): q for q in gold if q.get('source_id')}

# Robust CH-48
robust_paths = [
    Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
    Path("/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
]
ch48_path = next((p for p in robust_paths if p.exists()), None)
if not ch48_path:
    print("Robust CH-48 introuvable")
    raise SystemExit(1)

ch48 = json.loads(ch48_path.read_text(encoding="utf-8"))
samples = ch48.get("per_sample", [])
print(f"\nCH-48 Robust : {len(samples)} samples")
print(f"Sample[0] keys : {list(samples[0].keys())[:15]}")
print(f"Sample[0] : qid={samples[0].get('question_id')} orig_id={samples[0].get('original_id')}")

# Intersection
in_gold_by_id = sum(1 for s in samples if s.get('question_id') in gold_ids)
in_gold_by_orig = sum(1 for s in samples if s.get('original_id') in gold_ids or s.get('original_id') in gold_source_ids)
in_gold_by_qsrc = sum(1 for s in samples if s.get('question_id') in gold_source_ids)
print(f"\nIntersection :")
print(f"  question_id in gold.id : {in_gold_by_id}/{len(samples)}")
print(f"  original_id in gold (id ou source_id) : {in_gold_by_orig}/{len(samples)}")
print(f"  question_id in gold.source_id : {in_gold_by_qsrc}/{len(samples)}")

# Vérification d'un match concret
print(f"\nGold IDs sample : {list(gold_ids.keys())[:5]}")
print(f"Gold source_ids sample : {list(gold_source_ids.keys())[:5]}")
print(f"\nRobust qid sample : {[s.get('question_id') for s in samples[:5]]}")
print(f"Robust original_id sample : {[s.get('original_id') for s in samples[:5]]}")

# Sample structure analysis
ev0 = samples[0].get('evaluation') or {}
print(f"\nSample[0] evaluation keys : {list(ev0.keys())[:10]}")
sm0 = samples[0].get('structured_metrics') or {}
print(f"Sample[0] structured_metrics : {list(sm0.keys())[:10]}")
gt0 = samples[0].get('ground_truth')
print(f"Sample[0] has ground_truth : {gt0 is not None}")
