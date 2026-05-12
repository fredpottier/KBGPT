"""CH-48 — Inspecte les ABSTAINs du bench micro stratifié."""
import json

results = json.loads(open("/app/data/audit/ch48_stratified_llama_turbo.json").read())
abstains = [r for r in results if r.get("decision") == "ABSTAIN"]
print(f"== {len(abstains)} ABSTAIN ==\n")
for r in abstains:
    print(f"{r['id']:38s} type={r.get('primary_type','?'):10s} routing={r.get('routing','')}")
    print(f"  Q: {(r.get('question') or '')[:160]}")
    print(f"  A: {(r.get('answer') or '')[:200]}")
    print(f"  atomic={len(r.get('atomic_facts') or [])} rel={len(r.get('relational_facts') or [])} primary_type={r.get('primary_type')}")
    print()
