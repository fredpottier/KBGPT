"""CH-48 — Comparaison résultats Llama-3.3-70B-Turbo (CH-48) vs Qwen-72B (CH-46_POSTOPT).

Génère un rapport markdown :
- Robust : global_score, scores par catégorie, judge_stats, errors, latences
- RAGAS  : faithfulness, context_relevance, factual_correctness OSMOSIS
- T2T5   : (si baseline disponible)

Usage : docker exec knowbase-app python /app/scripts/ch48_compare_results.py
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

BASE = Path("/app/data/benchmark/results")
TAG_NEW = "V4_CH48_LLAMA_TURBO_TOGETHER"
TAG_BASELINE = "V4_CH46_POSTOPT"


def latest_run(prefix: str, tag: str) -> Path | None:
    cands = sorted(
        [p for p in BASE.glob(f"{prefix}_run_*.json") if tag in p.name],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return cands[0] if cands else None


def load(p: Path | None) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else {}


def percent_delta(new: float, old: float) -> str:
    if old == 0 and new == 0:
        return "= 0"
    delta = new - old
    sign = "+" if delta >= 0 else ""
    return f"{new:.3f} (Δ {sign}{delta:+.3f})"


def report_robust(new: dict, base: dict) -> str:
    out = ["## Robustness 170q\n"]
    n_scores = new.get("scores") or {}
    b_scores = base.get("scores") or {}
    out.append(f"| Metric | CH-46 (Qwen-72B) | CH-48 (Llama-Turbo) |")
    out.append(f"|---|---:|---:|")
    out.append(f"| **global_score** | {b_scores.get('global_score',0):.3f} | **{percent_delta(n_scores.get('global_score',0), b_scores.get('global_score',0))}** |")
    cats = sorted({
        k for k in (list(n_scores.keys()) + list(b_scores.keys()))
        if k.endswith("_score") and k != "global_score"
    })
    for k in cats:
        new_v = n_scores.get(k, 0)
        base_v = b_scores.get(k, 0)
        out.append(f"| {k} | {base_v:.3f} | {percent_delta(new_v, base_v)} |")

    n_per = new.get("per_sample") or []
    b_per = base.get("per_sample") or []
    n_errs = len(new.get("errors") or [])
    b_errs = len(base.get("errors") or [])
    out.append("")
    out.append(f"**Errors** : CH-46={b_errs}  vs  CH-48={n_errs}")
    out.append(f"**Duration** : CH-46={base.get('duration_s',0):.0f}s  vs  CH-48={new.get('duration_s',0):.0f}s (gain {(base.get('duration_s',0)-new.get('duration_s',0)):.0f}s)")

    n_judge = new.get("judge_stats") or {}
    b_judge = base.get("judge_stats") or {}
    if n_judge or b_judge:
        out.append(f"**Judge stats CH-48** : success={n_judge.get('success','?')} fail={n_judge.get('failures','?')} retries={n_judge.get('retries','?')}")

    if n_per:
        empty = sum(1 for s in n_per if not (s.get("answer") or "").strip())
        out.append(f"**Réponses vides CH-48** : {empty}/{len(n_per)}")
        cats_d = defaultdict(lambda: {"n": 0, "answer": 0, "abstain": 0})
        for s in n_per:
            t = s.get("primary_type") or s.get("category") or "?"
            cats_d[t]["n"] += 1
            ev = (s.get("evaluation") or {}).get("decision") or s.get("decision") or ""
            if "ANSWER" in str(ev).upper():
                cats_d[t]["answer"] += 1
            if "ABSTAIN" in str(ev).upper():
                cats_d[t]["abstain"] += 1
        out.append("\n**Distribution CH-48 par primary_type**")
        out.append(f"| type | n | ANSWER | ABSTAIN |")
        out.append(f"|---|---:|---:|---:|")
        for t in sorted(cats_d.keys()):
            d = cats_d[t]
            out.append(f"| {t} | {d['n']} | {d['answer']} | {d['abstain']} |")
    return "\n".join(out)


def report_ragas(new: dict, base: dict) -> str:
    out = ["\n## RAGAS gold_v4\n"]
    n_per = new.get("per_sample") or []
    b_per = base.get("per_sample") or []

    def avg(samples, key):
        vals = [s.get(key) for s in samples if isinstance(s.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else 0.0

    metrics = ["faithfulness", "context_relevance", "factual_correctness"]
    out.append(f"| Metric | CH-46 (Qwen-72B) | CH-48 (Llama-Turbo) |")
    out.append(f"|---|---:|---:|")
    for m in metrics:
        b_v = avg(b_per, m)
        n_v = avg(n_per, m)
        out.append(f"| {m} | {b_v:.3f} | {percent_delta(n_v, b_v)} |")
    out.append(f"\n**Duration** : CH-46={base.get('duration_s',0):.0f}s  vs  CH-48={new.get('duration_s',0):.0f}s")
    return "\n".join(out)


def report_t2t5(new: dict, base: dict) -> str:
    out = ["\n## T2T5 70q\n"]
    if not new and not base:
        out.append("(pas de données disponibles)")
        return "\n".join(out)
    n_scores = new.get("scores") or {}
    b_scores = base.get("scores") or {}
    keys = sorted(set(list(n_scores.keys()) + list(b_scores.keys())))
    out.append(f"| Metric | CH-46 | CH-48 |")
    out.append(f"|---|---:|---:|")
    for k in keys:
        b_v = b_scores.get(k, 0) if isinstance(b_scores.get(k), (int, float)) else 0
        n_v = n_scores.get(k, 0) if isinstance(n_scores.get(k), (int, float)) else 0
        out.append(f"| {k} | {b_v:.3f} | {percent_delta(n_v, b_v)} |")
    return "\n".join(out)


def main():
    rb_n = load(latest_run("robustness", TAG_NEW))
    rb_b = load(latest_run("robustness", TAG_BASELINE))
    rg_n = load(latest_run("ragas", TAG_NEW))
    rg_b = load(latest_run("ragas", TAG_BASELINE))
    t_n = load(latest_run("t2t5", TAG_NEW))
    t_b = load(latest_run("t2t5", TAG_BASELINE))

    md = ["# CH-48 — Llama-3.3-70B-Turbo (Together AI) vs Qwen-72B (DeepInfra)\n"]
    md.append(f"**New** : {TAG_NEW}  |  **Baseline** : {TAG_BASELINE}\n")
    md.append(report_robust(rb_n, rb_b))
    md.append(report_ragas(rg_n, rg_b))
    md.append(report_t2t5(t_n, t_b))

    out_path = Path("/app/data/audit/ch48_comparison_report.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Report written → {out_path}")
    print("\n" + "\n".join(md))


if __name__ == "__main__":
    main()
