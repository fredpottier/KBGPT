"""Compte précisément les questions sans reference gold à construire."""
import json
from collections import defaultdict
from pathlib import Path

GOLD = json.loads(Path("/app/benchmark/questions/gold_set_v4.json").read_text(encoding="utf-8"))
gold_source_ids = {q.get("source_id") for q in GOLD if q.get("source_id")}

# Robust 170q
RB_PATHS = [
    Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
]
RB = json.loads(next(p for p in RB_PATHS if p.exists()).read_text(encoding="utf-8"))
rb_samples = RB["per_sample"]

# T2T5
T2_PATHS = [
    Path("/data/benchmark/results/t2t5_run_20260509_162259_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
    Path("/app/data/benchmark/results/t2t5_run_20260509_162259_V4_CH48_LLAMA_TURBO_TOGETHER.json"),
]
T2 = json.loads(next(p for p in T2_PATHS if p.exists()).read_text(encoding="utf-8"))
t2_samples = T2["per_sample"]

print(f"Gold v4 total : {len(GOLD)} questions ({len(gold_source_ids)} avec source_id utilisable)\n")

# Robust : combien sans gold ?
rb_with = sum(1 for s in rb_samples if s.get("original_id") in gold_source_ids)
rb_without = len(rb_samples) - rb_with
print(f"Robust 170q :")
print(f"  Avec gold reference : {rb_with}")
print(f"  Sans gold reference : {rb_without}")

# Distribution Robust sans gold par catégorie
rb_missing_by_cat = defaultdict(list)
for s in rb_samples:
    if s.get("original_id") not in gold_source_ids:
        cat = s.get("category") or "?"
        rb_missing_by_cat[cat].append(s.get("original_id"))

print(f"\n  Distribution Robust SANS gold par catégorie:")
for cat, oids in sorted(rb_missing_by_cat.items()):
    print(f"    {cat:35s} : {len(oids):3d} | examples: {oids[:3]}")

# T2T5 : pas dans gold normalement
t2_with = sum(1 for s in t2_samples if (s.get("question_id") or "") in gold_source_ids)
print(f"\nT2T5 70q :")
print(f"  Avec gold reference : {t2_with}")
print(f"  Sans gold reference : {len(t2_samples) - t2_with}")

t2_by_task = defaultdict(int)
for s in t2_samples:
    t = s.get("task_name", "?")
    t2_by_task[t] += 1
print(f"  Distribution T2T5 par task:")
for t, n in sorted(t2_by_task.items()):
    print(f"    {t:35s} : {n:3d}")

# RAGAS gold_v4 - checking
print(f"\nGold-set v4 distribution par primary_type :")
type_count = defaultdict(int)
for q in GOLD:
    type_count[q.get("primary_type", "?")] += 1
for t, n in sorted(type_count.items(), key=lambda x: -x[1]):
    print(f"  {t:25s} : {n:3d}")

print(f"\n=== TOTAL questions sans gold reference (à construire pour CH-50) ===")
total_missing = rb_without + (len(t2_samples) - t2_with)
print(f"  Robust sans gold : {rb_without}")
print(f"  T2T5 sans gold   : {len(t2_samples) - t2_with}")
print(f"  TOTAL            : {total_missing}")
