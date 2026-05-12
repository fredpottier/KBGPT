#!/usr/bin/env python3
"""Bench mini V2 sur 5 questions aerospace, avec encoding UTF-8 explicite."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

QUESTIONS_PATH = Path('/app/benchmark/questions/v2_aerospace_compliance_mini.json')
OUT_DIR = Path('/data/forensics/runs')
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    questions = json.loads(QUESTIONS_PATH.read_text(encoding='utf-8'))
    results = []
    for q in questions:
        print(f"\n=== {q['id']} ({q['category']}) ===", flush=True)
        print(f"Q: {q['question']}", flush=True)
        start = time.time()
        try:
            r = requests.post(
                'http://localhost:8000/api/runtime_v2/answer',
                json={'question': q['question'], 'top_k_claims': 5},
                timeout=120,
            )
            r.raise_for_status()
            d = r.json()
            latency = time.time() - start
            decision = d.get('decision')
            anchor_type = (d.get('anchor') or {}).get('anchor_type')
            docs = d.get('authoritative_doc_ids') or []
            ans = d.get('synthesized_answer') or ''
            gt_doc = q.get('ground_truth_doc_id')
            doc_match = (gt_doc in docs) if gt_doc else None
            trust = d.get('trust_score') or 0.0
            n_evo = len(d.get('evolution_points') or [])
            n_conf = len(d.get('conflicts') or [])
            print(f"  decision={decision} anchor={anchor_type} trust={trust:.2f} latency={latency:.1f}s")
            print(f"  docs={docs[:3]}")
            if gt_doc is not None:
                print(f"  GT doc match: {doc_match}")
            if n_evo:
                print(f"  evolution_points: {n_evo}")
            if n_conf:
                print(f"  conflicts: {n_conf}")
            print(f"  Answer: {ans[:300]}")
            results.append({
                'id': q['id'],
                'task': q['task'],
                'category': q['category'],
                'question': q['question'],
                'ground_truth_doc_id': gt_doc,
                'ground_truth_answer': q.get('ground_truth_answer'),
                'pipeline_v2': {
                    'decision': decision,
                    'anchor_type': anchor_type,
                    'authoritative_doc_ids': docs[:5],
                    'doc_match': doc_match,
                    'synthesized_answer': ans,
                    'trust_score': trust,
                    'n_evolution_points': n_evo,
                    'n_conflicts': n_conf,
                    'latency_s': round(latency, 2),
                },
            })
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            results.append({'id': q['id'], 'error': str(e)})

    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    out = OUT_DIR / f'v2_aero_mini_{ts}.json'
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n\nForensics: {out}")

    # Summary
    n_pass = sum(1 for r in results if r.get('pipeline_v2', {}).get('synthesized_answer') and (r.get('pipeline_v2', {}).get('doc_match') is not False))
    print(f"\n=== SUMMARY ===")
    print(f"  {n_pass}/{len(results)} questions traitées avec réponse + doc_match OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
