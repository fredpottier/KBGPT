"""Bench POC initial (reasoning_agent.run_agent) sur le même panel 50q
stratifié que V5.1 A3 (seed=42).

But : comparaison apples-to-apples POC vs V5.1 sur :
- Même corpus (38 docs SAP)
- Mêmes 50 questions (seed=42, stratifié 15 factual / 8 comparison / 8 multi_hop / ...)
- Même judge (Llama-3.3-70B via DeepInfra)
- Même endpoint LLM (Together AI DeepSeek-V3.1)

Diff post-scoring : isole les questions où POC réussit ET V5.1 échoue → traces brutes.

Sortie format compatible score_v51_bench_judge.py.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# POC initial (synchrone)
from knowbase.runtime_v5.reasoning_agent import run_agent


PHANTOM_PATTERN = re.compile(
    r"[｜|]tool[▁_]calls?[▁_](?:begin|sep|end)[｜|]|<tool[_-]call>",
    re.IGNORECASE,
)

STRATIFIED_QUOTA = {
    "factual": 15, "comparison": 8, "multi_hop": 8, "contextual": 3,
    "false_premise": 3, "causal": 3, "listing": 3, "negation": 3,
    "lifecycle": 2, "quantitative": 1, "unanswerable": 1,
}


def has_phantom(text): return bool(text) and bool(PHANTOM_PATTERN.search(text))
def has_citation(text): return bool(text) and bool(re.search(r"\[doc=[\w]+|\[Source\s+\d+", text))


def stratified_sample(qs, seed=42):
    rng = random.Random(seed)
    by_type = {}
    for q in qs:
        by_type.setdefault(q.get("primary_type", "?"), []).append(q)
    selected = []
    for ptype, quota in STRATIFIED_QUOTA.items():
        pool = by_type.get(ptype, [])
        if not pool:
            continue
        n = min(quota, len(pool))
        sample = rng.sample(pool, n)
        selected.extend(sample)
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", default="benchmark/questions/gold_set_sap_v2.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-iter", type=int, default=8, help="POC default")
    parser.add_argument("--tag", default="poc_same_panel")
    args = parser.parse_args()

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    panel_path = root / args.panel
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    qs_all = panel if isinstance(panel, list) else panel.get("questions", [])

    selected = stratified_sample(qs_all, seed=args.seed)
    print(f"=== Bench POC same-panel ({args.tag}) ===")
    print(f"Selected: {len(selected)} / {len(qs_all)} (seed={args.seed})")
    dist = Counter(q.get("primary_type") for q in selected)
    for k, v in sorted(dist.items()):
        print(f"  {k}: {v}")

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / f"benchmark/runs/v5_poc_bench_50q_{args.tag}_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    t_global = time.time()
    for i, q in enumerate(selected):
        qid = q.get("id", f"q_{i}")
        ptype = q.get("primary_type", "?")
        question = q.get("question", "")
        gt = q.get("ground_truth", {})
        if isinstance(gt, dict):
            gt = gt.get("answer") or gt.get("text") or ""

        elapsed = time.time() - t_global
        print(f"\n[{i+1}/{len(selected)}] {qid} [{ptype}] t+{elapsed:.0f}s")
        print(f"  Q: {question[:120]}...")

        t_q = time.time()
        try:
            poc_result = run_agent(
                question=question,
                max_iterations=args.max_iter,
                verbose=False,
            )
            error = None
        except Exception as e:
            poc_result = None
            error = f"{type(e).__name__}: {e}"

        total_lat = time.time() - t_q

        if error:
            print(f"  ❌ {error[:150]}")
            results.append({
                "qid": qid, "primary_type": ptype,
                "question": question[:300], "ground_truth": gt[:500],
                "error": error, "status": "failed",
                "total_latency_s": total_lat,
            })
            continue

        answer = poc_result.get("answer", "") or ""
        stop_reason = poc_result.get("stopped_reason", "?")
        n_iterations = poc_result.get("n_iterations", 0)
        n_tokens = poc_result.get("tokens_total", 0)
        trace = poc_result.get("trace", [])
        phantom = has_phantom(answer)
        cited = has_citation(answer)
        # Extract citations from answer
        citations_found = re.findall(r"\[doc=[\w_/-]+(?:[#/]\S*)?\]", answer)

        print(f"  → completed | {stop_reason} | {total_lat:.1f}s | "
              f"{n_iterations}it | {n_tokens}tok | "
              f"{len(citations_found)}cit | "
              f"{'PHANTOM' if phantom else ''}{'CITED' if cited else ''}")

        results.append({
            "qid": qid, "primary_type": ptype,
            "question": question[:300], "ground_truth": gt[:500],
            "status": "completed",
            "epistemic_status": "?",
            "stop_reason": stop_reason,
            "answer": answer[:3000], "answer_chars": len(answer),
            "citations": citations_found, "n_citations": len(citations_found),
            "phantom_tool_call": phantom, "has_citation": cited,
            "metrics": {
                "n_iterations": n_iterations,
                "n_tool_calls": len(trace),
                "latency_s": total_lat,
                "tokens_total": n_tokens,
            },
            "trace_summary": [
                {"iter": t.get("iter"), "tool": t.get("tool_call", {}).get("name"),
                 "args": t.get("tool_call", {}).get("args", {})}
                for t in trace[:30]
            ],
            "total_latency_s": total_lat,
        })

        # Save progressive
        output_path.write_text(json.dumps({
            "_meta": {"ts": ts, "tag": args.tag, "n_done": i + 1, "n_total": len(selected),
                      "seed": args.seed, "agent": "POC reasoning_agent.run_agent",
                      "max_iter": args.max_iter, "model": "DeepSeek-V3.1"},
            "results": results,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary
    completed = [r for r in results if r.get("status") == "completed"]
    print(f"\n{'=' * 60}\nBENCH POC 50Q SUMMARY ({args.tag})\n{'=' * 60}")
    print(f"Completed: {len(completed)}/{len(results)}")
    if completed:
        lats = [r["metrics"].get("latency_s", r["total_latency_s"]) for r in completed]
        iters = [r["metrics"].get("n_iterations", 0) for r in completed]
        n_phantom = sum(1 for r in completed if r["phantom_tool_call"])
        n_cited = sum(1 for r in completed if r["has_citation"])
        print(f"Latence avg: {statistics.mean(lats):.1f}s  median: {statistics.median(lats):.1f}s")
        print(f"Iter avg: {statistics.mean(iters):.1f}  max: {max(iters)}")
        print(f"Phantom: {n_phantom}/{len(completed)}")
        print(f"Citation: {n_cited}/{len(completed)} ({100*n_cited/len(completed):.0f}%)")
        by_shape = {}
        for r in completed:
            by_shape.setdefault(r["primary_type"], []).append(r)
        print(f"\nPer-shape:")
        for shape in sorted(by_shape.keys()):
            rs = by_shape[shape]
            cit = sum(1 for r in rs if r["has_citation"]) / len(rs)
            print(f"  {shape:<15} n={len(rs):2d}  cite={cit:.0%}")

    print(f"\nWrote: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
