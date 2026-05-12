"""Re-test des 5 questions temporal via l'API POC (avec fallbacks Qdrant + list_all)."""
import json
import time
from pathlib import Path
import requests

API = "http://knowbase-app:8000/api/runtime_v4_poc/answer"
GOLD = json.loads(Path("/app/benchmark/questions/gold_set_v5.json").read_text(encoding="utf-8"))
gv5_by_sid = {q["source_id"]: q for q in GOLD}

# Les 5 questions temporal du bench POC
QIDS = ["T7_AERO_0001", "T7_AERO_0032", "T7_AERO_0031", "T6_AERO_TMP_005", "T7_AERO_0041"]

for qid in QIDS:
    g = gv5_by_sid[qid]
    q = g["question"]
    print(f"\n=== {qid} ===")
    print(f"Q: {q[:160]}")
    print(f"GOLD: {(g['ground_truth'].get('answer') or '')[:200]}")

    t0 = time.time()
    r = requests.post(API, json={"question": q, "top_k_claims": 12}, timeout=120)
    wall = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}")
        continue
    d = r.json()
    print(f"  layer={d['layer']} decision={d['decision']} wall={wall}ms")
    print(f"  breakdown: {d.get('latency_breakdown_ms')}")
    print(f"  answer: {(d.get('answer') or '')[:300]}")
    if d.get("abstention_reason"):
        print(f"  abstain_reason: {d['abstention_reason']}")
