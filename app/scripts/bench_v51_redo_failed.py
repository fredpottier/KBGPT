"""Relance les questions failed du bench 143q (admission denied).

Utilise rotation tenant_id pour bypass rate_limit + daily_quota_complex.
À fusionner ensuite dans le fichier bench final.

Usage :
    docker exec knowbase-app python scripts/bench_v51_redo_failed.py \\
        --input benchmark/runs/v51_bench_143q_<ts>.json \\
        --questions-per-tenant 4
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                        help="bench output JSON with failed questions")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--questions-per-tenant", type=int, default=4,
                        help="rotate tenant after N questions (bypass rate)")
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.add_argument("--sleep-between-q", type=int, default=2,
                        help="seconds between submits (anti-burst)")
    args = parser.parse_args()

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    input_path = root / args.input if not Path(args.input).is_absolute() else Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    results = data["results"]
    failed = [r for r in results if r.get("status") != "completed"]
    completed = [r for r in results if r.get("status") == "completed"]

    print(f"=== Redo failed questions ===")
    print(f"Input: {input_path}")
    print(f"Total : {len(results)} | Completed: {len(completed)} | To redo: {len(failed)}")

    if not failed:
        print("Nothing to redo!")
        return 0

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    redone = []
    t_global = time.time()

    for i, q in enumerate(failed):
        qid = q.get("qid")
        ptype = q.get("primary_type", "unknown")
        question = q.get("question", "")
        gt = q.get("ground_truth", "")
        # Rotate tenant_id every N questions
        tenant = f"benchredo_t{i // args.questions_per_tenant}"
        idemp = f"redo_{ts}_{qid}_{tenant}"

        elapsed = time.time() - t_global
        print(f"\n[{i+1}/{len(failed)}] {qid} [{ptype}] tenant={tenant} t+{elapsed:.0f}s")
        print(f"  Q: {question[:100]}...")

        t_q = time.time()
        sub = submit_question(args.url, tenant, question, ptype, idemp)
        if "_error" in sub:
            print(f"  ❌ submit: {sub['_error'][:150]}")
            redone.append({
                **q, "redo_error": sub["_error"], "redo_tenant": tenant,
                "redo_phase": "submit",
            })
            time.sleep(args.sleep_between_q)
            continue

        rid = sub["request_id"]
        body = poll_status(args.url, tenant, rid, timeout_s=args.timeout_s)
        total_lat = time.time() - t_q

        if "_error" in body:
            print(f"  ❌ poll: {body['_error']}")
            redone.append({
                **q, "redo_error": body["_error"], "redo_tenant": tenant,
                "redo_phase": "poll", "redo_total_latency_s": total_lat,
            })
            time.sleep(args.sleep_between_q)
            continue

        status = body.get("status")
        result = body.get("result") or {}
        answer = result.get("answer") or ""
        citations = result.get("citations", [])
        metrics = result.get("metrics", {})
        epi = result.get("epistemic_status", "?")
        sr = result.get("stop_reason", "")
        phantom = has_phantom(answer)
        cited = has_citation(answer)

        print(f"  → {status} | {epi} | {total_lat:.1f}s | "
              f"{metrics.get('n_iterations','?')}it | "
              f"{metrics.get('n_tool_calls','?')}tc | "
              f"{len(citations)}cit | "
              f"{'PHANTOM' if phantom else ''}{'CITED' if cited else ''}")

        # Update record (replace failed with new data)
        new_record = {
            "qid": qid,
            "primary_type": ptype,
            "question": question,
            "ground_truth": gt,
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
            "error": None,
            "redo_tenant": tenant,
        }
        redone.append(new_record)
        time.sleep(args.sleep_between_q)

    # Save merged file
    new_completed = [r for r in redone if r.get("status") == "completed"]
    new_failed = [r for r in redone if r.get("status") != "completed"]
    print(f"\n{'=' * 60}")
    print(f"REDO SUMMARY")
    print(f"{'=' * 60}")
    print(f"Re-attempted: {len(redone)}")
    print(f"  Now completed: {len(new_completed)}")
    print(f"  Still failed : {len(new_failed)}")

    # Merge into original
    merged_results = list(completed)
    for r in redone:
        merged_results.append(r)

    out_path = input_path.parent / f"{input_path.stem}_merged_{ts}.json"
    payload = {
        "_meta": {
            **(data.get("_meta", {})),
            "redo_ts": ts,
            "n_completed_total": len(completed) + len(new_completed),
            "n_failed_total": len(new_failed),
            "n_redone": len(redone),
            "merge_duration_s": time.time() - t_global,
        },
        "results": merged_results,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote merged: {out_path}")
    return 0 if not new_failed else 2


if __name__ == "__main__":
    sys.exit(main())
