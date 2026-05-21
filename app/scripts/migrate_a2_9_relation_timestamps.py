"""Migration A2.9 — Backfill timestamps sur relations cross-claim existantes.

Cf ADR_RELATIONS_CLAIM_CLAIM §3.2.

Pour chaque relation cross-claim sans `detected_at` :
  - set `detected_at = coalesce(r.created_at, a.ingested_at, datetime())`
  - calcule `valid_from_relation` selon symétrique (max) vs directionnelle (B.valid_from)
  - set `marker_type = coalesce(r.marker_type, 'inferred')`

Cascade `invalidated_relation_at` sur les relations attachées à des claims déjà invalidés.

Idempotent : run multiple fois sans effet de bord.

Usage:
    docker exec knowbase-app python /app/scripts/migrate_a2_9_relation_timestamps.py --tenant default [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from neo4j import GraphDatabase


# Relations symétriques (A ↔ B) — valid_from_relation = max
SYMMETRIC_RELATIONS = ["SAME_AS", "CONTRADICTS"]
# Relations directionnelles (B → A) — valid_from_relation = source (c1)
DIRECTIONAL_RELATIONS = [
    "EVOLUTION_OF",
    "SUPERSEDES",
    "REFINES",
    "QUALIFIES",
    "COMPLEMENTS",
    "SPECIALIZES",
    "EVOLVES_TO",
    "CHAINS_TO",
]


# ---------------------------------------------------------------------------
# Backfill detected_at + marker_type (toutes relations)
# ---------------------------------------------------------------------------


def backfill_detected_at_and_marker(driver, tenant_id: str, dry_run: bool = False) -> dict:
    """Pour toutes relations cross-claim, set detected_at + marker_type si NULL."""
    all_rels = SYMMETRIC_RELATIONS + DIRECTIONAL_RELATIONS
    rel_union = "|".join(all_rels)

    if dry_run:
        cypher = f"""
        MATCH (a:Claim)-[r:{rel_union}]-(b:Claim)
        WHERE a.tenant_id = $tid AND b.tenant_id = $tid
          AND (r.detected_at IS NULL OR r.marker_type IS NULL)
        RETURN count(r) AS would_update, type(r) AS rel_type
        ORDER BY rel_type
        """
    else:
        cypher = f"""
        MATCH (a:Claim)-[r:{rel_union}]-(b:Claim)
        WHERE a.tenant_id = $tid AND b.tenant_id = $tid
          AND (r.detected_at IS NULL OR r.marker_type IS NULL)
        SET r.detected_at = coalesce(r.detected_at, r.created_at, a.ingested_at, datetime()),
            r.marker_type = coalesce(r.marker_type, 'inferred')
        RETURN count(r) AS updated
        """
    with driver.session() as session:
        if dry_run:
            results = list(session.run(cypher, tid=tenant_id))
            return {row["rel_type"]: row["would_update"] for row in results if row.get("would_update")}
        else:
            record = session.run(cypher, tid=tenant_id).single()
            return {"updated": record["updated"] if record else 0}


# ---------------------------------------------------------------------------
# Backfill valid_from_relation (symétrique = max, directionnelle = source)
# ---------------------------------------------------------------------------


def backfill_valid_from_relation_symmetric(driver, tenant_id: str, dry_run: bool = False) -> dict:
    """Symétriques : valid_from_relation = max(a.valid_from, b.valid_from), NULL si l'un NULL.

    NB : Cypher Neo4j ne distingue pas la direction sur (a)-[r]-(b), mais comme c'est
    symétrique, peu importe.
    """
    counts: dict[str, int] = {}
    for rel in SYMMETRIC_RELATIONS:
        if dry_run:
            cypher = f"""
            MATCH (a:Claim)-[r:{rel}]-(b:Claim)
            WHERE a.tenant_id = $tid AND b.tenant_id = $tid
              AND r.valid_from_relation IS NULL
              AND a.valid_from IS NOT NULL AND b.valid_from IS NOT NULL
            RETURN count(DISTINCT r) AS would_update
            """
        else:
            cypher = f"""
            MATCH (a:Claim)-[r:{rel}]-(b:Claim)
            WHERE a.tenant_id = $tid AND b.tenant_id = $tid
              AND r.valid_from_relation IS NULL
              AND a.valid_from IS NOT NULL AND b.valid_from IS NOT NULL
            WITH DISTINCT r, a.valid_from AS af, b.valid_from AS bf
            SET r.valid_from_relation = CASE WHEN af > bf THEN af ELSE bf END
            RETURN count(r) AS updated
            """
        with driver.session() as session:
            record = session.run(cypher, tid=tenant_id).single()
            counts[rel] = record["would_update" if dry_run else "updated"] if record else 0
    return counts


def backfill_valid_from_relation_directional(driver, tenant_id: str, dry_run: bool = False) -> dict:
    """Directionnelles : valid_from_relation = source (c1).valid_from.

    Note : (c1)-[r]->(c2), c1 est le source/winner, on prend c1.valid_from.
    """
    counts: dict[str, int] = {}
    for rel in DIRECTIONAL_RELATIONS:
        if dry_run:
            cypher = f"""
            MATCH (c1:Claim)-[r:{rel}]->(c2:Claim)
            WHERE c1.tenant_id = $tid AND c2.tenant_id = $tid
              AND r.valid_from_relation IS NULL
              AND c1.valid_from IS NOT NULL
            RETURN count(r) AS would_update
            """
        else:
            cypher = f"""
            MATCH (c1:Claim)-[r:{rel}]->(c2:Claim)
            WHERE c1.tenant_id = $tid AND c2.tenant_id = $tid
              AND r.valid_from_relation IS NULL
              AND c1.valid_from IS NOT NULL
            SET r.valid_from_relation = c1.valid_from
            RETURN count(r) AS updated
            """
        with driver.session() as session:
            record = session.run(cypher, tid=tenant_id).single()
            counts[rel] = record["would_update" if dry_run else "updated"] if record else 0
    return counts


# ---------------------------------------------------------------------------
# Cascade invalidated_relation_at (claims déjà invalidés)
# ---------------------------------------------------------------------------


def cascade_invalidated_relation_at(driver, tenant_id: str, dry_run: bool = False) -> dict:
    """Pour chaque claim invalidé, propage invalidated_at sur ses relations cross-claim."""
    all_rels = SYMMETRIC_RELATIONS + DIRECTIONAL_RELATIONS
    rel_union = "|".join(all_rels)

    if dry_run:
        cypher = f"""
        MATCH (a:Claim)-[r:{rel_union}]-(b:Claim)
        WHERE a.tenant_id = $tid AND b.tenant_id = $tid
          AND (a.invalidated_at IS NOT NULL OR b.invalidated_at IS NOT NULL)
          AND r.invalidated_relation_at IS NULL
        RETURN count(DISTINCT r) AS would_cascade
        """
    else:
        cypher = f"""
        MATCH (a:Claim)-[r:{rel_union}]-(b:Claim)
        WHERE a.tenant_id = $tid AND b.tenant_id = $tid
          AND (a.invalidated_at IS NOT NULL OR b.invalidated_at IS NOT NULL)
          AND r.invalidated_relation_at IS NULL
        SET r.invalidated_relation_at = coalesce(a.invalidated_at, b.invalidated_at)
        RETURN count(DISTINCT r) AS cascaded
        """
    with driver.session() as session:
        record = session.run(cypher, tid=tenant_id).single()
        return {"would_cascade" if dry_run else "cascaded": record[0] if record else 0}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Migration A2.9 — backfill timestamps sur relations cross-claim")
    parser.add_argument("--tenant", default="default", help="Tenant ID (défaut: default)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche le nombre de relations qui seraient mises à jour, sans écrire")
    parser.add_argument("--bolt", default="bolt://neo4j:7687", help="URL Bolt Neo4j")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="graphiti_neo4j_pass")
    args = parser.parse_args()

    print(f"=== Migration A2.9 — tenant={args.tenant} dry_run={args.dry_run} ===")
    print(f"  Bolt: {args.bolt}")

    driver = GraphDatabase.driver(args.bolt, auth=(args.user, args.password))

    start = time.time()

    print()
    print("▶ Étape 1 — Backfill detected_at + marker_type (toutes relations)")
    res1 = backfill_detected_at_and_marker(driver, args.tenant, dry_run=args.dry_run)
    for k, v in res1.items():
        print(f"    {k}: {v}")

    print()
    print("▶ Étape 2 — Backfill valid_from_relation symétriques (max)")
    res2 = backfill_valid_from_relation_symmetric(driver, args.tenant, dry_run=args.dry_run)
    for k, v in res2.items():
        print(f"    {k}: {v}")

    print()
    print("▶ Étape 3 — Backfill valid_from_relation directionnelles (source)")
    res3 = backfill_valid_from_relation_directional(driver, args.tenant, dry_run=args.dry_run)
    for k, v in res3.items():
        print(f"    {k}: {v}")

    print()
    print("▶ Étape 4 — Cascade invalidated_relation_at (claims déjà invalidés)")
    res4 = cascade_invalidated_relation_at(driver, args.tenant, dry_run=args.dry_run)
    for k, v in res4.items():
        print(f"    {k}: {v}")

    duration = time.time() - start
    print()
    print(f"=== Migration terminée en {duration:.1f}s ===")
    print(f"   Mode: {'DRY-RUN (aucune écriture)' if args.dry_run else 'WRITE'}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
