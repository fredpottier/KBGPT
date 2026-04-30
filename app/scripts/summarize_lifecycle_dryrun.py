#!/usr/bin/env python3
"""Helper : résume le dernier forensics dry-run lifecycle."""
import glob
import json
import os

paths = sorted(glob.glob("/data/forensics/lifecycle_backfill_v2s1_*.json"), key=os.path.getmtime, reverse=True)
if not paths:
    print("No forensics file found")
    raise SystemExit(1)

with open(paths[0]) as f:
    d = json.load(f)

print(f"=== {os.path.basename(paths[0])} ===")
print(f"  vllm: {d['metadata']['vllm_url']}, model: {d['metadata']['model_id']}, dry_run={d['metadata']['dry_run']}, n_docs={d['metadata']['n_docs']}\n")

acc_total = 0
rej_total = 0
for r in d["results"]:
    n_acc = r.get("n_accepted", 0)
    n_rej = r.get("n_rejected", 0)
    if n_acc == 0 and n_rej == 0:
        continue
    print(f"  {r['doc_id']}: accepted={n_acc}, rejected={n_rej}")
    for a in r.get("accepted", []):
        print(f"    ✓ -> {a['target_doc_id']} [{a['type']}] conf={a['confidence']:.2f}")
        print(f"       quote: {a['evidence_quote'][:140]}")
    for rj in r.get("rejected", []):
        cand = rj["candidate"]
        print(f"    ✗ -> {cand['target_doc_reference']} [{cand['type']}] {rj['outcome']}")
        print(f"       quote: {cand['evidence_quote'][:140]}")
    acc_total += n_acc
    rej_total += n_rej

print(f"\nTotal: accepted={acc_total}, rejected={rej_total}")
