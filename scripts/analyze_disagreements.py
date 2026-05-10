#!/usr/bin/env python3
"""
CH-40.6 — Analyse des désaccords judge LLM vs structured metrics.

Lit un rapport bench Robustness (avec disagreement calculé en CH-40.2/CH-40.6)
et génère doc/ongoing/V4_S0_DISAGREEMENT_ANALYSIS.md avec :
- Top-20 cas judge_overscored (Claude juge dit "bon" mais structured dit "mauvais")
  → hypothèse principale : style over substance
- Top-20 cas judge_underscored (Claude rate ce que structured a vu)
- Distribution disagreement par catégorie / primary_type

Usage :
  python scripts/analyze_disagreements.py [--report PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_DIR = PROJECT_ROOT / "app" / "data" / "benchmark" / "results"
OUTPUT_PATH = PROJECT_ROOT / "doc" / "ongoing" / "V4_S0_DISAGREEMENT_ANALYSIS.md"


def find_latest_report() -> Path | None:
    """Trouve le rapport bench Robustness V3_S0_* le plus récent."""
    candidates = sorted(
        DEFAULT_REPORT_DIR.glob("robustness_run_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return next((p for p in candidates if "V3_S0" in p.name), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=str, help="Chemin rapport bench (défaut: dernier V3_S0_*)")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else find_latest_report()
    if not report_path or not report_path.exists():
        print(f"ERREUR : aucun rapport bench trouvé. Lancez CH-40.5 d'abord.")
        return 1

    data = json.loads(report_path.read_text(encoding="utf-8"))
    per_sample = data.get("per_sample", [])
    samples_with_disagreement = [s for s in per_sample if s.get("disagreement")]

    if not samples_with_disagreement:
        print("ERREUR : aucun sample avec disagreement (gold-set v4 absent ou structured_metrics off)")
        return 1

    # Tri par disagreement value desc
    overscored = sorted(
        [s for s in samples_with_disagreement if s["disagreement"]["dominant_signal"] == "judge_overscored"],
        key=lambda s: s["disagreement"]["value"],
        reverse=True,
    )
    underscored = sorted(
        [s for s in samples_with_disagreement if s["disagreement"]["dominant_signal"] == "judge_underscored"],
        key=lambda s: s["disagreement"]["value"],
        reverse=True,
    )
    aligned = [s for s in samples_with_disagreement if s["disagreement"]["dominant_signal"] == "aligned"]

    # Distribution par catégorie
    cat_dist: dict[str, dict[str, int]] = {}
    for s in samples_with_disagreement:
        cat = s.get("category", "unknown")
        sig = s["disagreement"]["dominant_signal"]
        if cat not in cat_dist:
            cat_dist[cat] = {"judge_overscored": 0, "judge_underscored": 0, "aligned": 0}
        cat_dist[cat][sig] += 1

    # Distribution par primary_type
    pt_dist: dict[str, dict[str, int]] = {}
    for s in samples_with_disagreement:
        pt = s.get("primary_type", "unknown") or "unknown"
        sig = s["disagreement"]["dominant_signal"]
        if pt not in pt_dist:
            pt_dist[pt] = {"judge_overscored": 0, "judge_underscored": 0, "aligned": 0}
        pt_dist[pt][sig] += 1

    # Génération markdown
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    judge_model = data.get("judge_model", "?")
    tag = data.get("tag", "")
    md = [
        "# V4 S0 — Analyse désaccords judge vs structured metrics",
        "",
        f"_Généré : {ts}_",
        f"_Source rapport : {report_path.name}_",
        f"_Tag : `{tag}`_",
        f"_Juge : `{judge_model}`_",
        "",
        "## Vue d'ensemble",
        "",
        f"- **Total samples avec disagreement calculé** : {len(samples_with_disagreement)}",
        f"- **judge_overscored** (Claude dit 'bon' mais structured 'mauvais') : {len(overscored)} ({100*len(overscored)/len(samples_with_disagreement):.1f}%)",
        f"- **judge_underscored** (Claude rate ce que structured voit) : {len(underscored)} ({100*len(underscored)/len(samples_with_disagreement):.1f}%)",
        f"- **aligned** : {len(aligned)} ({100*len(aligned)/len(samples_with_disagreement):.1f}%)",
        "",
        "**Interprétation** : un taux élevé de `judge_overscored` indique que le LLM-juge sur-évalue les réponses qui ont l'air structurées/cohérentes mais qui manquent les faits critiques (style over substance). C'est l'angle mort principal de l'overfit Claude-juge identifié dans l'ADR_OSMOSIS_V4_ARCHITECTURE.md.",
        "",
        "---",
        "",
        "## Distribution par primary_type",
        "",
        "| primary_type | overscored | underscored | aligned | overscored % |",
        "|---|---:|---:|---:|---:|",
    ]
    for pt, counts in sorted(pt_dist.items()):
        total = sum(counts.values())
        over_pct = 100 * counts["judge_overscored"] / total if total else 0
        md.append(f"| {pt} | {counts['judge_overscored']} | {counts['judge_underscored']} | {counts['aligned']} | {over_pct:.1f}% |")

    md.extend([
        "",
        "## Distribution par catégorie source",
        "",
        "| catégorie | overscored | underscored | aligned |",
        "|---|---:|---:|---:|",
    ])
    for cat, counts in sorted(cat_dist.items()):
        md.append(f"| {cat} | {counts['judge_overscored']} | {counts['judge_underscored']} | {counts['aligned']} |")

    md.extend([
        "",
        "---",
        "",
        f"## Top-20 judge_overscored (style over substance — STYLE OF JUDGE)",
        "",
        "_Ces cas sont les plus pédagogiques : Claude-juge dit 'bon' mais les structured metrics montrent que les faits critiques manquent. À examiner pour calibrer le bake-off A/B/C (CH-40.4)._",
        "",
    ])
    for i, s in enumerate(overscored[:20], 1):
        d = s["disagreement"]
        sm = s.get("structured_metrics") or {}
        md.append(f"### {i}. {s.get('original_id', s.get('question_id', '?'))} — {s.get('category', '?')} / {s.get('primary_type', '?')}")
        md.append("")
        md.append(f"**Question** : {s.get('question', '')[:200]}")
        md.append("")
        md.append(f"- judge_score = **{d['judge_score']:.2f}** | structured_avg = **{d['structured_avg']:.2f}** | disagreement = **{d['value']:.2f}**")
        if sm.get("item_recall", {}).get("applicable"):
            ir = sm["item_recall"]
            md.append(f"- item_recall : {ir['n_matched']}/{ir['n_expected']} matched (missing : `{ir.get('missing_items')}`)")
        if sm.get("exact_match", {}).get("applicable"):
            em = sm["exact_match"]
            md.append(f"- exact_match : {em['n_matched']}/{em['n_expected']} (missing : `{em.get('missing_ids')}`)")
        if sm.get("citation", {}).get("applicable"):
            ci = sm["citation"]
            md.append(f"- citation_rate : {ci.get('citation_rate')} (unsupported : {ci.get('unsupported_sentences')}/{ci.get('sentences_total')})")
        md.append(f"- judge reason : _{(s.get('evaluation', {}).get('judge_reason') or '?')[:200]}_")
        md.append("")

    md.extend([
        "---",
        "",
        "## Top-20 judge_underscored (Claude trop strict)",
        "",
        "_Ces cas montrent où le judge LLM est plus strict que les structured metrics. Plus rare. Peut signaler que le prompt judge a un critère implicite que le gold-set ne capture pas._",
        "",
    ])
    for i, s in enumerate(underscored[:20], 1):
        d = s["disagreement"]
        md.append(f"### {i}. {s.get('original_id', s.get('question_id', '?'))} — {s.get('category', '?')}")
        md.append(f"- judge_score = **{d['judge_score']:.2f}** | structured_avg = **{d['structured_avg']:.2f}**")
        md.append(f"- judge reason : _{(s.get('evaluation', {}).get('judge_reason') or '?')[:200]}_")
        md.append("")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote disagreement analysis to {args.output}")
    print(f"Top-20 overscored documented (potential style-over-substance bias).")
    print(f"Total : {len(samples_with_disagreement)} samples analyzed, {len(overscored)} overscored ({100*len(overscored)/max(len(samples_with_disagreement),1):.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
