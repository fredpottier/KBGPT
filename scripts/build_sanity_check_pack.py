#!/usr/bin/env python3
"""
CH-40.7 — Sanity check externe Fred (10 questions).

Sélectionne 10 questions diversifiées du gold-set v4, prend les réponses du dernier
bench Robustness V3_S0_*, génère un fichier markdown interactif que Fred remplit
avec un verdict ternaire (OK | KO | bizarre) par question.

But : éviter la dérive "Claude juge + Claude reviewer". Si > 2/10 cas où Fred
détecte du judge-overscoring que Claude-juge n'a pas vu → déclenche bake-off
A/B/C (CH-40.4) même si Pearson global OK.

Stratification : 2 factual + 2 list + 2 temporal + 2 causal + 1 comparison + 1 false_premise,
mix FR/EN.

Usage :
  python scripts/build_sanity_check_pack.py [--report PATH]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "app" / "data" / "benchmark" / "results"
OUTPUT_PATH = PROJECT_ROOT / "doc" / "ongoing" / "V4_S0_SANITY_CHECK.md"

RANDOM_SEED = 20260505_1  # different seed than gold-set construction


def find_latest_report() -> Path | None:
    candidates = sorted(
        DEFAULT_REPORT_DIR.glob("robustness_run_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return next((p for p in candidates if "V3_S0" in p.name), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=str, help="Chemin rapport bench Robustness")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else find_latest_report()
    if not report_path or not report_path.exists():
        print("ERREUR : aucun rapport bench V3_S0_* trouvé. Lancez CH-40.5 d'abord.")
        return 1

    if not GOLD_SET_PATH.exists():
        print(f"ERREUR : gold-set v4 manquant ({GOLD_SET_PATH})")
        return 1

    gold_items = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    gold_by_source = {it["source_id"]: it for it in gold_items if it.get("source_id")}

    report = json.loads(report_path.read_text(encoding="utf-8"))
    samples = report.get("per_sample", [])
    samples_by_oid = {s.get("original_id"): s for s in samples if s.get("original_id")}

    # Stratification
    rng = random.Random(RANDOM_SEED)
    quota = {
        "factual": 2,
        "list": 2,
        "temporal": 2,
        "causal": 2,
        "comparison": 1,
        "false_premise": 1,
    }
    by_type = {pt: [] for pt in quota}
    for it in gold_items:
        pt = it.get("primary_type")
        if pt in by_type and it["source_id"] in samples_by_oid:
            by_type[pt].append(it)
    for arr in by_type.values():
        rng.shuffle(arr)

    selected = []
    for pt, n in quota.items():
        selected.extend(by_type[pt][:n])

    # Mix FR/EN target : si possible inclure ≥ 2 EN (T1 a 6 EN)
    fr_count = sum(1 for it in selected if it.get("language") == "fr")
    en_count = sum(1 for it in selected if it.get("language") == "en")
    if en_count < 2:
        # Try to swap one factual FR for factual EN
        en_factual = [it for it in by_type["factual"] if it.get("language") == "en"]
        for swap in en_factual:
            if swap not in selected:
                # remove last FR factual
                for i, s in enumerate(selected):
                    if s.get("primary_type") == "factual" and s.get("language") == "fr":
                        selected[i] = swap
                        en_count += 1
                        fr_count -= 1
                        break
                if en_count >= 2:
                    break

    if len(selected) < 10:
        print(f"WARNING : seulement {len(selected)} questions sélectionnées (gold-set/bench partiel)")

    # Génération markdown interactif
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = [
        "# V4 S0 — Sanity Check Externe Fred",
        "",
        f"_Généré : {ts}_",
        f"_Source rapport : {report_path.name}_",
        f"_Sélection : {len(selected)} questions stratifiées (FR={fr_count}, EN={en_count})_",
        "",
        "## Instructions",
        "",
        "Pour chaque question, vous voyez :",
        "- La question (FR ou EN)",
        "- La réponse V3 OSMOSIS",
        "- Le score du LLM-judge (Llama-3.3-70B)",
        "- Le score structured metrics (item_recall + exact_match + citation)",
        "- Les éventuels gaps détectés",
        "",
        "**Émettez un verdict ternaire pour chacune** :",
        "- ✅ **OK** : la réponse est correcte / acceptable pour un compliance officer",
        "- ❌ **KO** : la réponse contient une erreur factuelle, identifiant inversé, valeur fausse",
        "- ⚠️ **bizarre** : ni clairement OK ni KO — formulation suspecte, partial, instruction-following bug",
        "",
        "**Après la review, comptez** :",
        "- Si > 2/10 cas où Claude-juge dit OK (score ≥ 0.7) mais vous dites KO → **judge-overscoring grave**",
        "- → déclenche bake-off CH-40.4 même si Pearson global OK",
        "",
        "Compléter en éditant la ligne `**Verdict** : ___` à la fin de chaque question.",
        "",
        "---",
        "",
    ]

    for i, gold in enumerate(selected, 1):
        sample = samples_by_oid.get(gold["source_id"], {})
        ev = sample.get("evaluation", {})
        sm = sample.get("structured_metrics") or {}

        judge_score = ev.get("score")
        struct_avg = sm.get("structured_avg")

        md.append(f"## Question {i} — {gold['source_id']} ({gold.get('primary_type')} / {gold.get('language')})")
        md.append("")
        md.append(f"**Question** : {gold.get('question', '')}")
        md.append("")
        md.append(f"**Réponse V3** :")
        md.append("")
        md.append(f"> {(sample.get('answer') or '_(pas de réponse)_').replace(chr(10), ' ')[:1200]}")
        md.append("")
        md.append(f"**Scores** :")
        md.append(f"- LLM-judge : `{judge_score}` ({ev.get('judge_reason') or '?'})")
        md.append(f"- structured_avg : `{struct_avg}`")
        if sm.get("exact_match", {}).get("applicable"):
            em = sm["exact_match"]
            md.append(f"- exact_match : {em['n_matched']}/{em['n_expected']} (missing : `{em.get('missing_ids')}`)")
        if sm.get("item_recall", {}).get("applicable"):
            ir = sm["item_recall"]
            md.append(f"- item_recall : {ir['n_matched']}/{ir['n_expected']} (missing : `{ir.get('missing_items')}`)")
        md.append("")
        gt = gold.get("ground_truth", {})
        md.append(f"**Référence** : {(gt.get('ground_truth_answer') or '?')[:300]}")
        md.append(f"**Identifiants attendus** : `{gt.get('exact_identifiers')}`")
        md.append("")
        md.append("**Verdict** : `___` (OK | KO | bizarre)  ")
        md.append("**Note libre** : ___")
        md.append("")
        md.append("---")
        md.append("")

    md.extend([
        "## Synthèse à compléter",
        "",
        "À remplir une fois les 10 verdicts émis :",
        "",
        "| Métrique | Valeur |",
        "|---|---|",
        "| Total OK | ___ |",
        "| Total KO | ___ |",
        "| Total bizarre | ___ |",
        "| **Cas judge-overscoring grave** (Claude judge ≥ 0.7 mais Fred dit KO) | ___ |",
        "",
        "**Si judge-overscoring grave > 2/10** :",
        "- [ ] Déclencher bake-off A/B/C (CH-40.4) : `python scripts/judge_bakeoff.py`",
        "- [ ] Documenter dans ADR un addendum sur les patterns d'overscoring observés",
        "",
        "**Si judge-overscoring grave ≤ 2/10** :",
        "- [ ] Sprint S0 gate validé sur le critère sanity check",
        "- [ ] Continuer S1 (Verifier upgrade)",
    ])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote sanity check pack to {args.output}")
    print(f"Selection : {len(selected)} questions (FR={fr_count}, EN={en_count})")
    print(f"À remplir par Fred (~30 min). Verdict ternaire OK/KO/bizarre par question.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
