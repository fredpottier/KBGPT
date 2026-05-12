"""Smoke test Layer 2 orchestrator (Cap3) — 3 questions complexes."""
import time
import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"

QUESTIONS = [
    # causal_why
    "Pourquoi le règlement (UE) 2021/821 a-t-il abrogé le règlement 428/2009 ?",
    # multi_hop
    "Si un nouveau règlement amende l'Annex I de 2021/821, quel est l'impact sur les autorisations d'export en cours ?",
    # hypothetical
    "Si une compagnie aérienne souhaitait certifier un nouvel aéronef en 2024, quelle version de CS-25 devrait-elle suivre et pourquoi ?",
]

for q in QUESTIONS:
    print(f"\n=== Q: {q} ===")
    t0 = time.time()
    try:
        r = requests.post(API, json={"question": q, "top_k_claims": 12}, timeout=120)
        wall = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            continue
        d = r.json()
        print(f"  layer={d['layer']} decision={d['decision']} wall={wall}ms")
        ans = (d.get('answer') or '')[:500]
        print(f"  answer: {ans}")
        if d.get('abstention_reason'):
            print(f"  abstain_reason: {d['abstention_reason']}")
        bd = d.get('latency_breakdown_ms', {})
        if 'layer2_ms' in bd:
            print(f"  layer2_ms: {bd['layer2_ms']}")
    except Exception as exc:
        print(f"  exc: {exc}")
