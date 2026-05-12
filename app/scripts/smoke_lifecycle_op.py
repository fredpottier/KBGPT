"""Smoke tests Cap2.B lifecycle_resolution_op — direct via Python (évite encodage JSON Bash)."""
import json
import time
import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"

QUESTIONS = [
    "Quel règlement a remplacé le règlement (CE) n° 428/2009 ?",
    "What document supersedes Regulation (EC) No 428/2009?",
    "Que remplace le règlement 2021/821 ?",
    "Which delegated regulation amends Annex I of Regulation 2021/821?",
    "List the items in Annex I",  # devrait être NOT_APPLICABLE → Layer 0
]

for q in QUESTIONS:
    print(f"\n=== Q: {q} ===")
    t0 = time.time()
    r = requests.post(API, json={"question": q, "top_k_claims": 12}, timeout=120)
    wall = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {r.text[:200]}")
        continue
    d = r.json()
    print(f"  layer={d['layer']} decision={d['decision']} wall={wall}ms")
    print(f"  answer: {(d.get('answer') or '')[:300]}")
    if d.get('abstention_reason'):
        print(f"  abstain_reason: {d['abstention_reason']}")
    print(f"  breakdown: {d.get('latency_breakdown_ms')}")
