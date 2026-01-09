#!/usr/bin/env python3
"""
Script d'analyse des anchor_status dans Neo4j.

Permet de mesurer la distribution des statuts d'ancrage:
- SPAN: Ancrage réussi
- FUZZY_FAILED: Score < seuil (70%)
- NO_MATCH: Aucune correspondance
- EMPTY_QUOTE: Quote vide

Usage:
    docker-compose exec app python scripts/analyze_anchor_status.py
"""

import logging
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def get_neo4j_client():
    """Obtient le client Neo4j."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client()


def analyze_anchor_status() -> Dict:
    """Analyse la distribution des anchor_status dans le KG."""
    client = get_neo4j_client()

    # Statistiques globales par anchor_status
    global_query = """
    MATCH (pc:ProtoConcept)
    RETURN
        pc.anchor_status AS status,
        count(pc) AS count,
        avg(pc.fuzzy_best_score) AS avg_score,
        min(pc.fuzzy_best_score) AS min_score,
        max(pc.fuzzy_best_score) AS max_score
    ORDER BY count DESC
    """

    # Statistiques par document
    doc_query = """
    MATCH (pc:ProtoConcept)-[:EXTRACTED_FROM]->(d:Document)
    RETURN
        d.name AS doc_name,
        pc.anchor_status AS status,
        count(pc) AS count
    ORDER BY d.name, pc.anchor_status
    """

    # Distribution des scores pour FUZZY_FAILED
    score_distribution_query = """
    MATCH (pc:ProtoConcept)
    WHERE pc.anchor_status = 'FUZZY_FAILED'
    WITH
        CASE
            WHEN pc.fuzzy_best_score < 30 THEN '0-29'
            WHEN pc.fuzzy_best_score < 50 THEN '30-49'
            WHEN pc.fuzzy_best_score < 60 THEN '50-59'
            WHEN pc.fuzzy_best_score < 65 THEN '60-64'
            WHEN pc.fuzzy_best_score < 70 THEN '65-69'
            ELSE '70+'
        END AS score_range,
        pc
    RETURN score_range, count(pc) AS count
    ORDER BY score_range
    """

    # Top failure reasons
    failure_reasons_query = """
    MATCH (pc:ProtoConcept)
    WHERE pc.anchor_status <> 'SPAN' AND pc.anchor_failure_reason IS NOT NULL
    RETURN pc.anchor_failure_reason AS reason, count(pc) AS count
    ORDER BY count DESC
    LIMIT 10
    """

    stats = {
        "global": [],
        "by_document": {},
        "score_distribution": [],
        "failure_reasons": []
    }

    with client.driver.session(database="neo4j") as session:
        # Global stats
        result = session.run(global_query)
        for record in result:
            stats["global"].append({
                "status": record["status"] or "NULL",
                "count": record["count"],
                "avg_score": round(record["avg_score"] or 0, 1),
                "min_score": round(record["min_score"] or 0, 1),
                "max_score": round(record["max_score"] or 0, 1)
            })

        # By document
        result = session.run(doc_query)
        for record in result:
            doc_name = record["doc_name"]
            if doc_name not in stats["by_document"]:
                stats["by_document"][doc_name] = {}
            stats["by_document"][doc_name][record["status"] or "NULL"] = record["count"]

        # Score distribution for FUZZY_FAILED
        result = session.run(score_distribution_query)
        for record in result:
            stats["score_distribution"].append({
                "range": record["score_range"],
                "count": record["count"]
            })

        # Failure reasons
        result = session.run(failure_reasons_query)
        for record in result:
            stats["failure_reasons"].append({
                "reason": record["reason"],
                "count": record["count"]
            })

    return stats


def print_report(stats: Dict):
    """Affiche le rapport d'analyse."""
    logger.info("=" * 70)
    logger.info("ANALYSE DES ANCHOR_STATUS - ProtoConcepts")
    logger.info("=" * 70)

    # Stats globales
    logger.info("\n## Distribution Globale\n")
    total = sum(s["count"] for s in stats["global"])
    for s in stats["global"]:
        pct = 100 * s["count"] / total if total > 0 else 0
        logger.info(
            f"  {s['status']:15} : {s['count']:5} ({pct:5.1f}%) "
            f"[score: avg={s['avg_score']}, min={s['min_score']}, max={s['max_score']}]"
        )
    logger.info(f"\n  TOTAL: {total}")

    # Distribution des scores FUZZY_FAILED
    if stats["score_distribution"]:
        logger.info("\n## Distribution des Scores FUZZY_FAILED\n")
        logger.info("  (Utile pour décider si baisser le seuil de 70%)")
        for s in stats["score_distribution"]:
            logger.info(f"  {s['range']:10} : {s['count']:5}")

    # Failure reasons
    if stats["failure_reasons"]:
        logger.info("\n## Top Raisons d'Échec\n")
        for r in stats["failure_reasons"]:
            logger.info(f"  {r['reason']:30} : {r['count']:5}")

    # Par document
    logger.info("\n## Breakdown par Document\n")
    logger.info(f"  {'Document':<45} | {'SPAN':>5} | {'FUZZY':>5} | {'NO_Q':>5} | {'NO_M':>5} | {'%SPAN':>6}")
    logger.info("-" * 95)
    for doc_name, statuses in sorted(stats["by_document"].items()):
        span = statuses.get("SPAN", 0)
        fuzzy = statuses.get("FUZZY_FAILED", 0)
        no_quote = statuses.get("NO_QUOTE", 0)
        no_match = statuses.get("NO_MATCH", 0)
        total_doc = span + fuzzy + no_quote + no_match
        pct = 100 * span / total_doc if total_doc > 0 else 0
        doc_short = doc_name[:43] + ".." if len(doc_name) > 45 else doc_name
        logger.info(f"  {doc_short:<45} | {span:>5} | {fuzzy:>5} | {no_quote:>5} | {no_match:>5} | {pct:>5.1f}%")

    logger.info("\n" + "=" * 70)


def main():
    stats = analyze_anchor_status()
    print_report(stats)


if __name__ == "__main__":
    main()
