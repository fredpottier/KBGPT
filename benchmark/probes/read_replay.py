import json
import sys

d = json.load(open("/app/data/benchmark/results/replay_regressed_20260408_155145.json"))
idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0

r = d["results"][idx]
print("=" * 80)
print(f"QID: {r['question_id']} ({r['category']})  PRE={r.get('pre_score','?')} -> B9={r.get('b9_score','?')}")
print(f"Question: {r.get('question','')}")
print()
print(f"Sources (replay): {r.get('replay_sources', [])}")
print(f"Chunks count: {r.get('replay_chunks_count')}")
print()
print("=== REPONSE COMPLETE (replay B9) ===")
print(r.get("replay_answer", ""))
print()
print("=" * 80)
print("=== PRE answer (tronquee 500) ===")
print(r.get("pre_answer", ""))
