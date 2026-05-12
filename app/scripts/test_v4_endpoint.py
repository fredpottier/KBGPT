"""Smoke test endpoint V4."""
import json
import sys
import time

import requests

API = "http://knowbase-app:8000/api/runtime_v4/answer"

questions = [
    "Quel règlement remplace le 428/2009 sur les biens à double usage ?",
    "Liste les autorités compétentes pour délivrer une autorisation d'export.",
    "Pourquoi le RGPD impose-t-il un DPO pour certaines organisations ?",
]

for q in questions:
    print(f"\n=== Q: {q} ===")
    t0 = time.time()
    resp = requests.post(API, json={"question": q, "top_k_claims": 15}, timeout=240)
    elapsed = time.time() - t0
    if resp.status_code != 200:
        print(f"FAIL HTTP {resp.status_code}: {resp.text[:300]}")
        continue
    data = resp.json()
    print(f"  primary_type     : {data.get('primary_type')}")
    print(f"  routing_decision : {data.get('routing_decision')}")
    print(f"  decision         : {data.get('decision')}")
    print(f"  rerouter_promoted: {data.get('rerouter_promoted')}")
    print(f"  faithfulness     : {data.get('faithfulness_score')} ({data.get('faithfulness_verdict')})")
    print(f"  doc_ids ({len(data.get('doc_ids_cited', []))}) : {data.get('doc_ids_cited', [])[:3]}")
    print(f"  chunks_used      : {len(data.get('chunks_used', []))}")
    print(f"  answer (first 200): {(data.get('answer') or '')[:200]}")
    print(f"  elapsed wall     : {elapsed:.1f}s")

print("\n✅ Smoke test V4 done")
