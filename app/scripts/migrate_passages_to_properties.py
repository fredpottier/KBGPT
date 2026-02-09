#!/usr/bin/env python3
"""
Migration des Passages → propriétés sur les Claims.

Chantier 0 - Phase 1A : Copie passage.text, section_title, page_no,
char_start, char_end sur chaque Claim liée, puis supprime les Passage nodes
et les edges SUPPORTED_BY / FROM.

Gains : -6 220 nodes, -17 179 edges (~40% du graphe).

Usage:
    # Mode dry-run (par défaut) - rapport sans modification
    docker-compose exec app python scripts/migrate_passages_to_properties.py

    # Mode exécution - migre réellement
    docker-compose exec app python scripts/migrate_passages_to_properties.py --execute

    # Avec tenant spécifique
    docker-compose exec app python scripts/migrate_passages_to_properties.py --execute --tenant default
"""

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

from neo4j import GraphDatabase


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def count_current_state(driver, tenant_id: str) -> Dict[str, int]:
    """Compte l'état actuel des Passages, SUPPORTED_BY et FROM."""
    counts = {}

    with driver.session() as session:
        queries = {
            "passages": f"MATCH (p:Passage {{tenant_id: '{tenant_id}'}}) RETURN count(p) AS c",
            "supported_by": "MATCH ()-[r:SUPPORTED_BY]->() RETURN count(r) AS c",
            "from_edges": f"MATCH (p:Passage {{tenant_id: '{tenant_id}'}})-[r:FROM]->() RETURN count(r) AS c",
            "claims_total": f"MATCH (c:Claim {{tenant_id: '{tenant_id}'}}) RETURN count(c) AS c",
            "claims_with_passage_text": f"MATCH (c:Claim {{tenant_id: '{tenant_id}'}}) WHERE c.passage_text IS NOT NULL RETURN count(c) AS c",
        }

        for key, query in queries.items():
            result = session.run(query)
            record = result.single()
            counts[key] = record["c"] if record else 0

    return counts


def fetch_passage_claim_pairs(
    driver, tenant_id: str
) -> List[Dict[str, Any]]:
    """
    Charge toutes les paires (Passage, Claim) avec les données à copier.

    Returns:
        Liste de dicts avec les données de chaque paire.
    """
    query = """
    MATCH (p:Passage {tenant_id: $tid})<-[:SUPPORTED_BY]-(c:Claim)
    RETURN p.passage_id AS passage_id,
           p.text AS passage_text,
           p.section_title AS section_title,
           p.page_no AS page_no,
           p.char_start AS char_start,
           p.char_end AS char_end,
           c.claim_id AS claim_id
    """

    pairs = []
    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        for record in result:
            pairs.append({
                "passage_id": record["passage_id"],
                "passage_text": record["passage_text"],
                "section_title": record["section_title"],
                "page_no": record["page_no"],
                "char_start": record["char_start"],
                "char_end": record["char_end"],
                "claim_id": record["claim_id"],
            })

    return pairs


def build_batches(pairs: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
    """Découpe les paires en lots de taille batch_size."""
    return [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]


def analyze_sharing(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyse la distribution 1:1 vs 1:N des passages."""
    passage_to_claims: Dict[str, List[str]] = {}
    for pair in pairs:
        pid = pair["passage_id"]
        if pid not in passage_to_claims:
            passage_to_claims[pid] = []
        passage_to_claims[pid].append(pair["claim_id"])

    unique_passages = len(passage_to_claims)
    shared = {pid: cids for pid, cids in passage_to_claims.items() if len(cids) > 1}
    exclusive = unique_passages - len(shared)

    distribution = {}
    for pid, cids in passage_to_claims.items():
        count = len(cids)
        if count not in distribution:
            distribution[count] = 0
        distribution[count] += 1

    return {
        "unique_passages": unique_passages,
        "exclusive_1_to_1": exclusive,
        "shared_1_to_n": len(shared),
        "shared_percentage": round(100 * len(shared) / unique_passages, 1) if unique_passages else 0,
        "total_claim_assignments": len(pairs),
        "distribution": dict(sorted(distribution.items())),
    }


def execute_migration(
    driver,
    pairs: List[Dict[str, Any]],
    tenant_id: str,
    batch_size: int,
) -> Dict[str, int]:
    """
    Exécute la migration :
    1. SET passage_text etc. sur chaque Claim (par batch)
    2. Vérifie que toutes les claims ont reçu les données
    3. Supprime edges SUPPORTED_BY
    4. Supprime edges FROM (Passage→Document)
    5. Supprime nodes Passage
    """
    stats = {
        "claims_enriched": 0,
        "supported_by_deleted": 0,
        "from_deleted": 0,
        "passages_deleted": 0,
    }

    batches = build_batches(pairs, batch_size)

    # Étape 1: Enrichir les Claims avec les données des Passages
    print(f"\n  Étape 1/4 : Enrichissement des Claims ({len(pairs)} paires en {len(batches)} lots)...")

    enrich_query = """
    UNWIND $batch AS row
    MATCH (c:Claim {claim_id: row.claim_id})
    SET c.passage_text = row.passage_text,
        c.section_title = row.section_title,
        c.page_no = row.page_no,
        c.passage_char_start = row.char_start,
        c.passage_char_end = row.char_end
    RETURN count(c) AS enriched
    """

    with driver.session() as session:
        for i, batch in enumerate(batches, 1):
            result = session.run(enrich_query, batch=batch)
            record = result.single()
            enriched = record["enriched"] if record else 0
            stats["claims_enriched"] += enriched
            if i % 10 == 0 or i == len(batches):
                print(f"    Lot {i}/{len(batches)} — {stats['claims_enriched']} claims enrichies")

    # Étape 2: Vérification
    print("\n  Étape 2/4 : Vérification...")
    with driver.session() as session:
        check_query = f"""
        MATCH (c:Claim {{tenant_id: '{tenant_id}'}})<-[:SUPPORTED_BY]-(p:Passage)
        WHERE c.passage_text IS NULL
        RETURN count(c) AS missing
        """
        # Note : On inverse — on cherche les claims qui sont encore liées
        # MAIS n'ont pas reçu passage_text
        # Correction: la relation est Claim -[:SUPPORTED_BY]-> Passage
        check_query = """
        MATCH (c:Claim {tenant_id: $tid})-[:SUPPORTED_BY]->(p:Passage)
        WHERE c.passage_text IS NULL
        RETURN count(c) AS missing
        """
        result = session.run(check_query, tid=tenant_id)
        record = result.single()
        missing = record["missing"] if record else 0
        if missing > 0:
            print(f"    ATTENTION : {missing} claims liées n'ont pas reçu passage_text!")
            print("    Abandon de la suppression des passages.")
            return stats
        print(f"    OK — toutes les claims liées ont été enrichies")

    # Étape 3: Supprimer SUPPORTED_BY
    print("\n  Étape 3/4 : Suppression des edges SUPPORTED_BY et FROM...")
    with driver.session() as session:
        # SUPPORTED_BY
        result = session.run(
            "MATCH (:Claim {tenant_id: $tid})-[r:SUPPORTED_BY]->(:Passage) DELETE r RETURN count(r) AS c",
            tid=tenant_id,
        )
        record = result.single()
        stats["supported_by_deleted"] = record["c"] if record else 0
        print(f"    {stats['supported_by_deleted']} edges SUPPORTED_BY supprimés")

        # FROM
        result = session.run(
            "MATCH (p:Passage {tenant_id: $tid})-[r:FROM]->() DELETE r RETURN count(r) AS c",
            tid=tenant_id,
        )
        record = result.single()
        stats["from_deleted"] = record["c"] if record else 0
        print(f"    {stats['from_deleted']} edges FROM supprimés")

    # Étape 4: Supprimer les Passage nodes
    print("\n  Étape 4/4 : Suppression des nodes Passage...")
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Passage {tenant_id: $tid}) DELETE p RETURN count(p) AS c",
            tid=tenant_id,
        )
        record = result.single()
        stats["passages_deleted"] = record["c"] if record else 0
        print(f"    {stats['passages_deleted']} nodes Passage supprimés")

    return stats


def print_dry_run_report(
    counts: Dict[str, int],
    pairs: List[Dict[str, Any]],
    sharing: Dict[str, Any],
):
    """Affiche le rapport dry-run."""
    print("\n" + "=" * 70)
    print("RAPPORT DRY-RUN — Migration Passages → Propriétés Claims")
    print("=" * 70)

    print(f"\n--- État actuel ---")
    print(f"  Passages               : {counts['passages']}")
    print(f"  Edges SUPPORTED_BY     : {counts['supported_by']}")
    print(f"  Edges FROM             : {counts['from_edges']}")
    print(f"  Claims total           : {counts['claims_total']}")
    print(f"  Claims déjà enrichies  : {counts['claims_with_passage_text']}")

    print(f"\n--- Paires Passage↔Claim chargées ---")
    print(f"  Total paires           : {len(pairs)}")
    print(f"  Passages uniques       : {sharing['unique_passages']}")
    print(f"  Passages exclusifs 1:1 : {sharing['exclusive_1_to_1']}")
    print(f"  Passages partagés 1:N  : {sharing['shared_1_to_n']} ({sharing['shared_percentage']}%)")

    print(f"\n--- Distribution claims par passage ---")
    for claim_count, passage_count in sharing["distribution"].items():
        print(f"    {claim_count} claim(s) → {passage_count} passage(s)")

    print(f"\n--- Opérations prévues ---")
    print(f"  Claims à enrichir      : {len(pairs)}")
    print(f"  Edges à supprimer      : ~{counts['supported_by'] + counts['from_edges']}")
    print(f"  Nodes à supprimer      : {counts['passages']}")

    gains_nodes = counts["passages"]
    gains_edges = counts["supported_by"] + counts["from_edges"]
    print(f"\n--- Gains estimés ---")
    print(f"  Nodes éliminés         : -{gains_nodes}")
    print(f"  Edges éliminés         : -{gains_edges}")

    print("\n" + "=" * 70)


def print_execution_report(
    counts_before: Dict[str, int],
    stats: Dict[str, int],
    counts_after: Dict[str, int],
):
    """Affiche le rapport après exécution."""
    print("\n" + "=" * 70)
    print("RAPPORT D'EXÉCUTION — Migration Passages → Propriétés Claims")
    print("=" * 70)

    print(f"\n--- Opérations effectuées ---")
    print(f"  Claims enrichies       : {stats['claims_enriched']}")
    print(f"  SUPPORTED_BY supprimés : {stats['supported_by_deleted']}")
    print(f"  FROM supprimés         : {stats['from_deleted']}")
    print(f"  Passages supprimés     : {stats['passages_deleted']}")

    print(f"\n--- Vérification finale ---")
    print(f"  Passages restants      : {counts_after['passages']} (attendu: 0)")
    print(f"  SUPPORTED_BY restants  : {counts_after['supported_by']} (attendu: 0)")
    print(f"  FROM restants          : {counts_after['from_edges']} (attendu: 0)")
    print(f"  Claims avec passage_text : {counts_after['claims_with_passage_text']}")

    ok = (
        counts_after["passages"] == 0
        and counts_after["supported_by"] == 0
        and counts_after["from_edges"] == 0
    )
    print(f"\n  {'MIGRATION RÉUSSIE' if ok else 'ATTENTION — Vérifier les résidus'}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Migration Passages → propriétés Claims (Chantier 0 - Phase 1A)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Exécute réellement la migration (sinon dry-run)"
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant ID (default: 'default')"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Taille des lots pour le batch SET (default: 500)"
    )

    args = parser.parse_args()

    print("[OSMOSE] Chantier 0 — Phase 1A : Migration Passages → Propriétés Claims")
    print(f"  Mode    : {'EXÉCUTION' if args.execute else 'DRY-RUN'}")
    print(f"  Tenant  : {args.tenant}")
    print(f"  Batch   : {args.batch_size}")

    print("\nConnexion à Neo4j...")
    driver = get_neo4j_driver()

    try:
        # 1. État actuel
        print("Comptage de l'état actuel...")
        counts = count_current_state(driver, args.tenant)

        if counts["passages"] == 0:
            print("\nAucun Passage trouvé — migration déjà effectuée ou rien à migrer.")
            return 0

        # 2. Charger les paires
        print("Chargement des paires Passage↔Claim...")
        pairs = fetch_passage_claim_pairs(driver, args.tenant)
        print(f"  → {len(pairs)} paires chargées")

        if not pairs:
            print("\nAucune paire trouvée — les Passages ne sont liés à aucune Claim.")
            return 0

        # 3. Analyser la distribution
        sharing = analyze_sharing(pairs)

        if args.execute:
            # Rapport pré-exécution succinct
            print(f"\n  {len(pairs)} paires à migrer, {sharing['shared_1_to_n']} passages partagés")

            # Exécuter
            stats = execute_migration(driver, pairs, args.tenant, args.batch_size)

            # Vérification finale
            print("\nVérification finale...")
            counts_after = count_current_state(driver, args.tenant)
            print_execution_report(counts, stats, counts_after)

        else:
            print_dry_run_report(counts, pairs, sharing)
            print("\n  MODE DRY-RUN — Aucune modification effectuée")
            print("    Utilisez --execute pour migrer réellement")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
