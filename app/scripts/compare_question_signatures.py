#!/usr/bin/env python3
"""
Comparaison cross-doc des QuestionSignatures.

Charge les QS depuis Neo4j, trouve les paires comparables,
classifie les différences (évolution, contradiction, convergence, accord).

Usage:
    docker exec knowbase-app python scripts/compare_question_signatures.py
    docker exec knowbase-app python scripts/compare_question_signatures.py --min-confidence 0.7 --output /tmp/qs_comparisons.json
"""

import argparse
import json
import logging
import sys
from collections import Counter

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] qs_compare")


def main(
    tenant_id: str = "default",
    min_confidence: float = 0.5,
    output_file: str = None,
):
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.models.question_signature import QuestionSignature
    from knowbase.claimfirst.comparisons.qs_comparator import (
        ComparisonType,
        compare_all,
    )

    client = get_neo4j_client()

    # Charger les QS avec dimension_id
    with client.driver.session(database=client.database) as session:
        result = session.run("""
            MATCH (qs:QuestionSignature {tenant_id: $tenant_id})
            WHERE qs.dimension_id IS NOT NULL
            RETURN properties(qs) AS props
        """, tenant_id=tenant_id)
        records = [dict(r) for r in result]

    signatures = []
    for rec in records:
        props = rec.get("props", {})
        if props:
            try:
                signatures.append(QuestionSignature.from_neo4j_record(props))
            except Exception as e:
                logger.warning("Erreur désérialisation QS: %s", e)

    logger.info("QS chargées: %d", len(signatures))

    if len(signatures) < 2:
        logger.info("Pas assez de QS pour comparer. Fin.")
        return

    # Comparer
    results = compare_all(signatures)

    # Filtrer par confiance
    results = [r for r in results if r.confidence >= min_confidence]
    logger.info("Résultats après filtre confiance >= %.2f: %d", min_confidence, len(results))

    # Rapport
    type_counts = Counter(r.comparison_type.value for r in results)
    logger.info("=" * 60)
    logger.info("RAPPORT COMPARAISON CROSS-DOC")
    logger.info("=" * 60)
    logger.info("QS total: %d", len(signatures))
    logger.info("Comparaisons: %d", len(results))
    for ct, count in type_counts.most_common():
        logger.info("  %s: %d", ct, count)

    # Détails par type
    for comp_type in [ComparisonType.CONTRADICTION, ComparisonType.EVOLUTION,
                      ComparisonType.CONVERGENCE, ComparisonType.AGREEMENT]:
        typed = [r for r in results if r.comparison_type == comp_type]
        if typed:
            logger.info("\n── %s (%d) ──", comp_type.value, len(typed))
            for r in typed[:10]:
                logger.info(
                    "  [%.0f%%] %s: %s → %s | scope: %s | docs: %s vs %s",
                    r.confidence * 100,
                    r.dimension_key,
                    r.value_diff.value_a if r.value_diff else "?",
                    r.value_diff.value_b if r.value_diff else "?",
                    r.scope_a_label or "?",
                    r.qs_a_doc_id[:20],
                    r.qs_b_doc_id[:20],
                )

    # Export JSON
    if output_file:
        output = [r.to_dict() for r in results]
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        logger.info("\nExport: %s (%d résultats)", output_file, len(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Comparaison cross-doc QS")
    parser.add_argument("--tenant-id", type=str, default="default")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--output", type=str, default=None, help="Fichier JSON de sortie")
    args = parser.parse_args()

    main(
        tenant_id=args.tenant_id,
        min_confidence=args.min_confidence,
        output_file=args.output,
    )
