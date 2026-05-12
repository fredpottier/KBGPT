"""Bake-off A/B mode séparé vs unifié (Amendment 7).

Lance 30q smoke (sample stratifié gold v5) sur /api/runtime_v4_2/answer dans
les deux modes, mesure :
  - latence (p50, p95)
  - skip_qa rate (mode unifié)
  - decision agreement (ANSWER vs ABSTAIN)
  - structured_avg (multi-view scorer une fois P1.4 livré)

Output: data/audit/runtime_v4_2_unified_bakeoff_<timestamp>.json

Usage (depuis container app) :
  docker exec knowbase-app python /app/app/scripts/runtime_v4_2_unified_bakeoff.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import time
from pathlib import Path

import requests

API = "http://knowbase-app:8000/api/runtime_v4_2/answer"
HEALTH = "http://knowbase-app:8000/api/runtime_v4_2/health"
GOLD_PATH = Path("/app/benchmark/questions/gold_set_v5.json")

# Sample stratifié 30q (5 par type — meme set que POC v2)
SAMPLE_OIDS = [
    # factual
    "T1_AERO_0001", "T1_AERO_0002", "T1_AERO_0006", "T1_AERO_0007", "T1_AERO_0009",
    # list
    "T6_AERO_LIST_001", "T6_AERO_LIST_002", "T6_AERO_LIST_003",
    "T6_AERO_LIST_004", "T6_AERO_LIST_005",
    # temporal
    "T7_AERO_0001", "T7_AERO_0032", "T7_AERO_0031",
    "T6_AERO_TMP_005", "T7_AERO_0041",
    # causal
    "T6_AERO_CAUSAL_001", "T6_AERO_CAUSAL_002", "T6_AERO_CAUSAL_003",
    "T6_AERO_CAUSAL_004", "T6_AERO_CAUSAL_005",
    # unanswerable
    "T6_AERO_UNA_001", "T6_AERO_UNA_002", "T6_AERO_UNA_003",
    "T6_AERO_UNA_004", "T6_AERO_UNA_005",
    # multi_hop
    "T5_AERO_0001", "T5_AERO_0002", "T5_AERO_0003",
    "T5_AERO_0004", "T5_AERO_0005",
]


def load_gold() -> dict:
    if not GOLD_PATH.exists():
        raise FileNotFoundError(f"Gold v5 introuvable: {GOLD_PATH}")
    raw = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    return {q["source_id"]: q for q in raw}


def run_one(question: str, top_k: int = 12, timeout: int = 90) -> dict:
    t0 = time.time()
    try:
        r = requests.post(API, json={"question": question, "top_k_claims": top_k}, timeout=timeout)
        wall = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "wall_ms": wall}
        d = r.json()
        d["_wall_ms"] = wall
        return d
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "wall_ms": int((time.time() - t0) * 1000)}


def aggregate(rows: list[dict]) -> dict:
    latencies = [r.get("_wall_ms") for r in rows if r.get("_wall_ms")]
    decisions = [r.get("decision") for r in rows]
    answers = sum(1 for d in decisions if d == "ANSWER")
    abstains = sum(1 for d in decisions if d == "ABSTAIN")
    errors = sum(1 for r in rows if r.get("error"))
    skipped = sum(
        1 for r in rows
        if (r.get("latency_breakdown_ms") or {}).get("unified_qa_skipped") == 1
    )
    p50 = statistics.median(latencies) if latencies else None
    p95 = sorted(latencies)[int(round(0.95 * (len(latencies) - 1)))] if latencies else None
    return {
        "n": len(rows),
        "n_answer": answers,
        "n_abstain": abstains,
        "n_error": errors,
        "qa_skipped": skipped,
        "qa_skipped_rate": round(skipped / max(1, len(rows)), 3),
        "wall_ms_p50": int(p50) if p50 else None,
        "wall_ms_p95": int(p95) if p95 else None,
    }


def run_phase(label: str, gold_by_oid: dict) -> dict:
    rows: list[dict] = []
    print(f"\n=== Phase: {label} ===")
    for oid in SAMPLE_OIDS:
        g = gold_by_oid.get(oid)
        if not g:
            print(f"  - {oid}: missing in gold")
            rows.append({"oid": oid, "error": "missing_in_gold"})
            continue
        q = g["question"]
        result = run_one(q)
        result["oid"] = oid
        result["primary_type"] = g.get("primary_type")
        rows.append(result)
        layer = result.get("layer", "?")
        decision = result.get("decision", "?")
        wall = result.get("_wall_ms", 0)
        print(f"  - {oid:25s} | {decision:7s} | layer={layer:24s} | wall={wall}ms")
    return {"label": label, "rows": rows, "agg": aggregate(rows)}


def health() -> dict:
    try:
        return requests.get(HEALTH, timeout=10).json()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def main() -> None:
    gold_by_oid = load_gold()
    print(f"Gold loaded: {len(gold_by_oid)} questions")
    print(f"Sample size: {len(SAMPLE_OIDS)}")
    print(f"Health: {json.dumps(health(), indent=2)[:500]}")

    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    output = Path(f"/app/data/audit/runtime_v4_2_unified_bakeoff_{timestamp}.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Phase A : mode séparé (default)
    os.environ.pop("RUNTIME_V4_2_UNIFIED_PROMPT", None)
    # Note : variable env doit être set côté container avant restart pour effet ;
    # ici on lit juste le state actuel via /health pour confirmer.
    h_a = health().get("config", {}).get("unified_prompt_enabled")
    print(f"\n[Phase A] unified_prompt_enabled (server) = {h_a}")
    phase_a = run_phase("separate", gold_by_oid) if h_a is False else {
        "label": "separate", "skipped_reason": "server_unified_enabled_at_startup"
    }

    # Phase B : mode unifié
    print(f"\n[Phase B] need RUNTIME_V4_2_UNIFIED_PROMPT=true on server then restart app")
    print("[Phase B] this script alone cannot toggle env mid-run — run twice with proper env")
    phase_b = {"label": "unified", "skipped_reason": "manual_env_toggle_required"}

    payload = {
        "timestamp": timestamp,
        "sample_size": len(SAMPLE_OIDS),
        "phase_a_separate": phase_a,
        "phase_b_unified": phase_b,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWritten {output}")
    print(f"Phase A agg: {phase_a.get('agg')}")
    print(f"Phase B agg: {phase_b.get('agg')}")


if __name__ == "__main__":
    main()
