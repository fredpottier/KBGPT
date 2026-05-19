"""V6 Double Bench — lance 2 modèles en parallèle pour mesurer Δ pipeline.

Protocole : DS-V3.1 (plafond) + Qwen-2.5-72B (robustesse) en // sur même panel.
Δ = score(DS31) − score(Qwen72) = dépendance pipeline au LLM, à minimiser.

Voir doc/ongoing/V6_DOUBLE_BENCH_PROTOCOL.md pour les targets V6.

Usage :
    docker exec knowbase-app python scripts/v6_double_bench.py --tag v6_jalon_1
    docker exec knowbase-app python scripts/v6_double_bench.py --tag v6_quick --limit 15
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# Paire fixe de modèles selon le protocole V6
MODELS = [
    ("ds31", "deepseek-ai/DeepSeek-V3.1"),
    ("qwen72", "Qwen/Qwen2.5-72B-Instruct"),
]


def _shell(cmd: str, capture: bool = True, timeout: int = 30) -> str:
    """Exec une commande shell (le script tourne déjà dans knowbase-app).
    Returns stdout. Ne lève PAS si exit != 0 (caller check)."""
    proc = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=capture, text=True, timeout=timeout,
    )
    return proc.stdout.strip() if capture else ""


def _launch_bench(tag: str, model: str, limit: int, sleep_q: int) -> str:
    """Lance un bench en background via nohup. Returns log_path."""
    log_path = f"/tmp/bench_{tag}.log"
    cmd_str = (
        f"cd /app && nohup python scripts/bench_v51_50q_stratified.py "
        f"--tag {tag} "
        f"--sleep-between-q {sleep_q} "
        f"--model {model} "
    )
    if limit > 0:
        cmd_str += f"--limit {limit} "
    cmd_str += f"> {log_path} 2>&1 &"
    _shell(cmd_str, capture=False)
    return log_path


def _is_bench_done(log_path: str) -> bool:
    """True si le bench a écrit son BENCH SUMMARY."""
    try:
        out = _shell(f"grep -c 'BENCH 50Q SUMMARY' {log_path} 2>/dev/null || echo 0")
        return int(out.strip() or "0") >= 1
    except Exception:
        return False


def _wait_benches(log_paths: list[str], poll_interval: int = 30, max_wait_s: int = 7200) -> bool:
    """Attend que tous les benchs soient finis. True si OK, False si timeout."""
    start = time.time()
    while time.time() - start < max_wait_s:
        all_done = all(_is_bench_done(p) for p in log_paths)
        if all_done:
            return True
        elapsed = int(time.time() - start)
        statuses = []
        for p in log_paths:
            try:
                last = _shell(f"grep -oE '\\[[0-9]+/[0-9]+\\]' {p} 2>/dev/null | tail -1")
                statuses.append(last or "starting")
            except Exception:
                statuses.append("?")
        print(f"  [{elapsed}s] {' | '.join(statuses)}", flush=True)
        time.sleep(poll_interval)
    return False


def _find_latest_output(tag: str) -> str:
    """Retourne le path du dernier JSON output produit pour ce tag."""
    out = _shell(
        f"ls -t /app/benchmark/runs/v51_bench_50q_{tag}_*.json 2>/dev/null "
        f"| grep -v scored | head -1"
    )
    return out.strip()


def _score_bench(json_path: str, limit: int) -> dict:
    """Lance le judge sur un JSON, retourne {'mean': float, 'per_shape': {...}}."""
    cmd_str = (
        f"cd /app && python scripts/score_v51_bench_judge.py "
        f"--input {json_path}"
    )
    if limit > 0:
        cmd_str += f" --limit {limit}"
    # Run synchronously, capture output
    proc = subprocess.run(
        ["bash", "-c", cmd_str],
        capture_output=True, text=True, timeout=600,
    )
    output = proc.stdout + "\n" + proc.stderr
    # Parse mean score
    mean = None
    per_shape: dict[str, float] = {}
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("Mean score:"):
            try:
                mean = float(line.split(":")[1].strip())
            except Exception:
                pass
        # "  comparison      n=  8  mean=0.500 ..."
        if "mean=" in line and "n=" in line:
            parts = line.split()
            if parts and parts[0] in (
                "factual", "comparison", "multi_hop", "contextual",
                "causal", "lifecycle", "listing", "negation",
                "false_premise", "quantitative", "unanswerable",
            ):
                shape = parts[0]
                for p in parts:
                    if p.startswith("mean="):
                        try:
                            per_shape[shape] = float(p.split("=")[1])
                        except Exception:
                            pass
                        break
    return {"mean": mean if mean is not None else 0.0, "per_shape": per_shape}


def _format_report(tag: str, results: dict, limit: int) -> str:
    """Format un rapport markdown du double bench."""
    ds31 = results["ds31"]
    qwen72 = results["qwen72"]
    delta = ds31["mean"] - qwen72["mean"]

    lines = [
        f"# V6 Double Bench — {tag}",
        f"_Generated {datetime.utcnow().isoformat()}Z, panel={50 if limit <= 0 else limit}q_",
        "",
        "## Résultats globaux",
        "",
        "| Modèle | Mean | Rôle |",
        "|---|---|---|",
        f"| **DeepSeek-V3.1** | **{ds31['mean']:.3f}** | plafond capacité |",
        f"| **Qwen-2.5-72B** | **{qwen72['mean']:.3f}** | robustesse pipeline |",
        f"| **Δ (DS31 − Qwen72)** | **{delta:.3f}** | dépendance LLM (↘ idéal) |",
        "",
        "## Per shape",
        "",
        "| Shape | DS-V3.1 | Qwen-72B | Δ |",
        "|---|---|---|---|",
    ]
    shapes = sorted(set(ds31["per_shape"].keys()) | set(qwen72["per_shape"].keys()))
    for shape in shapes:
        a = ds31["per_shape"].get(shape)
        b = qwen72["per_shape"].get(shape)
        a_s = f"{a:.3f}" if a is not None else "—"
        b_s = f"{b:.3f}" if b is not None else "—"
        d_s = f"{(a - b):.3f}" if (a is not None and b is not None) else "—"
        lines.append(f"| {shape} | {a_s} | {b_s} | {d_s} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="Tag du jalon V6 (ex: v6_jalon_1)")
    parser.add_argument("--limit", type=int, default=0, help="Sample slice (0=full 50q)")
    parser.add_argument("--sleep-q", type=int, default=2, help="Sleep entre questions")
    parser.add_argument("--no-score", action="store_true", help="Skip scoring (debug)")
    args = parser.parse_args()

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    print(f"=== V6 Double Bench — {args.tag} ({ts}) ===")
    print(f"Models: {', '.join(m[1] for m in MODELS)}")
    print(f"Limit: {args.limit or '50 (full)'}")
    print()

    # 1) Lance les 2 benchs en parallèle
    log_paths = []
    bench_tags = []
    for short, model in MODELS:
        tag = f"{args.tag}_{short}"
        bench_tags.append(tag)
        log_path = _launch_bench(tag, model, args.limit, args.sleep_q)
        log_paths.append(log_path)
        print(f"  Launched {short}: {log_path}")
        time.sleep(8)  # Décalage 8s pour éviter health check concurrent

    # 2) Attend la fin
    print("\nWaiting for bench completion...")
    ok = _wait_benches(log_paths, poll_interval=60)
    if not ok:
        print("TIMEOUT waiting for benchs", file=sys.stderr)
        return 2
    print("Both benchs done.\n")

    if args.no_score:
        print("Skipping scoring (--no-score)")
        return 0

    # 3) Score
    print("Scoring...")
    results = {}
    for (short, _model), tag in zip(MODELS, bench_tags):
        json_path = _find_latest_output(tag)
        if not json_path:
            print(f"  ERROR: no output for {tag}")
            results[short] = {"mean": 0.0, "per_shape": {}}
            continue
        print(f"  Scoring {short} ({json_path})...")
        results[short] = _score_bench(json_path, args.limit)

    # 4) Rapport
    report = _format_report(args.tag, results, args.limit)
    print("\n" + report + "\n")

    # 5) Persist
    output_dir = Path(__file__).resolve().parents[2] / "benchmark" / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"v6_double_bench_{args.tag}_{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    json_path = output_dir / f"v6_double_bench_{args.tag}_{ts}.json"
    json_path.write_text(json.dumps({
        "tag": args.tag,
        "ts": ts,
        "limit": args.limit,
        "results": results,
        "delta": results["ds31"]["mean"] - results["qwen72"]["mean"],
    }, indent=2), encoding="utf-8")
    print(f"Saved: {report_path}")
    print(f"Saved: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
