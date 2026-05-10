"""Smoke test Cap2.E comparison_contradiction_op."""
import time
import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"

QUESTIONS = [
    # Should trigger
    "Compare l'Annex I du règlement 2021/821 avec le délégué 2023/996 sur la liste des produits contrôlés",
    "Are CS-25 Amendment 26 and Amendment 28 aligned regarding impact energy requirements?",
    "Y a-t-il une contradiction entre le règlement 2021/821 et le délégué 2024/2547 sur l'Annex I ?",
    # Should NOT trigger (factual)
    "What is the maximum altitude limit?",
    # Should NOT trigger (causal)
    "Why was Regulation 428/2009 repealed?",
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
    except Exception as exc:
        print(f"  exc: {exc}")
