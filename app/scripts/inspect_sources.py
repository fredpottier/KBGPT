"""Inspecte la disponibilité des sources_used dans V3 et V4.2."""
import json

V3 = "/app/data/benchmark/results/robustness_run_20260505_104355_V3_FINAL3.json"
V42 = "/app/data/benchmark/results/robustness_run_20260510_145658_v4_2_baseline.json"

for label, path in [("V3", V3), ("V4.2", V42)]:
    d = json.load(open(path))
    samples = d["per_sample"]
    nonempty = [s for s in samples if s.get("sources_used")]
    print(f"\n=== {label} ===")
    print(f"Samples avec sources_used non-vide: {len(nonempty)}/{len(samples)}")
    for s in nonempty[:3]:
        qid = s["question_id"]
        su = s["sources_used"]
        print(f"\n  qid={qid} | sources_used={len(su)} items")
        if isinstance(su, list) and su:
            first = su[0]
            print(f"  sample[0] type={type(first).__name__}")
            if isinstance(first, dict):
                print(f"  sample[0] keys: {list(first.keys())}")
                # Peek text content
                for k in ("text", "content", "chunk", "snippet"):
                    if k in first:
                        v = first[k]
                        print(f"  sample[0].{k}: {str(v)[:200]}...")
                        break
            else:
                print(f"  sample[0]: {str(first)[:200]}")
