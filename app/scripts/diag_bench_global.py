"""Diag temporaire — investigue le rate d'abstention et structurer_rejected."""
import json
from collections import Counter
d = json.load(open('/app/data/benchmark/calibration/bench_global_v4.json'))
samples = d['per_sample']
abst = sum(1 for r in samples if r.get('answer_text', '').startswith(('The answer', 'La réponse')))
print(f"Abstentions: {abst}/{len(samples)}")
print(f"Routing decisions: {Counter(r.get('routing_decision') for r in samples)}")
print(f"Verifier passed: {Counter(r.get('verifier_passed') for r in samples)}")
print(f"Structurer rejected count distribution:",
      Counter(r.get('structurer_rejected_count') for r in samples))

non_abst = [r for r in samples if not r.get('answer_text', '').startswith(('The answer', 'La réponse'))]
print(f"\n=== Non-abstention samples: {len(non_abst)} ===")
for r in non_abst[:5]:
    print(f"-- {r['id']} | type={r.get('expected_type')} | route={r.get('routing_decision')} | rejected={r.get('structurer_rejected_count')}")
    print(f"   answer: {r.get('answer_text', '')[:180]}")
