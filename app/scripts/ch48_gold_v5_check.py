"""Vérifie couverture gold v5 sur les benchs + sample qualité."""
import json
from pathlib import Path

GOLD_V5 = json.loads(Path("/app/benchmark/questions/gold_set_v5.json").read_text(encoding="utf-8"))
gv5_by_sid = {q["source_id"]: q for q in GOLD_V5}

# Robust
RB = json.loads(Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json").read_text(encoding="utf-8"))
rb = RB["per_sample"]

# T2T5
T2 = json.loads(Path("/data/benchmark/results/t2t5_run_20260509_162259_V4_CH48_LLAMA_TURBO_TOGETHER.json").read_text(encoding="utf-8"))
t2 = T2["per_sample"]

# Couverture Robust
rb_covered = sum(1 for s in rb if s.get("original_id") in gv5_by_sid)
print(f"Robust 170q × gold_v5 : {rb_covered}/{len(rb)} couverts ({100*rb_covered/len(rb):.0f}%)")

# Couverture T2T5 (note: question_id est qid alphanumérique q_0/q_1 pas T2_AERO_xxx)
# Il faut peut-être chercher un autre champ pour matcher
print(f"\nT2T5 sample[0] keys: {list(t2[0].keys())[:10]}")
print(f"T2T5 sample[0] q_id: {t2[0].get('question_id')} task: {t2[0].get('task_name')}")

# Vérifier aussi : est-ce que T2 dans gold_v5 a bien des source_id type T2_AERO_xxxx ?
t2_in_gold = [q for q in GOLD_V5 if q["source_task"] == "T2_contradictions"]
print(f"\nGold v5 T2 entries : {len(t2_in_gold)}")
print(f"  source_id sample : {[q['source_id'] for q in t2_in_gold[:3]]}")

# Sample qualité — 3 échantillons par task
print("\n" + "=" * 90)
print("ÉCHANTILLONS DE QUALITÉ")
print("=" * 90)

samples_to_show = []
for task in ["T6_robustness", "T7_v2_anchor", "T2_contradictions"]:
    matching = [q for q in GOLD_V5 if q["source_task"] == task][:1]
    samples_to_show.extend(matching)

for s in samples_to_show:
    print(f"\n--- {s['id']} ({s['source_task']} / {s['source_category']}) ---")
    print(f"Question: {s['question'][:160]}")
    print(f"primary_type: {s['primary_type']} | secondary: {s['secondary_types']} | flags: {s['flags']}")
    gt = s["ground_truth"]
    print(f"answer: {(gt.get('answer') or '')[:200]}")
    print(f"exact_identifiers: {gt.get('exact_identifiers')}")
    print(f"supporting_doc_ids: {gt.get('supporting_doc_ids')}")
    print(f"answerability: {gt.get('answerability')}")
