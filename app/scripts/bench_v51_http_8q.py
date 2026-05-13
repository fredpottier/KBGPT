"""B3.full — Bench V5.1 réel via endpoint HTTP sur 8q panel quantitative.

Workflow :
1. Charge panel quantitative_panel_10q.json
2. Pour chaque question :
   a. POST /api/runtime_v5/answer → 202 + request_id
   b. Poll GET /api/runtime_v5/answer/{request_id} jusqu'à completed/failed
   c. Collecte answer, citations, metrics
3. Aggregate report

Usage :
    docker exec knowbase-app python scripts/bench_v51_http_8q.py
    # ou en local depuis l'host :
    python scripts/bench_v51_http_8q.py --url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


def make_idempotency_key(qid: str, prefix: str) -> str:
    return f"bench_{prefix}_{qid}"


def submit_question(
    base_url: str,
    tenant_id: str,
    question_text: str,
    answer_shape: str,
    idempotency_key: str,
) -> dict:
    """POST /api/runtime_v5/answer → 202 + request_id."""
    url = f"{base_url}/api/runtime_v5/answer"
    r = requests.post(
        url,
        headers={
            "X-Tenant-ID": tenant_id,
            "X-Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        },
        json={
            "question": question_text,
            "answer_shape_hint": answer_shape,
        },
        timeout=60,
    )
    if r.status_code == 202:
        return r.json()
    return {"_error": f"HTTP {r.status_code}: {r.text[:500]}"}


def poll_status(
    base_url: str,
    tenant_id: str,
    request_id: str,
    timeout_s: int = 240,
    interval_s: int = 5,
    http_timeout_s: int = 60,
) -> dict:
    """Poll GET /api/runtime_v5/answer/{request_id} jusqu'à completed/failed."""
    url = f"{base_url}/api/runtime_v5/answer/{request_id}"
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        try:
            r = requests.get(
                url,
                headers={"X-Tenant-ID": tenant_id},
                timeout=http_timeout_s,
            )
        except requests.exceptions.Timeout:
            print(f"    [poll] HTTP timeout {http_timeout_s}s, retrying...")
            time.sleep(interval_s)
            continue
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}: {r.text[:500]}"}
        body = r.json()
        status = body.get("status")
        if status != last_status:
            print(f"    [poll] status={status}")
            last_status = status
        if status in ("completed", "failed", "cancelled"):
            return body
        time.sleep(interval_s)
    return {"_error": "poll_timeout"}


def save_progress(output_path, results, total_duration_s, meta_extra: dict) -> None:
    """Sauvegarde incrémentale après chaque question."""
    payload = {
        "_meta": {
            **meta_extra,
            "n_questions_done": len(results),
            "total_duration_s": total_duration_s,
        },
        "results": results,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_ground_truth(q: dict) -> str:
    gt = q.get("ground_truth")
    if isinstance(gt, dict):
        return gt.get("answer", "") or gt.get("text", "")
    return q.get("ground_truth_text", "") or q.get("answer", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument(
        "--panel",
        default="benchmark/questions/quantitative_panel_10q.json",
    )
    parser.add_argument("--max-questions", type=int, default=8)
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument(
        "--output",
        default="benchmark/runs/v51_smoke_8q_<ts>.json",
    )
    args = parser.parse_args()

    # Resolve paths (works inside container at /app)
    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    panel_path = root / args.panel
    if not panel_path.exists():
        print(f"ERROR: panel not found: {panel_path}")
        return 1

    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    questions = panel.get("questions", [])[: args.max_questions]
    if not questions:
        print("ERROR: no questions")
        return 1

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / args.output.replace("<ts>", ts)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Health check
    print(f"=== Health check {args.url}/docs ===")
    try:
        r = requests.get(f"{args.url}/docs", timeout=10)
        print(f"  HTTP {r.status_code}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return 2

    # ─── Bench loop ──────────────────────────────────────────────────────────
    results = []
    t_global = time.time()
    meta_extra = {
        "ts": ts,
        "url": args.url,
        "tenant_id": args.tenant_id,
        "panel_source": args.panel,
        "n_questions_total": len(questions),
    }
    for i, q in enumerate(questions):
        qid = q.get("id", f"q_{i}")
        primary_type = q.get("primary_type", "unknown")
        question_text = q.get("question", "")
        ground_truth = get_ground_truth(q)

        print(f"\n[{i+1}/{len(questions)}] {qid} (type={primary_type})")
        print(f"  Q: {question_text[:150]}...")

        # 1. Submit
        idemp = make_idempotency_key(qid, prefix=ts)
        t_q = time.time()
        submission = submit_question(
            args.url, args.tenant_id, question_text, primary_type, idemp,
        )
        if "_error" in submission:
            print(f"  ❌ submit error: {submission['_error']}")
            results.append({
                "qid": qid, "primary_type": primary_type,
                "question": question_text[:300],
                "ground_truth": ground_truth[:300],
                "error": submission["_error"],
            })
            save_progress(output_path, results, time.time() - t_global, meta_extra)
            continue
        request_id = submission.get("request_id")
        print(f"  request_id: {request_id} (queued)")

        # 2. Poll
        status_body = poll_status(
            args.url, args.tenant_id, request_id,
            timeout_s=args.timeout_s,
        )
        total_latency = time.time() - t_q

        if "_error" in status_body:
            print(f"  ❌ poll error: {status_body['_error']}")
            results.append({
                "qid": qid, "primary_type": primary_type,
                "question": question_text[:300],
                "ground_truth": ground_truth[:300],
                "request_id": request_id,
                "error": status_body["_error"],
                "latency_s": total_latency,
            })
            save_progress(output_path, results, time.time() - t_global, meta_extra)
            continue

        # 3. Parse result
        result = status_body.get("result") or {}
        err = status_body.get("error")
        status = status_body.get("status")
        answer = (result.get("answer") or "")[:2000]
        citations = result.get("citations", [])
        metrics = result.get("metrics", {})
        epistemic = result.get("epistemic_status", "?")
        stop_reason = result.get("stop_reason", "")

        print(f"  status: {status}, epistemic: {epistemic}")
        print(f"  latency: {total_latency:.1f}s, agent_latency: {metrics.get('latency_s', '?')}")
        print(f"  n_iter: {metrics.get('n_iterations', '?')}, n_tools: {metrics.get('n_tool_calls', '?')}")
        print(f"  n_citations: {len(citations)}")
        print(f"  answer ({len(answer)} chars): {answer[:200]}...")

        results.append({
            "qid": qid,
            "primary_type": primary_type,
            "question": question_text[:300],
            "ground_truth": ground_truth[:300],
            "request_id": request_id,
            "status": status,
            "epistemic_status": epistemic,
            "stop_reason": stop_reason,
            "answer": answer,
            "citations": citations,
            "metrics": metrics,
            "total_latency_s": total_latency,
            "error": err,
        })
        save_progress(output_path, results, time.time() - t_global, meta_extra)

    total_duration = time.time() - t_global

    # ─── Aggregate report ────────────────────────────────────────────────────
    completed = [r for r in results if r.get("status") == "completed"]
    failed = [r for r in results if r.get("status") != "completed"]

    print(f"\n{'=' * 60}")
    print(f"BENCH 8Q SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total: {len(results)} questions in {total_duration:.1f}s")
    print(f"Completed: {len(completed)}/{len(results)}")
    print(f"Failed:    {len(failed)}/{len(results)}")

    if completed:
        latencies = [r["metrics"].get("latency_s", r["total_latency_s"]) for r in completed]
        iters = [r["metrics"].get("n_iterations", 0) for r in completed]
        tools = [r["metrics"].get("n_tool_calls", 0) for r in completed]
        chars = [r["metrics"].get("retrieved_chars", 0) for r in completed]
        tokens = [r["metrics"].get("output_tokens", 0) for r in completed]

        print(f"\n--- Stats on {len(completed)} completed ---")
        print(f"  latency_s   : avg={statistics.mean(latencies):.1f}  median={statistics.median(latencies):.1f}  max={max(latencies):.1f}")
        print(f"  iterations  : avg={statistics.mean(iters):.1f}  median={statistics.median(iters):.0f}  max={max(iters)}")
        print(f"  tool_calls  : avg={statistics.mean(tools):.1f}  median={statistics.median(tools):.0f}  max={max(tools)}")
        print(f"  retrieved   : avg={statistics.mean(chars):.0f} chars  max={max(chars)}")
        print(f"  output_tok  : avg={statistics.mean(tokens):.0f}  max={max(tokens)}")

        # Epistemic distribution
        from collections import Counter
        epi = Counter(r["epistemic_status"] for r in completed)
        print(f"\n  epistemic_status: {dict(epi)}")
        # Stop reason distribution
        sr = Counter(r["stop_reason"][:50] for r in completed)
        print(f"  stop_reasons: {dict(sr)}")
        # Citations rate
        cited = sum(1 for r in completed if r.get("citations"))
        print(f"  with_citation: {cited}/{len(completed)} ({100*cited/len(completed):.0f}%)")

    # Persist
    payload = {
        "_meta": {
            "ts": ts,
            "url": args.url,
            "tenant_id": args.tenant_id,
            "panel_source": args.panel,
            "n_questions": len(results),
            "n_completed": len(completed),
            "total_duration_s": total_duration,
        },
        "results": results,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    print(f"\nWrote: {output_path}")

    if failed:
        print(f"\n--- Failed questions ---")
        for r in failed:
            print(f"  {r['qid']} : {r.get('error', r.get('status'))}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
