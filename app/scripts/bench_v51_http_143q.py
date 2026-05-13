"""A — Bench complet V5.1 sur 143q gold_set_sap_v2 via endpoint HTTP réel.

Mesure progression V5.1 vs baselines connues (S0 v2 report 2026-05-13) :
- V4.2 (gold_set_v1 30q hard) : 0.333
- V5 POC v1 (gold_set_v1 30q hard) : 0.737
- V5 v2 (gold_set_v2 143q réaliste) : 0.631   ← baseline à battre / égaler
- Ceiling LLM v2 : 0.606
- EKX v1 : 0.858 (hard)

Pipeline :
1. POST /api/runtime_v5/answer pour chaque q (async)
2. Poll GET status jusqu'à completed
3. Save progressif après chaque question (anti-perte)
4. Stats agrégés par answer_shape

Usage :
    docker exec knowbase-app python scripts/bench_v51_http_143q.py
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


PHANTOM_PATTERN = re.compile(
    r"[｜|]tool[▁_]calls?[▁_](?:begin|sep|end)[｜|]|<tool[_-]call>",
    re.IGNORECASE,
)


def has_phantom(text: str) -> bool:
    return bool(text) and bool(PHANTOM_PATTERN.search(text))


def has_citation(text: str) -> bool:
    return bool(text) and bool(re.search(r"\[doc=[\w]+|\[Source\s+\d+", text))


def submit_question(base_url, tenant_id, question_text, answer_shape, idemp_key):
    r = requests.post(
        f"{base_url}/api/runtime_v5/answer",
        headers={
            "X-Tenant-ID": tenant_id,
            "X-Idempotency-Key": idemp_key,
            "Content-Type": "application/json",
        },
        json={"question": question_text, "answer_shape_hint": answer_shape},
        timeout=60,
    )
    if r.status_code == 202:
        return r.json()
    return {"_error": f"HTTP {r.status_code}: {r.text[:300]}"}


def poll_status(base_url, tenant_id, request_id, timeout_s=300, interval_s=5,
                http_timeout_s=60):
    url = f"{base_url}/api/runtime_v5/answer/{request_id}"
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        try:
            r = requests.get(url, headers={"X-Tenant-ID": tenant_id},
                              timeout=http_timeout_s)
        except requests.exceptions.Timeout:
            time.sleep(interval_s)
            continue
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}: {r.text[:300]}"}
        body = r.json()
        status = body.get("status")
        if status != last_status:
            last_status = status
        if status in ("completed", "failed", "cancelled"):
            return body
        time.sleep(interval_s)
    return {"_error": "poll_timeout"}


def get_ground_truth(q):
    gt = q.get("ground_truth")
    if isinstance(gt, dict):
        return gt.get("answer", "") or gt.get("text", "")
    return q.get("ground_truth_text", "") or q.get("answer", "")


def save_progress(path, results, ts, total_duration_s, n_total):
    path.write_text(json.dumps({
        "_meta": {
            "ts": ts,
            "n_total": n_total,
            "n_done": len(results),
            "total_duration_s": round(total_duration_s, 1),
            "panel": "gold_set_sap_v2",
        },
        "results": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--panel",
                        default="benchmark/questions/gold_set_sap_v2.json")
    parser.add_argument("--limit", type=int, default=0,
                        help="0 = all 143q. Lower for smoke.")
    parser.add_argument("--timeout-s", type=int, default=300)
    args = parser.parse_args()

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    panel_path = root / args.panel
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    qs = panel if isinstance(panel, list) else panel.get("questions", [])
    if args.limit > 0:
        qs = qs[:args.limit]
    n_total = len(qs)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / f"benchmark/runs/v51_bench_143q_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"=== Bench V5.1 — {n_total}q gold_set_sap_v2 ===")
    print(f"URL: {args.url}")
    print(f"Output: {output_path}")
    # Distribution
    print(f"Distribution shapes:")
    for k, v in Counter(q.get("primary_type") for q in qs).items():
        print(f"  {k}: {v}")

    # Health check
    r = requests.get(f"{args.url}/docs", timeout=10)
    print(f"Health: HTTP {r.status_code}")

    results = []
    t_global = time.time()
    for i, q in enumerate(qs):
        qid = q.get("id", f"q_{i}")
        ptype = q.get("primary_type", "unknown")
        question = q.get("question", "")
        gt = get_ground_truth(q)

        elapsed_global = time.time() - t_global
        progress_pct = 100 * (i + 1) / n_total
        print(f"\n[{i+1}/{n_total} ({progress_pct:.0f}%)] {qid} [{ptype}] — t+{elapsed_global:.0f}s")
        print(f"  Q: {question[:120]}...")

        idemp = f"bench143_{ts}_{qid}"
        t_q = time.time()
        sub = submit_question(args.url, args.tenant_id, question, ptype, idemp)
        if "_error" in sub:
            print(f"  ❌ submit: {sub['_error']}")
            results.append({
                "qid": qid, "primary_type": ptype,
                "question": question[:300], "ground_truth": gt[:300],
                "error": sub["_error"], "phase": "submit",
            })
            save_progress(output_path, results, ts, time.time() - t_global, n_total)
            continue

        rid = sub["request_id"]
        body = poll_status(args.url, args.tenant_id, rid,
                           timeout_s=args.timeout_s)
        total_lat = time.time() - t_q

        if "_error" in body:
            print(f"  ❌ poll: {body['_error']}")
            results.append({
                "qid": qid, "primary_type": ptype,
                "question": question[:300], "ground_truth": gt[:300],
                "request_id": rid, "error": body["_error"], "phase": "poll",
                "total_latency_s": total_lat,
            })
            save_progress(output_path, results, ts, time.time() - t_global, n_total)
            continue

        status = body.get("status")
        result = body.get("result") or {}
        err = body.get("error")
        answer = result.get("answer") or ""
        citations = result.get("citations", [])
        metrics = result.get("metrics", {})
        epi = result.get("epistemic_status", "?")
        sr = result.get("stop_reason", "")

        # Flags
        phantom = has_phantom(answer)
        cited = has_citation(answer)
        flags = ["PHANTOM"] if phantom else []
        if cited:
            flags.append("CITED")

        print(f"  → {status} | {epi} | {total_lat:.1f}s | "
              f"{metrics.get('n_iterations','?')}it | "
              f"{metrics.get('n_tool_calls','?')}tc | "
              f"{len(citations)}cit | "
              f"{'+'.join(flags) or '—'}")

        results.append({
            "qid": qid,
            "primary_type": ptype,
            "question": question[:300],
            "ground_truth": gt[:500],
            "request_id": rid,
            "status": status,
            "epistemic_status": epi,
            "stop_reason": sr,
            "answer": answer[:3000],
            "answer_chars": len(answer),
            "citations": citations,
            "n_citations": len(citations),
            "phantom_tool_call": phantom,
            "has_citation": cited,
            "metrics": metrics,
            "total_latency_s": total_lat,
            "error": err,
        })
        save_progress(output_path, results, ts, time.time() - t_global, n_total)

    total_duration = time.time() - t_global

    # ─── Aggregate report ──────────────────────────────────────────────────────
    completed = [r for r in results if r.get("status") == "completed"]
    failed = [r for r in results if r.get("status") != "completed"]

    print(f"\n{'=' * 70}")
    print(f"BENCH 143Q SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total: {len(results)} questions in {total_duration:.0f}s = {total_duration/60:.1f}min")
    print(f"Completed: {len(completed)}/{len(results)} ({100*len(completed)/len(results):.0f}%)")
    print(f"Failed:    {len(failed)}/{len(results)}")

    if completed:
        latencies = [r["metrics"].get("latency_s", r["total_latency_s"]) for r in completed]
        iters = [r["metrics"].get("n_iterations", 0) for r in completed]
        tools = [r["metrics"].get("n_tool_calls", 0) for r in completed]
        chars = [r["metrics"].get("retrieved_chars", 0) for r in completed]
        tokens = [r["metrics"].get("output_tokens", 0) for r in completed]
        ans_chars = [r["answer_chars"] for r in completed]

        print(f"\n--- Stats on {len(completed)} completed ---")
        def stat(lst, fmt=".1f"):
            return f"avg={statistics.mean(lst):{fmt}}  median={statistics.median(lst):{fmt}}  max={max(lst):{fmt}}"
        print(f"  latency_s    : {stat(latencies)}")
        print(f"  iterations   : {stat(iters)}")
        print(f"  tool_calls   : {stat(tools)}")
        print(f"  retrieved_c  : {stat(chars, '.0f')}")
        print(f"  output_tok   : {stat(tokens, '.0f')}")
        print(f"  answer_chars : {stat(ans_chars, '.0f')}")

        # Per-shape stats
        print(f"\n--- Per-shape stats ---")
        by_shape: dict[str, list[dict]] = {}
        for r in completed:
            by_shape.setdefault(r["primary_type"], []).append(r)
        for shape in sorted(by_shape.keys()):
            rs = by_shape[shape]
            lat_s = statistics.mean(r["metrics"].get("latency_s", r["total_latency_s"]) for r in rs)
            iter_avg = statistics.mean(r["metrics"].get("n_iterations", 0) for r in rs)
            cit_rate = sum(1 for r in rs if r["has_citation"]) / len(rs)
            phantom_rate = sum(1 for r in rs if r["phantom_tool_call"]) / len(rs)
            stop_concluded = sum(1 for r in rs if "concluded" in (r["stop_reason"] or "")) / len(rs)
            print(f"  {shape:<15} n={len(rs):3d}  lat={lat_s:5.1f}s  iter={iter_avg:.1f}  "
                  f"cite={cit_rate:.0%}  phantom={phantom_rate:.0%}  concluded={stop_concluded:.0%}")

        # Global flags
        n_phantom = sum(1 for r in completed if r["phantom_tool_call"])
        n_cited = sum(1 for r in completed if r["has_citation"])
        print(f"\n--- Global flags ---")
        print(f"  phantom_rate:  {n_phantom}/{len(completed)} ({100*n_phantom/len(completed):.0f}%)")
        print(f"  citation_rate: {n_cited}/{len(completed)} ({100*n_cited/len(completed):.0f}%)")
        print(f"  epistemic    : {dict(Counter(r['epistemic_status'] for r in completed))}")
        print(f"  stop_reasons : {dict(Counter(r['stop_reason'][:50] for r in completed))}")

    save_progress(output_path, results, ts, total_duration, n_total)
    print(f"\nWrote: {output_path}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
