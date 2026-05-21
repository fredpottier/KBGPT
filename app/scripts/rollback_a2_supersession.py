"""Rollback A2.13 — Purge :SUPERSEDES + :ConflictPending + reset invalidated_at.

Permet de re-jouer detect_contradictions avec un nouveau prompt LLM sans bias des
résultats précédents. Idempotent.

Effets :
  - DELETE toutes les relations :SUPERSEDES (et leurs props)
  - DELETE tous les nodes :ConflictPending (+ :INVOLVES)
  - SET claims.invalidated_at = NULL (uniquement si invalidated_by setté = ceux issus de A2.8)
  - SET claims.valid_until = NULL (idem condition)
  - SET claims.invalidated_by = NULL
  - SET claims.invalidation_reason = NULL

NE PURGE PAS les :CONTRADICTS / :REFINES / :QUALIFIES — c'est intentionnel pour le
benchmark : on garde les anciennes décisions pour comparer avec les nouvelles.

Si --purge-contradicts est passé, on purge aussi les :CONTRADICTS pour permettre une
relance propre de detect_contradictions.

Usage:
    docker exec knowbase-app sh -c 'python /app/scripts/rollback_a2_supersession.py --tenant default [--dry-run] [--purge-contradicts]'
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from neo4j import GraphDatabase


def count_state(driver, tenant_id: str) -> dict:
    """Compte les nodes/relations clés."""
    with driver.session() as session:
        r = session.run(
            "MATCH ()-[r:SUPERSEDES]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid RETURN count(r) AS n",
            tid=tenant_id,
        ).single()
        sup = r["n"] if r else 0

        r = session.run("MATCH (cp:ConflictPending {tenant_id: $tid}) RETURN count(cp) AS n", tid=tenant_id).single()
        cp = r["n"] if r else 0

        r = session.run(
            "MATCH (c:Claim {tenant_id: $tid}) WHERE c.invalidated_at IS NOT NULL RETURN count(c) AS n",
            tid=tenant_id,
        ).single()
        inv = r["n"] if r else 0

        r = session.run(
            "MATCH ()-[r:CONTRADICTS]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid RETURN count(r) AS n",
            tid=tenant_id,
        ).single()
        contr = r["n"] if r else 0

    return {"supersedes": sup, "conflict_pending": cp, "claims_invalidated": inv, "contradicts": contr}


def rollback(driver, tenant_id: str, dry_run: bool = False, purge_contradicts: bool = False) -> dict:
    """Exécute le rollback."""
    results = {}

    # 1. SUPERSEDES
    if dry_run:
        cypher = """
        MATCH ()-[r:SUPERSEDES]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid
        RETURN count(r) AS would_delete
        """
        with driver.session() as session:
            results["supersedes_to_delete"] = session.run(cypher, tid=tenant_id).single()["would_delete"]
    else:
        cypher = """
        MATCH ()-[r:SUPERSEDES]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid
        WITH r, count(r) AS _
        DELETE r
        """
        with driver.session() as session:
            session.run(cypher, tid=tenant_id)
            results["supersedes_deleted"] = "OK"

    # 2. ConflictPending nodes (+ :INVOLVES)
    if dry_run:
        cypher = "MATCH (cp:ConflictPending {tenant_id: $tid}) RETURN count(cp) AS would_delete"
        with driver.session() as session:
            results["conflict_pending_to_delete"] = session.run(cypher, tid=tenant_id).single()["would_delete"]
    else:
        cypher = """
        MATCH (cp:ConflictPending {tenant_id: $tid})
        DETACH DELETE cp
        """
        with driver.session() as session:
            session.run(cypher, tid=tenant_id)
            results["conflict_pending_deleted"] = "OK"

    # 3. Reset invalidated_at sur claims (uniquement ceux invalidés par A2.8 = ont invalidated_by setté)
    if dry_run:
        cypher = """
        MATCH (c:Claim {tenant_id: $tid})
        WHERE c.invalidated_at IS NOT NULL AND c.invalidated_by IS NOT NULL
        RETURN count(c) AS would_reset
        """
        with driver.session() as session:
            results["claims_to_reset"] = session.run(cypher, tid=tenant_id).single()["would_reset"]
    else:
        cypher = """
        MATCH (c:Claim {tenant_id: $tid})
        WHERE c.invalidated_at IS NOT NULL AND c.invalidated_by IS NOT NULL
        SET c.invalidated_at = NULL,
            c.valid_until = NULL,
            c.invalidated_by = NULL,
            c.invalidation_reason = NULL
        """
        with driver.session() as session:
            session.run(cypher, tid=tenant_id)
            results["claims_reset"] = "OK"

    # 4. Optional : purge CONTRADICTS pour relance propre
    if purge_contradicts:
        if dry_run:
            cypher = """
            MATCH ()-[r:CONTRADICTS]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid
            RETURN count(r) AS would_delete
            """
            with driver.session() as session:
                results["contradicts_to_delete"] = session.run(cypher, tid=tenant_id).single()["would_delete"]
        else:
            cypher = """
            MATCH ()-[r:CONTRADICTS]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid
            DELETE r
            """
            with driver.session() as session:
                session.run(cypher, tid=tenant_id)
                results["contradicts_deleted"] = "OK"

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-contradicts", action="store_true", help="Purge aussi les :CONTRADICTS (relance propre detect_contradictions)")
    parser.add_argument("--bolt", default="bolt://neo4j:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="graphiti_neo4j_pass")
    args = parser.parse_args()

    print(f"=== Rollback A2.13 — tenant={args.tenant} dry_run={args.dry_run} purge_contradicts={args.purge_contradicts} ===")
    driver = GraphDatabase.driver(args.bolt, auth=(args.user, args.password))

    start = time.time()

    print()
    print("▶ État AVANT :")
    before = count_state(driver, args.tenant)
    for k, v in before.items():
        print(f"    {k:<25}: {v}")

    print()
    print(f"▶ {'DRY-RUN' if args.dry_run else 'Rollback EN COURS...'}")
    res = rollback(driver, args.tenant, dry_run=args.dry_run, purge_contradicts=args.purge_contradicts)
    for k, v in res.items():
        print(f"    {k}: {v}")

    if not args.dry_run:
        print()
        print("▶ État APRÈS :")
        after = count_state(driver, args.tenant)
        for k, v in after.items():
            delta = v - before.get(k, 0)
            sign = "+" if delta >= 0 else ""
            print(f"    {k:<25}: {v} ({sign}{delta})")

    duration = time.time() - start
    print()
    print(f"=== Rollback terminé en {duration:.1f}s ===")
    print(f"   Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
