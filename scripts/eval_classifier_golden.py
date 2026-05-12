#!/usr/bin/env python3
"""
S3.F.3 — Évaluation classifier sur le golden set annoté.

Lit les nodes :GoldenPair annotés (g.human_label != null) et compare
avec g.predicted_type. Calcule :
- Précision globale (% labels predicted == human)
- Précision par type (matrice confusion)
- Précision spécifique CONFLICT (critère plan §S3.F : ≥ 80%)
- False positive rate par type

human_label peut être :
- même type que predicted_type → correct
- autre type V3.3 → faux (mauvaise classification)
- "REJECTED" → la paire ne devrait pas exister (faux positif total)

Usage :
    docker exec knowbase-app python /tmp/eval_classifier_golden.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CONFLICT_PRECISION_TARGET = 0.80


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"golden_set_eval_{ts}.md"
    summary_path = OUTPUT_DIR / f"golden_set_eval_{ts}.json"

    logger.info("=" * 70)
    logger.info("S3.F.3 — Évaluation classifier sur golden set")
    logger.info("=" * 70)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        with driver.session() as s:
            # Toutes les GoldenPair (annotées ou non)
            all_pairs = s.run("""
                MATCH (g:GoldenPair {tenant_id: $tid})
                RETURN
                  g.golden_id AS gid,
                  g.predicted_type AS predicted,
                  g.predicted_confidence AS confidence,
                  g.predicted_is_contradiction AS predicted_is_contra,
                  g.human_label AS human,
                  g.human_notes AS notes,
                  g.annotated_at AS annotated_at
            """, tid=TENANT_ID).data()

        annotated = [p for p in all_pairs if p["human"] is not None]
        unannotated = [p for p in all_pairs if p["human"] is None]

        logger.info(f"Total golden pairs : {len(all_pairs)}")
        logger.info(f"Annotated : {len(annotated)}")
        logger.info(f"Unannotated : {len(unannotated)}")

        if not annotated:
            logger.warning("⚠ Aucune paire annotée. Annoter via /admin/relations/golden-set d'abord.")
            return 1

        # === Précision globale ===
        correct = sum(1 for p in annotated if p["human"] == p["predicted"])
        rejected = sum(1 for p in annotated if p["human"] == "REJECTED")
        wrong_type = sum(1 for p in annotated if p["human"] not in (p["predicted"], "REJECTED"))

        precision = correct / len(annotated) if annotated else 0
        rejection_rate = rejected / len(annotated) if annotated else 0

        logger.info(f"\n=== Précision globale ===")
        logger.info(f"  Correct (predicted == human) : {correct}/{len(annotated)} ({precision*100:.1f}%)")
        logger.info(f"  Rejected (faux positif total) : {rejected}/{len(annotated)} ({rejection_rate*100:.1f}%)")
        logger.info(f"  Wrong type (autre type V3.3) : {wrong_type}/{len(annotated)}")

        # === Précision par type ===
        by_type = defaultdict(lambda: {"total": 0, "correct": 0, "rejected": 0, "wrong_type": 0})
        for p in annotated:
            t = p["predicted"]
            by_type[t]["total"] += 1
            if p["human"] == t:
                by_type[t]["correct"] += 1
            elif p["human"] == "REJECTED":
                by_type[t]["rejected"] += 1
            else:
                by_type[t]["wrong_type"] += 1

        logger.info(f"\n=== Précision par type prédit ===")
        type_stats = []
        for t in sorted(by_type.keys()):
            s_t = by_type[t]
            prec = s_t["correct"] / s_t["total"] if s_t["total"] else 0
            type_stats.append({"type": t, "total": s_t["total"], "correct": s_t["correct"],
                               "rejected": s_t["rejected"], "wrong": s_t["wrong_type"],
                               "precision": prec})
            logger.info(f"  {t:15s} : {s_t['correct']}/{s_t['total']} = {prec*100:.0f}% (rejected {s_t['rejected']}, wrong {s_t['wrong_type']})")

        # === CONFLICT precision (critère bloquant) ===
        conflict_stats = by_type.get("CONFLICT", {"total": 0, "correct": 0})
        conflict_precision = conflict_stats["correct"] / conflict_stats["total"] if conflict_stats["total"] else 0
        conflict_pass = conflict_precision >= CONFLICT_PRECISION_TARGET

        logger.info(f"\n=== Critère bloquant : CONFLICT précision ===")
        logger.info(f"  CONFLICT : {conflict_stats['correct']}/{conflict_stats['total']} = {conflict_precision*100:.1f}%")
        logger.info(f"  Cible plan : ≥ {CONFLICT_PRECISION_TARGET*100:.0f}%")
        logger.info(f"  Verdict : {'✅ ATTEINTE — cleanup legacy autorisé' if conflict_pass else '❌ EN DESSOUS — itérer sur prompt avant cleanup'}")

        # === Confusion matrix ===
        logger.info(f"\n=== Matrice de confusion (predicted → human) ===")
        confusion: dict[str, Counter] = defaultdict(Counter)
        for p in annotated:
            confusion[p["predicted"]][p["human"]] += 1

        # === Output reports ===
        summary = {
            "timestamp": ts,
            "tenant_id": TENANT_ID,
            "total_pairs": len(all_pairs),
            "annotated": len(annotated),
            "unannotated": len(unannotated),
            "global_precision": precision,
            "global_correct": correct,
            "global_rejected": rejected,
            "global_wrong_type": wrong_type,
            "by_type": type_stats,
            "conflict_precision": conflict_precision,
            "conflict_target": CONFLICT_PRECISION_TARGET,
            "conflict_pass": conflict_pass,
            "confusion_matrix": {p: dict(h) for p, h in confusion.items()},
        }
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        md = [
            f"# S3.F.3 — Golden set evaluation ({ts})",
            "",
            f"**Total pairs** : {len(all_pairs)} (annotated {len(annotated)}, unannotated {len(unannotated)})",
            "",
            "## Précision globale",
            "",
            f"- Correct : **{correct}/{len(annotated)} ({precision*100:.1f}%)**",
            f"- Rejected (faux positif total) : {rejected}/{len(annotated)} ({rejection_rate*100:.1f}%)",
            f"- Wrong type (mauvaise classification) : {wrong_type}/{len(annotated)}",
            "",
            "## Précision par type prédit",
            "",
            "| Type prédit | Total | Correct | Rejected | Wrong type | Précision |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for ts_ in type_stats:
            md.append(f"| {ts_['type']} | {ts_['total']} | {ts_['correct']} | {ts_['rejected']} | {ts_['wrong']} | {ts_['precision']*100:.0f}% |")
        md.append("")
        md.append("## Critère bloquant : CONFLICT")
        md.append("")
        md.append(f"- CONFLICT précision : **{conflict_stats['correct']}/{conflict_stats['total']} = {conflict_precision*100:.1f}%**")
        md.append(f"- Cible plan : ≥ {CONFLICT_PRECISION_TARGET*100:.0f}%")
        md.append(f"- Verdict : {'✅ Atteinte — cleanup legacy autorisé' if conflict_pass else '❌ En dessous — itérer sur prompt avant cleanup'}")
        md.append("")
        md.append("## Matrice de confusion")
        md.append("")
        md.append("| Predicted ↓ \\ Human → | " + " | ".join(sorted({p["human"] for p in annotated})) + " |")
        md.append("|" + "---|" * (len({p["human"] for p in annotated}) + 1))
        for p_type in sorted(confusion.keys()):
            row = [p_type]
            for h_label in sorted({p["human"] for p in annotated}):
                row.append(str(confusion[p_type].get(h_label, 0)))
            md.append("| " + " | ".join(row) + " |")
        md.append("")

        report_path.write_text("\n".join(md), encoding="utf-8")
        logger.info(f"\n✅ Report : {report_path}")

        if conflict_pass:
            logger.info(f"\n🟢 Cleanup legacy autorisé. Lancer : scripts/delete_legacy_relations.py --confirm")
            return 0
        else:
            logger.info(f"\n🔴 Cleanup BLOQUÉ. Itérer sur prompt classifier puis re-classify avant cleanup.")
            return 2

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
