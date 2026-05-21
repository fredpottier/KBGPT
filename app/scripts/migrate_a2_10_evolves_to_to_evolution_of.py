"""Migration A2.10 — Renommage :EVOLVES_TO → :EVOLUTION_OF dans le KG.

Cf ADR_RELATIONS_CLAIM_CLAIM §2.2 (harmonisation vocabulaire).

Pour chaque relation `:EVOLVES_TO` existante :
  1. Crée une `:EVOLUTION_OF` avec les mêmes propriétés vers la même cible (MERGE idempotent)
  2. Supprime la `:EVOLVES_TO` originale

Idempotent : run multiple fois sans effet de bord (la première run renomme, les
suivantes ne trouvent plus de :EVOLVES_TO).

Le KG actuel a 0 :EVOLVES_TO (étape #14 c6_pivots pas exécutée), donc le script
est "future-proof" : il sera utile si jamais c6_pivots ancien tourne avant la
recreate Neo4j.

Usage:
    docker exec knowbase-app sh -c 'python /app/scripts/migrate_a2_10_evolves_to_to_evolution_of.py --tenant default [--dry-run]'
"""

from __future__ import annotations

import argparse
import sys
import time

from neo4j import GraphDatabase


def count_evolves_to(driver, tenant_id: str) -> int:
    cypher = """
    MATCH (a:Claim {tenant_id: $tid})-[r:EVOLVES_TO]->(b:Claim {tenant_id: $tid})
    RETURN count(r) AS n
    """
    with driver.session() as session:
        record = session.run(cypher, tid=tenant_id).single()
        return record["n"] if record else 0


def count_evolution_of(driver, tenant_id: str) -> int:
    cypher = """
    MATCH (a:Claim {tenant_id: $tid})-[r:EVOLUTION_OF]->(b:Claim {tenant_id: $tid})
    RETURN count(r) AS n
    """
    with driver.session() as session:
        record = session.run(cypher, tid=tenant_id).single()
        return record["n"] if record else 0


def migrate_evolves_to_to_evolution_of(driver, tenant_id: str, dry_run: bool = False) -> dict:
    """Renomme toutes les :EVOLVES_TO en :EVOLUTION_OF (idempotent)."""
    # Cypher : créer EVOLUTION_OF en copiant les props, puis supprimer EVOLVES_TO
    # Note APOC : si pas disponible, on copie les props manuellement
    if dry_run:
        cypher = """
        MATCH (a:Claim {tenant_id: $tid})-[r:EVOLVES_TO]->(b:Claim {tenant_id: $tid})
        RETURN count(r) AS would_migrate
        """
        with driver.session() as session:
            record = session.run(cypher, tid=tenant_id).single()
            return {"would_migrate": record["would_migrate"] if record else 0}

    # WRITE : 2 étapes pour éviter perte de propriétés
    # Étape 1 : créer EVOLUTION_OF en copiant les props de chaque EVOLVES_TO
    cypher_copy = """
    MATCH (a:Claim {tenant_id: $tid})-[r:EVOLVES_TO]->(b:Claim {tenant_id: $tid})
    MERGE (a)-[new_r:EVOLUTION_OF]->(b)
    ON CREATE SET new_r = properties(r),
                  new_r.migrated_from = 'EVOLVES_TO',
                  new_r.migrated_at = datetime()
    RETURN count(new_r) AS copied
    """
    with driver.session() as session:
        copied_rec = session.run(cypher_copy, tid=tenant_id).single()
        copied = copied_rec["copied"] if copied_rec else 0

    # Étape 2 : supprimer toutes les EVOLVES_TO
    cypher_delete = """
    MATCH (a:Claim {tenant_id: $tid})-[r:EVOLVES_TO]->(b:Claim {tenant_id: $tid})
    DELETE r
    RETURN count(*) AS deleted
    """
    with driver.session() as session:
        deleted_rec = session.run(cypher_delete, tid=tenant_id).single()
        deleted = deleted_rec["deleted"] if deleted_rec else 0

    return {"copied_to_evolution_of": copied, "deleted_evolves_to": deleted}


def main():
    parser = argparse.ArgumentParser(description="Migration A2.10 — renommage EVOLVES_TO → EVOLUTION_OF")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bolt", default="bolt://neo4j:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="graphiti_neo4j_pass")
    args = parser.parse_args()

    print(f"=== Migration A2.10 — tenant={args.tenant} dry_run={args.dry_run} ===")
    driver = GraphDatabase.driver(args.bolt, auth=(args.user, args.password))

    start = time.time()

    print()
    print("▶ État avant migration")
    n_before_evolves = count_evolves_to(driver, args.tenant)
    n_before_evolution = count_evolution_of(driver, args.tenant)
    print(f"    :EVOLVES_TO    : {n_before_evolves}")
    print(f"    :EVOLUTION_OF  : {n_before_evolution}")

    if n_before_evolves == 0:
        print()
        print("✅ Aucune :EVOLVES_TO à migrer — migration no-op.")
        driver.close()
        return 0

    print()
    print(f"▶ {'DRY-RUN' if args.dry_run else 'Migration EVOLVES_TO → EVOLUTION_OF'}")
    res = migrate_evolves_to_to_evolution_of(driver, args.tenant, dry_run=args.dry_run)
    for k, v in res.items():
        print(f"    {k}: {v}")

    if not args.dry_run:
        print()
        print("▶ État après migration")
        n_after_evolves = count_evolves_to(driver, args.tenant)
        n_after_evolution = count_evolution_of(driver, args.tenant)
        print(f"    :EVOLVES_TO    : {n_after_evolves} (attendu 0)")
        print(f"    :EVOLUTION_OF  : {n_after_evolution} (avant: {n_before_evolution}, +{n_after_evolution - n_before_evolution})")

        if n_after_evolves > 0:
            print()
            print(f"⚠️ ATTENTION : il reste {n_after_evolves} :EVOLVES_TO après migration — investiguer")

    duration = time.time() - start
    print()
    print(f"=== Migration terminée en {duration:.1f}s ===")
    print(f"   Mode: {'DRY-RUN (aucune écriture)' if args.dry_run else 'WRITE'}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
