#!/usr/bin/env python3
"""
Archivage des claims isolées dans Neo4j.

Chantier 0 - Phase 1B : Marque les claims sans structured_form,
sans relations structurantes (CHAINS_TO, ABOUT, REFINES, QUALIFIES,
CONTRADICTS) avec archived=true.

Gains : ~2 986 claims exclues du query engine sans perte de données.

Usage:
    # Mode dry-run (par défaut)
    docker-compose exec app python scripts/archive_isolated_claims.py

    # Mode exécution
    docker-compose exec app python scripts/archive_isolated_claims.py --execute

    # Avec tenant spécifique
    docker-compose exec app python scripts/archive_isolated_claims.py --execute --tenant default
"""

import argparse
import os
import sys
from typing import Any, Dict, List

from neo4j import GraphDatabase


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


# Requête d'identification des claims isolées
ISOLATED_CLAIMS_QUERY = """
MATCH (c:Claim {tenant_id: $tid})
WHERE c.structured_form_json IS NULL
  AND NOT EXISTS { (c)-[:CHAINS_TO]->() }
  AND NOT EXISTS { ()-[:CHAINS_TO]->(c) }
  AND NOT EXISTS { (c)-[:ABOUT]->() }
  AND NOT EXISTS { (c)-[:REFINES]->() }
  AND NOT EXISTS { ()-[:REFINES]->(c) }
  AND NOT EXISTS { (c)-[:QUALIFIES]->() }
  AND NOT EXISTS { ()-[:QUALIFIES]->(c) }
  AND NOT EXISTS { (c)-[:CONTRADICTS]->() }
  AND NOT EXISTS { ()-[:CONTRADICTS]->(c) }
RETURN c.claim_id AS claim_id, c.doc_id AS doc_id,
       substring(c.text, 0, 120) AS text_preview
"""


def is_claim_isolated(claim_data: Dict[str, Any]) -> bool:
    """
    Vérifie les critères d'isolation d'une claim (logique pure).

    Une claim est isolée si:
    - structured_form_json est NULL
    - Aucune relation CHAINS_TO (source ou cible)
    - Aucune relation ABOUT
    - Aucune relation REFINES (source ou cible)
    - Aucune relation QUALIFIES (source ou cible)
    - Aucune relation CONTRADICTS (source ou cible)

    Args:
        claim_data: Dict avec les champs de la claim et ses compteurs de relations

    Returns:
        True si la claim est isolée
    """
    if claim_data.get("structured_form_json") is not None:
        return False
    if claim_data.get("chains_to_out", 0) > 0:
        return False
    if claim_data.get("chains_to_in", 0) > 0:
        return False
    if claim_data.get("about_count", 0) > 0:
        return False
    if claim_data.get("refines_out", 0) > 0:
        return False
    if claim_data.get("refines_in", 0) > 0:
        return False
    if claim_data.get("qualifies_out", 0) > 0:
        return False
    if claim_data.get("qualifies_in", 0) > 0:
        return False
    if claim_data.get("contradicts_out", 0) > 0:
        return False
    if claim_data.get("contradicts_in", 0) > 0:
        return False
    return True


def fetch_isolated_claims(driver, tenant_id: str) -> List[Dict[str, Any]]:
    """Récupère les claims isolées depuis Neo4j."""
    with driver.session() as session:
        result = session.run(ISOLATED_CLAIMS_QUERY, tid=tenant_id)
        return [dict(record) for record in result]


def analyze_distribution(claims: List[Dict[str, Any]]) -> Dict[str, int]:
    """Analyse la distribution des claims isolées par doc_id."""
    by_doc: Dict[str, int] = {}
    for claim in claims:
        doc_id = claim.get("doc_id", "unknown")
        by_doc[doc_id] = by_doc.get(doc_id, 0) + 1
    return dict(sorted(by_doc.items(), key=lambda x: -x[1]))


def execute_archive(
    driver,
    claim_ids: List[str],
    tenant_id: str,
    batch_size: int = 500,
) -> Dict[str, int]:
    """
    Archive les claims isolées (SET archived=true).

    Args:
        driver: Neo4j driver
        claim_ids: IDs des claims à archiver
        tenant_id: Tenant ID
        batch_size: Taille des lots

    Returns:
        Stats d'exécution
    """
    stats = {"archived": 0}

    batches = [claim_ids[i:i + batch_size] for i in range(0, len(claim_ids), batch_size)]

    archive_query = """
    UNWIND $ids AS cid
    MATCH (c:Claim {claim_id: cid, tenant_id: $tid})
    SET c.archived = true,
        c.archived_at = datetime(),
        c.archived_reason = 'isolated_claim_phase0'
    RETURN count(c) AS archived
    """

    with driver.session() as session:
        for i, batch in enumerate(batches, 1):
            result = session.run(archive_query, ids=batch, tid=tenant_id)
            record = result.single()
            stats["archived"] += record["archived"] if record else 0
            if i % 10 == 0 or i == len(batches):
                print(f"    Lot {i}/{len(batches)} — {stats['archived']} claims archivées")

    return stats


def verify_archive(driver, tenant_id: str) -> Dict[str, int]:
    """Vérifie qu'aucune claim archivée n'a de relations structurantes."""
    with driver.session() as session:
        # Compter les claims archivées
        result = session.run(
            "MATCH (c:Claim {tenant_id: $tid, archived: true}) RETURN count(c) AS c",
            tid=tenant_id,
        )
        archived_count = result.single()["c"]

        # Vérifier que les archivées n'ont PAS de relations structurantes
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid, archived: true})-[r:CHAINS_TO|ABOUT|REFINES|QUALIFIES|CONTRADICTS]-()
            RETURN count(r) AS c
            """,
            tid=tenant_id,
        )
        relations_on_archived = result.single()["c"]

        return {
            "archived_count": archived_count,
            "relations_on_archived": relations_on_archived,
        }


def print_dry_run_report(
    total_claims: int,
    isolated: List[Dict[str, Any]],
    distribution: Dict[str, int],
):
    """Affiche le rapport dry-run."""
    print("\n" + "=" * 70)
    print("RAPPORT DRY-RUN — Archivage Claims Isolées")
    print("=" * 70)

    print(f"\n--- Résumé ---")
    print(f"  Claims totales         : {total_claims}")
    print(f"  Claims isolées         : {len(isolated)} ({100 * len(isolated) / total_claims:.1f}%)" if total_claims else "  Claims isolées         : 0")

    print(f"\n--- Distribution par document ---")
    for doc_id, count in list(distribution.items())[:10]:
        print(f"    {doc_id}: {count} claims isolées")
    if len(distribution) > 10:
        print(f"    ... et {len(distribution) - 10} autres documents")

    print(f"\n--- Échantillon (5 premiers) ---")
    for claim in isolated[:5]:
        print(f"    [{claim['claim_id'][:20]}...] {claim['text_preview']}")

    print(f"\n--- Opération prévue ---")
    print(f"  SET archived=true sur {len(isolated)} claims")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Archivage des claims isolées (Chantier 0 - Phase 1B)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Exécute réellement l'archivage (sinon dry-run)"
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
        help="Taille des lots (default: 500)"
    )

    args = parser.parse_args()

    print("[OSMOSE] Chantier 0 — Phase 1B : Archivage Claims Isolées")
    print(f"  Mode    : {'EXÉCUTION' if args.execute else 'DRY-RUN'}")
    print(f"  Tenant  : {args.tenant}")

    print("\nConnexion à Neo4j...")
    driver = get_neo4j_driver()

    try:
        # Compter les claims totales
        with driver.session() as session:
            result = session.run(
                "MATCH (c:Claim {tenant_id: $tid}) RETURN count(c) AS c",
                tid=args.tenant,
            )
            total_claims = result.single()["c"]

        # Identifier les claims isolées
        print("Identification des claims isolées...")
        isolated = fetch_isolated_claims(driver, args.tenant)
        print(f"  → {len(isolated)} claims isolées trouvées")

        if not isolated:
            print("\nAucune claim isolée à archiver.")
            return 0

        distribution = analyze_distribution(isolated)

        if args.execute:
            claim_ids = [c["claim_id"] for c in isolated]
            print(f"\nArchivage de {len(claim_ids)} claims...")
            stats = execute_archive(driver, claim_ids, args.tenant, args.batch_size)

            # Vérification
            print("\nVérification...")
            verification = verify_archive(driver, args.tenant)

            print("\n" + "=" * 70)
            print("RAPPORT D'EXÉCUTION — Archivage Claims Isolées")
            print("=" * 70)
            print(f"  Claims archivées       : {stats['archived']}")
            print(f"  Claims archived total  : {verification['archived_count']}")
            print(f"  Relations sur archivées: {verification['relations_on_archived']} (attendu: 0)")
            ok = verification["relations_on_archived"] == 0
            print(f"\n  {'ARCHIVAGE RÉUSSI' if ok else 'ATTENTION — Relations trouvées sur claims archivées!'}")
            print("=" * 70)

        else:
            print_dry_run_report(total_claims, isolated, distribution)
            print("\n  MODE DRY-RUN — Aucune modification effectuée")
            print("    Utilisez --execute pour archiver réellement")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
