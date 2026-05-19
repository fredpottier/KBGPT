"""Bench V5.1 sur mini gold-set reference-heavy (10q) pour mesurer V6-J2 (find_references).

Réutilise les fonctions submit/poll de bench_v51_50q_stratified, sans stratification :
prend les questions du fichier en ordre.

Usage :
    python scripts/bench_v51_reference_mini.py --tag ref_mini_ds31
    python scripts/bench_v51_reference_mini.py --tag ref_mini_qwen72 \\
        --model Qwen/Qwen2.5-72B-Instruct
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from bench_v51_50q_stratified import submit, poll, has_phantom, has_citation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--panel", default="benchmark/questions/gold_set_reference_mini.json")
    parser.add_argument("--questions-per-tenant", type=int, default=5)
    parser.add_argument("--sleep-between-q", type=int, default=2)
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.add_argument("--tag", default="ref_mini")
    parser.add_argument("--model", default="",
                        help="LLM override (ex: Qwen/Qwen2.5-72B-Instruct)")
    args = parser.parse_args()

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    panel_path = root / args.panel
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    selected = panel.get("questions") if isinstance(panel, dict) else panel

    print(f"=== Bench V5.1 reference-heavy mini ({args.tag}) ===")
    print(f"Questions: {len(selected)}")
    print(f"Model: {args.model or 'V5_LLM_MODEL default'}\n")

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / f"benchmark/runs/v51_bench_refmini_{args.tag}_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        r = requests.get(f"{args.url}/docs", timeout=30)
        print(f"Health: HTTP {r.status_code}\n")
    except Exception as e:
        print(f"Health WARN: {e}\n")

    results = []
    t_global = time.time()
    for i, q in enumerate(selected):
        qid = q.get("id", f"q_{i}")
        ptype = q.get("primary_type", "factual")
        question = q.get("question", "")
        gt = q.get("ground_truth", {})
        if isinstance(gt, dict):
            gt_answer = gt.get("answer") or gt.get("text") or ""
        else:
            gt_answer = str(gt)
        tenant = f"refmini_{args.tag}_t{i // args.questions_per_tenant}"
        idemp = f"refmini_{args.tag}_{ts}_{qid}_{tenant}"

        elapsed = time.time() - t_global
        print(f"\n[{i+1}/{len(selected)}] {qid} [{ptype}] t+{elapsed:.0f}s")
        print(f"  Q: {question[:120]}...")

        t_q = time.time()
        sub = submit(args.url, tenant, question, ptype, idemp,
                     llm_model=args.model or None)
        if "_error" in sub:
            print(f"  ❌ submit: {sub['_error'][:150]}")
            results.append({**q, "qid": qid, "primary_type": ptype,
                            "question": question[:300], "ground_truth": gt_answer[:500],
                            "error": sub["_error"], "phase": "submit"})
            time.sleep(args.sleep_between_q)
            continue
        rid = sub["request_id"]
        body = poll(args.url, tenant, rid, timeout_s=args.timeout_s)
        total_lat = time.time() - t_q

        if "_error" in body:
            print(f"  ❌ poll: {body['_error']}")
            results.append({**q, "qid": qid, "primary_type": ptype,
                            "question": question[:300], "ground_truth": gt_answer[:500],
                            "error": body["_error"], "phase": "poll",
                            "total_latency_s": total_lat})
            time.sleep(args.sleep_between_q)
            continue

        result = body.get("result") or {}
        answer = result.get("answer") or ""
        citations = result.get("citations", [])
        metrics = result.get("metrics", {})
        epi = result.get("epistemic_status", "?")
        sr = result.get("stop_reason", "")
        verifier_report = result.get("verifier_report")
        phantom = has_phantom(answer)
        cited = has_citation(answer)
        v_outcome = (verifier_report or {}).get("outcome", "n/a")
        v_supp = (verifier_report or {}).get("support_rate", 0.0)

        # Compte invocations find_references / find_procedures via heuristique answer
        # (les vraies tool_calls ne sont pas dans le bench JSON — vérifier dans logs app)
        print(f"  → {body.get('status')} | {epi} | {total_lat:.1f}s | "
              f"{metrics.get('n_iterations','?')}it | "
              f"{metrics.get('n_tool_calls','?')}tc | "
              f"{len(citations)}cit | "
              f"v={v_outcome}({v_supp:.2f}) | "
              f"{'PHANTOM' if phantom else ''}{'CITED' if cited else ''}")

        # Quick exact_match check on identifiers
        ids = (q.get("ground_truth", {}) or {}).get("exact_identifiers", [])
        ans_lc = answer.lower()
        matched_ids = [x for x in ids if x.lower() in ans_lc]
        print(f"  Identifiers matched: {len(matched_ids)}/{len(ids)} ({', '.join(matched_ids[:5])})")

        results.append({
            "qid": qid, "primary_type": ptype,
            "question": question[:300], "ground_truth": gt_answer[:500],
            "request_id": rid, "status": body.get("status"),
            "epistemic_status": epi, "stop_reason": sr,
            "answer": answer[:3000], "answer_chars": len(answer),
            "citations": citations, "n_citations": len(citations),
            "phantom_tool_call": phantom, "has_citation": cited,
            "metrics": metrics, "total_latency_s": total_lat,
            "verifier_report": verifier_report,
            "exact_match_count": len(matched_ids),
            "exact_match_total": len(ids),
            "exact_match_rate": (len(matched_ids) / max(len(ids), 1)),
        })

        output_path.write_text(json.dumps({
            "_meta": {"ts": ts, "tag": args.tag, "n_done": i + 1,
                      "n_total": len(selected), "model": args.model or "default"},
            "results": results,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        time.sleep(args.sleep_between_q)

    completed = [r for r in results if r.get("status") == "completed"]
    print(f"\n{'=' * 60}\nREF MINI SUMMARY ({args.tag})\n{'=' * 60}")
    print(f"Completed: {len(completed)}/{len(results)}")
    if completed:
        lats = [r["metrics"].get("latency_s", r["total_latency_s"]) for r in completed]
        iters = [r["metrics"].get("n_iterations", 0) for r in completed]
        n_phantom = sum(1 for r in completed if r["phantom_tool_call"])
        n_cited = sum(1 for r in completed if r["has_citation"])
        em_rates = [r.get("exact_match_rate", 0) for r in completed]
        print(f"Latence avg: {statistics.mean(lats):.1f}s")
        print(f"Iter avg: {statistics.mean(iters):.1f}")
        print(f"Phantom: {n_phantom}/{len(completed)}")
        print(f"Citation: {n_cited}/{len(completed)} ({100*n_cited/len(completed):.0f}%)")
        print(f"Exact-match rate avg: {statistics.mean(em_rates):.2f}")
        # Strong/weak breakdown
        n_strong = sum(1 for r in completed if r.get("exact_match_rate", 0) >= 0.8)
        n_weak = sum(1 for r in completed if r.get("exact_match_rate", 0) < 0.3)
        print(f"Strong matches (≥0.8): {n_strong}/{len(completed)}")
        print(f"Weak matches (<0.3): {n_weak}/{len(completed)}")

    print(f"\nWrote: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
