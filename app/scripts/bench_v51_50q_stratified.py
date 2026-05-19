"""Re-bench 50q stratifié post-fix available_docs.

Échantillonnage représentatif depuis gold_set_sap_v2 (143q) :
- 15 factual (sur 50)
- 8 comparison (sur 28)
- 8 multi_hop (sur 23)
- 3 contextual (sur 9)
- 3 false_premise (sur 6)
- 3 causal (sur 6)
- 3 listing (sur 6)
- 3 negation (sur 6)
- 2 lifecycle (sur 3)
- 1 quantitative (sur 3)
- 1 unanswerable (sur 3)
= 50 questions, distribution alignée

Tenant_id rotatif pour bypass AdmissionController. Seed=42 pour reproductibilité.
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

import requests


PHANTOM_PATTERN = re.compile(
    r"[｜|]tool[▁_]calls?[▁_](?:begin|sep|end)[｜|]|<tool[_-]call>",
    re.IGNORECASE,
)

STRATIFIED_QUOTA = {
    "factual": 15,
    "comparison": 8,
    "multi_hop": 8,
    "contextual": 3,
    "false_premise": 3,
    "causal": 3,
    "listing": 3,
    "negation": 3,
    "lifecycle": 2,
    "quantitative": 1,
    "unanswerable": 1,
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


def submit(base_url, tenant, question, shape, idemp, llm_model=None):
    payload = {"question": question, "answer_shape_hint": shape}
    if llm_model:
        payload["llm_model"] = llm_model
    # timeout=180 : l'app peut être saturée par 3 benchs concurrents
    r = requests.post(
        f"{base_url}/api/runtime_v5/answer",
        headers={"X-Tenant-ID": tenant, "X-Idempotency-Key": idemp,
                 "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    return r.json() if r.status_code == 202 else {"_error": f"HTTP {r.status_code}: {r.text[:300]}"}


def poll(base_url, tenant, request_id, timeout_s=300, interval_s=5):
    url = f"{base_url}/api/runtime_v5/answer/{request_id}"
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        try:
            r = requests.get(url, headers={"X-Tenant-ID": tenant}, timeout=60)
        except requests.exceptions.Timeout:
            time.sleep(interval_s)
            continue
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}: {r.text[:300]}"}
        body = r.json()
        st = body.get("status")
        if st != last_status:
            last_status = st
        if st in ("completed", "failed", "cancelled"):
            return body
        time.sleep(interval_s)
    return {"_error": "poll_timeout"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--panel", default="benchmark/questions/gold_set_sap_v2.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--questions-per-tenant", type=int, default=5,
                        help="rotate tenant after N questions")
    parser.add_argument("--sleep-between-q", type=int, default=3)
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.add_argument("--tag", default="postfix")
    parser.add_argument("--limit", type=int, default=0,
                        help="if >0, keep only first N questions of stratified sample (preserves seed order)")
    parser.add_argument("--model", default="",
                        help="LLM model override (bench bake-off). Ex: meta-llama/Llama-3.3-70B-Instruct. "
                             "Si vide, le runtime utilise V5_LLM_MODEL.")
    args = parser.parse_args()

    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    panel_path = root / args.panel
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    qs_all = panel if isinstance(panel, list) else panel.get("questions", [])

    selected = stratified_sample(qs_all, seed=args.seed)
    if args.limit > 0:
        selected = selected[: args.limit]
    print(f"=== Re-bench 50q stratifié ({args.tag}) ===")
    print(f"Selected: {len(selected)} / {len(qs_all)}")
    dist = Counter(q.get("primary_type") for q in selected)
    for k, v in sorted(dist.items()):
        print(f"  {k}: {v}")

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / f"benchmark/runs/v51_bench_50q_{args.tag}_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Health check (timeout généreux quand benchs concurrents saturent l'app)
    try:
        r = requests.get(f"{args.url}/docs", timeout=30)
        print(f"Health: HTTP {r.status_code}")
    except Exception as e:
        print(f"Health WARN: {e} — continuing anyway (transient load)")

    results = []
    t_global = time.time()
    for i, q in enumerate(selected):
        qid = q.get("id", f"q_{i}")
        ptype = q.get("primary_type", "?")
        question = q.get("question", "")
        gt = q.get("ground_truth", {})
        if isinstance(gt, dict):
            gt = gt.get("answer") or gt.get("text") or ""
        tenant = f"bench50_{args.tag}_t{i // args.questions_per_tenant}"
        idemp = f"bench50_{args.tag}_{ts}_{qid}_{tenant}"

        elapsed = time.time() - t_global
        print(f"\n[{i+1}/{len(selected)}] {qid} [{ptype}] tenant={tenant} t+{elapsed:.0f}s")
        print(f"  Q: {question[:120]}...")

        t_q = time.time()
        sub = submit(args.url, tenant, question, ptype, idemp,
                     llm_model=args.model or None)
        if "_error" in sub:
            print(f"  ❌ submit: {sub['_error'][:150]}")
            results.append({**q, "qid": qid, "primary_type": ptype,
                            "question": question[:300], "ground_truth": gt[:500],
                            "error": sub["_error"], "phase": "submit"})
            time.sleep(args.sleep_between_q)
            continue
        rid = sub["request_id"]
        body = poll(args.url, tenant, rid, timeout_s=args.timeout_s)
        total_lat = time.time() - t_q

        if "_error" in body:
            print(f"  ❌ poll: {body['_error']}")
            results.append({**q, "qid": qid, "primary_type": ptype,
                            "question": question[:300], "ground_truth": gt[:500],
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
        verifier_report = result.get("verifier_report")  # A5 S7.7 Mode A
        phantom = has_phantom(answer)
        cited = has_citation(answer)

        v_outcome = (verifier_report or {}).get("outcome", "n/a")
        v_supp = (verifier_report or {}).get("support_rate", 0.0)
        print(f"  → {body.get('status')} | {epi} | {total_lat:.1f}s | "
              f"{metrics.get('n_iterations','?')}it | "
              f"{metrics.get('n_tool_calls','?')}tc | "
              f"{len(citations)}cit | "
              f"v={v_outcome}({v_supp:.2f}) | "
              f"{'PHANTOM' if phantom else ''}{'CITED' if cited else ''}")

        results.append({
            "qid": qid, "primary_type": ptype,
            "question": question[:300], "ground_truth": gt[:500],
            "request_id": rid, "status": body.get("status"),
            "epistemic_status": epi, "stop_reason": sr,
            "answer": answer[:3000], "answer_chars": len(answer),
            "citations": citations, "n_citations": len(citations),
            "phantom_tool_call": phantom, "has_citation": cited,
            "metrics": metrics, "total_latency_s": total_lat,
            "verifier_report": verifier_report,
        })

        # Save progressive
        output_path.write_text(json.dumps({
            "_meta": {"ts": ts, "tag": args.tag, "n_done": i + 1, "n_total": len(selected),
                      "seed": args.seed, "fix": "available_docs in user prompt"},
            "results": results,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        time.sleep(args.sleep_between_q)

    # Summary
    completed = [r for r in results if r.get("status") == "completed"]
    print(f"\n{'=' * 60}\nBENCH 50Q SUMMARY ({args.tag})\n{'=' * 60}")
    print(f"Completed: {len(completed)}/{len(results)}")
    if completed:
        lats = [r["metrics"].get("latency_s", r["total_latency_s"]) for r in completed]
        iters = [r["metrics"].get("n_iterations", 0) for r in completed]
        n_phantom = sum(1 for r in completed if r["phantom_tool_call"])
        n_cited = sum(1 for r in completed if r["has_citation"])
        print(f"Latence avg: {statistics.mean(lats):.1f}s  median: {statistics.median(lats):.1f}s")
        print(f"Iter avg: {statistics.mean(iters):.1f}")
        print(f"Phantom: {n_phantom}/{len(completed)}")
        print(f"Citation: {n_cited}/{len(completed)} ({100*n_cited/len(completed):.0f}%)")
        # Per shape
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
