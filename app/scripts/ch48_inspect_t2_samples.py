"""Inspect T2 samples du bench CH-48 pour comprendre les fails citation multi-source."""
import json
from pathlib import Path
import re

p = Path("/data/benchmark/results/t2t5_run_20260509_162259_V4_CH48_LLAMA_TURBO_TOGETHER.json")
d = json.loads(p.read_text(encoding="utf-8"))
samples = d.get("per_sample") or []
print(f"Total samples: {len(samples)}")

# Inspect first sample structure
print("Keys sample[0]:", list(samples[0].keys()))
print("Sample[0] question_id/category/dataset:", samples[0].get("question_id"), samples[0].get("category"), samples[0].get("dataset"))
print()

# Filtre par taxonomy : T2 = contradictions, regarder dataset/category
t2_samples = [s for s in samples if (s.get("task_name") or "").lower().startswith("t2")]
t5_samples = [s for s in samples if (s.get("task_name") or "").lower().startswith("t5")]
print(f"T2 samples: {len(t2_samples)} | T5 samples: {len(t5_samples)}")
print(f"task_names sample: {[s.get('task_name') for s in samples[:5]]}\n")

# Affiche 3 samples avec scores faibles ou N/A sur both_sides_surfaced
print("=== 3 SAMPLES T2 ===\n")
for s in t2_samples[:3]:
    qid = s.get("question_id", "?")
    q = s.get("question", "")
    a = s.get("answer", "")
    eval_ = s.get("evaluation") or {}
    print(f"--- {qid} ---")
    print(f"Q: {q[:200]}")
    print(f"A: {a[:600]}")
    # Compte les [doc=...] dans la réponse
    docs = re.findall(r"\[doc=([^\]]+)\]", a)
    unique_docs = sorted(set(docs))
    print(f"Citations [doc=...] : {len(docs)} occurrences, {len(unique_docs)} unique → {unique_docs}")
    sources = s.get("sources_used") or []
    print(f"sources_used: {len(sources)} sources")
    if eval_:
        print(f"evaluation keys: {list(eval_.keys())[:8]}")
        for k in ("both_sides_surfaced", "tension_mentioned", "both_sources_cited", "judge_score"):
            if k in eval_:
                print(f"  {k}: {eval_[k]}")
    print()
