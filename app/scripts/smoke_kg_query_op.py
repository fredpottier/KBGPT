"""Smoke tests Cap2.C kg_query_op — 3 query types (CHAIN, LIST_BY_STATUS, COUNT)."""
import time
import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"

QUESTIONS = [
    # COUNT
    "How many documents are deprecated in the corpus?",
    "Combien de relations SUPERSEDES existent dans le graphe ?",
    # LIST_BY_STATUS
    "List all active documents",
    "Quels sont les documents actuellement en vigueur ?",
    # CHAIN
    "Show the supersession chain of regulation 428/2009",
    "Quelle est la lignée d'évolution du règlement 2021/821 ?",
    # Non-applicable (doit passer en Layer 0)
    "What is the maximum altitude for commercial flights?",
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
        ans = (d.get('answer') or '')[:300]
        print(f"  answer: {ans}")
        if d.get('abstention_reason'):
            print(f"  abstain_reason: {d['abstention_reason']}")
    except Exception as exc:
        print(f"  exc: {exc}")
