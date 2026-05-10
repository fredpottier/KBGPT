"""CH-48 — Agrégation bench micro stratifié + comparaison baseline V4_CH46."""
from __future__ import annotations
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def aggregate(path: Path, label: str) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = raw if isinstance(raw, list) else raw.get("results") or raw.get("per_sample") or []
    by_type = defaultdict(list)
    for r in results:
        by_type[r.get("primary_type", "?")].append(r)

    print(f"\n=== {label} ===")
    header = f'{"type":12s} | {"n":>3s} | {"ANSWER":>9s} | {"ABSTAIN":>9s} | {"reason":>9s} | {"p50":>7s} | {"p95":>7s}'
    print(header)
    print("-" * len(header))

    out: dict = {"label": label, "by_type": {}, "global": {}}
    totals = {"n": 0, "answer": 0, "abstain": 0, "reasoning": 0, "walls": []}
    for t in ["list", "factual", "temporal", "comparison", "causal"]:
        rs = by_type.get(t, [])
        n = len(rs)
        if n == 0:
            continue
        answer = sum(1 for r in rs if r.get("decision") == "ANSWER")
        abstain = sum(1 for r in rs if r.get("decision") == "ABSTAIN")
        reasoning = sum(
            1 for r in rs
            if r.get("routing") == "reasoning_path" or r.get("routing_decision") == "reasoning_path"
        )
        walls = [r.get("wall_ms", 0) for r in rs if "error" not in r and r.get("wall_ms")]
        p50 = int(statistics.median(walls)) if walls else 0
        p95 = int(sorted(walls)[max(0, int(len(walls) * 0.95) - 1)]) if walls else 0
        totals["n"] += n
        totals["answer"] += answer
        totals["abstain"] += abstain
        totals["reasoning"] += reasoning
        totals["walls"] += walls
        out["by_type"][t] = {
            "n": n, "answer": answer, "abstain": abstain,
            "reasoning": reasoning, "p50_ms": p50, "p95_ms": p95,
        }
        print(f'{t:12s} | {n:>3d} | {answer:>3d}/{n:<3d}      | {abstain:>3d}/{n:<3d}      | {reasoning:>3d}/{n:<3d}      | {p50:>5d}ms | {p95:>5d}ms')

    print("-" * len(header))
    gp50 = int(statistics.median(totals["walls"])) if totals["walls"] else 0
    gp95 = int(sorted(totals["walls"])[max(0, int(len(totals["walls"]) * 0.95) - 1)]) if totals["walls"] else 0
    out["global"] = {
        "n": totals["n"], "answer": totals["answer"], "abstain": totals["abstain"],
        "reasoning": totals["reasoning"], "p50_ms": gp50, "p95_ms": gp95,
    }
    print(f'{"TOTAL":12s} | {totals["n"]:>3d} | {totals["answer"]:>3d}/{totals["n"]:<3d}      | {totals["abstain"]:>3d}/{totals["n"]:<3d}      | {totals["reasoning"]:>3d}/{totals["n"]:<3d}      | {gp50:>5d}ms | {gp95:>5d}ms')
    print(f'ANSWER {100 * totals["answer"] / max(totals["n"], 1):.0f}% | ABSTAIN {100 * totals["abstain"] / max(totals["n"], 1):.0f}% | mean wall {sum(totals["walls"]) / max(len(totals["walls"]), 1) / 1000:.1f}s')
    return out


def main():
    cur = aggregate(Path("/app/data/audit/ch48_stratified_llama_turbo.json"), "CH-48 Llama-3.3-70B-Turbo (full pipeline, Together)")
    base_paths = [
        ("/app/data/router/v4_stratified_CH46_post.json", "V4_CH46_POSTOPT (Qwen-72B DeepInfra)"),
        ("/app/data/router/v4_stratified_CH46_quality.json", "V4_CH46_QUALITY (Qwen-72B DeepInfra)"),
    ]
    baselines = []
    for p, label in base_paths:
        if Path(p).exists():
            baselines.append(aggregate(Path(p), label))

    if baselines:
        print("\n=== DELTA Llama-Turbo vs baseline V4_CH46 ===")
        for base in baselines:
            print(f"\nBase = {base['label']}")
            print(f'{"type":12s} | {"Δ ANSWER%":>10s} | {"Δ ABSTAIN%":>11s} | {"Δ p50":>9s}')
            print("-" * 55)
            for t in ["list", "factual", "temporal", "comparison", "causal"]:
                if t not in cur["by_type"] or t not in base["by_type"]:
                    continue
                c = cur["by_type"][t]
                b = base["by_type"][t]
                d_ans = 100 * (c["answer"] / c["n"] - b["answer"] / b["n"])
                d_abs = 100 * (c["abstain"] / c["n"] - b["abstain"] / b["n"])
                d_p50 = c["p50_ms"] - b["p50_ms"]
                print(f'{t:12s} | {d_ans:>+8.1f}pp | {d_abs:>+9.1f}pp | {d_p50:>+6d}ms')
            cg = cur["global"]
            bg = base["global"]
            d_ans = 100 * (cg["answer"] / cg["n"] - bg["answer"] / bg["n"])
            d_abs = 100 * (cg["abstain"] / cg["n"] - bg["abstain"] / bg["n"])
            d_p50 = cg["p50_ms"] - bg["p50_ms"]
            print("-" * 55)
            print(f'{"GLOBAL":12s} | {d_ans:>+8.1f}pp | {d_abs:>+9.1f}pp | {d_p50:>+6d}ms')


if __name__ == "__main__":
    main()
