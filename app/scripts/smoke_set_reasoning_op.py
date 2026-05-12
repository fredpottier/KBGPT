"""Smoke test Cap2.D set_reasoning_op."""
import time
import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"

QUESTIONS = [
    # Should trigger
    "What items are NOT subject to the export authorization requirement?",
    "Quelles sont les exemptions au règlement applicable aux exportations ?",
    "What is excluded from the scope of the dual-use regulation?",
    # Should NOT trigger (positive list)
    "List the items in Annex I",
    # Should NOT trigger (factual)
    "What is the maximum cabin altitude?",
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
        ans = (d.get('answer') or '')[:400]
        print(f"  answer: {ans}")
        if d.get('abstention_reason'):
            print(f"  abstain_reason: {d['abstention_reason']}")
    except Exception as exc:
        print(f"  exc: {exc}")
