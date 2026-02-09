#!/usr/bin/env python3
"""
Réparation de l'intégrité des ClaimClusters dans Neo4j.

Chantier 0 - Phase 2 : Synchronise les compteurs, supprime les clusters
vides, et identifie les mega-clusters.

Usage:
    # Mode dry-run (par défaut) — rapport sans modification
    docker-compose exec app python scripts/fix_cluster_integrity.py

    # Mode exécution — corrige l'intégrité
    docker-compose exec app python scripts/fix_cluster_integrity.py --execute

    # Avec splitting des mega-clusters (optionnel, après analyse)
    docker-compose exec app python scripts/fix_cluster_integrity.py --execute --split --split-threshold 20
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


def diagnose_integrity(driver, tenant_id: str) -> Dict[str, Any]:
    """
    Diagnostic complet de l'intégrité des clusters.

    Returns:
        Dict avec les problèmes identifiés
    """
    diagnosis = {
        "total_clusters": 0,
        "claim_count_mismatches": 0,
        "doc_count_mismatches": 0,
        "empty_clusters": 0,
        "mega_clusters": [],
        "details_mismatches": [],
    }

    with driver.session() as session:
        # Total clusters
        result = session.run(
            "MATCH (cc:ClaimCluster {tenant_id: $tid}) RETURN count(cc) AS c",
            tid=tenant_id,
        )
        diagnosis["total_clusters"] = result.single()["c"]

        # Clusters avec claim_count incorrect
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            OPTIONAL MATCH (c:Claim)-[:IN_CLUSTER]->(cc)
            WITH cc, count(c) AS actual_count
            WHERE cc.claim_count IS NULL OR cc.claim_count <> actual_count
            RETURN cc.cluster_id AS cluster_id,
                   cc.canonical_label AS label,
                   cc.claim_count AS stored_count,
                   actual_count
            ORDER BY actual_count DESC
            """,
            tid=tenant_id,
        )
        for record in result:
            diagnosis["claim_count_mismatches"] += 1
            diagnosis["details_mismatches"].append({
                "cluster_id": record["cluster_id"],
                "label": record["label"],
                "stored_count": record["stored_count"],
                "actual_count": record["actual_count"],
            })

        # Clusters avec doc_count incorrect
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            OPTIONAL MATCH (c:Claim)-[:IN_CLUSTER]->(cc)
            WITH cc, collect(DISTINCT c.doc_id) AS actual_docs
            WHERE cc.doc_count IS NULL OR cc.doc_count <> size(actual_docs)
            RETURN count(cc) AS c
            """,
            tid=tenant_id,
        )
        diagnosis["doc_count_mismatches"] = result.single()["c"]

        # Clusters vides
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            WHERE NOT EXISTS { (:Claim)-[:IN_CLUSTER]->(cc) }
            RETURN count(cc) AS c
            """,
            tid=tenant_id,
        )
        diagnosis["empty_clusters"] = result.single()["c"]

        # Mega-clusters (>20 claims)
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            OPTIONAL MATCH (c:Claim)-[:IN_CLUSTER]->(cc)
            WITH cc, count(c) AS cnt, collect(substring(c.text, 0, 80)) AS samples
            WHERE cnt > 20
            RETURN cc.cluster_id AS cluster_id,
                   cc.canonical_label AS label,
                   cnt AS claim_count,
                   samples[0..3] AS sample_texts
            ORDER BY cnt DESC
            """,
            tid=tenant_id,
        )
        for record in result:
            diagnosis["mega_clusters"].append({
                "cluster_id": record["cluster_id"],
                "label": record["label"],
                "claim_count": record["claim_count"],
                "sample_texts": record["sample_texts"],
            })

    return diagnosis


def fix_claim_counts(driver, tenant_id: str) -> int:
    """
    Étape 1 : Synchronise claim_count et claim_ids.

    Returns:
        Nombre de clusters corrigés
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            OPTIONAL MATCH (c:Claim)-[:IN_CLUSTER]->(cc)
            WITH cc, count(c) AS actual, collect(c.claim_id) AS actual_ids
            WHERE cc.claim_count IS NULL OR cc.claim_count <> actual
            SET cc.claim_count = actual, cc.claim_ids = actual_ids
            RETURN count(cc) AS fixed
            """,
            tid=tenant_id,
        )
        return result.single()["fixed"]


def fix_doc_counts(driver, tenant_id: str) -> int:
    """
    Étape 2 : Synchronise doc_ids et doc_count.

    Returns:
        Nombre de clusters corrigés
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            OPTIONAL MATCH (c:Claim)-[:IN_CLUSTER]->(cc)
            WITH cc, collect(DISTINCT c.doc_id) AS actual_docs
            WHERE cc.doc_count IS NULL OR cc.doc_count <> size(actual_docs)
            SET cc.doc_ids = actual_docs, cc.doc_count = size(actual_docs)
            RETURN count(cc) AS fixed
            """,
            tid=tenant_id,
        )
        return result.single()["fixed"]


def delete_empty_clusters(driver, tenant_id: str) -> int:
    """
    Étape 3 : Supprime les clusters vides.

    Returns:
        Nombre de clusters supprimés
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (cc:ClaimCluster {tenant_id: $tid})
            WHERE NOT EXISTS { (:Claim)-[:IN_CLUSTER]->(cc) }
            DELETE cc
            RETURN count(cc) AS deleted
            """,
            tid=tenant_id,
        )
        return result.single()["deleted"]


def print_diagnosis(diagnosis: Dict[str, Any]):
    """Affiche le rapport de diagnostic."""
    print("\n" + "=" * 70)
    print("DIAGNOSTIC INTÉGRITÉ — ClaimClusters")
    print("=" * 70)

    print(f"\n--- Résumé ---")
    print(f"  Clusters total             : {diagnosis['total_clusters']}")
    print(f"  claim_count incorrects     : {diagnosis['claim_count_mismatches']}")
    print(f"  doc_count incorrects       : {diagnosis['doc_count_mismatches']}")
    print(f"  Clusters vides             : {diagnosis['empty_clusters']}")
    print(f"  Mega-clusters (>20 claims) : {len(diagnosis['mega_clusters'])}")

    if diagnosis["details_mismatches"]:
        print(f"\n--- Détails claim_count incorrects (10 premiers) ---")
        for d in diagnosis["details_mismatches"][:10]:
            print(f"    [{d['cluster_id'][:20]}...] "
                  f"\"{d['label']}\" : stocké={d['stored_count']} réel={d['actual_count']}")

    if diagnosis["mega_clusters"]:
        print(f"\n--- Mega-clusters ---")
        for mc in diagnosis["mega_clusters"]:
            print(f"    [{mc['cluster_id'][:20]}...] "
                  f"\"{mc['label']}\" : {mc['claim_count']} claims")
            for sample in mc["sample_texts"][:2]:
                print(f"      → {sample}...")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Réparation intégrité ClaimClusters (Chantier 0 - Phase 2)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Exécute les corrections (sinon dry-run/diagnostic)"
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant ID (default: 'default')"
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="Active le splitting des mega-clusters (après analyse du rapport)"
    )
    parser.add_argument(
        "--split-threshold",
        type=int,
        default=20,
        help="Seuil pour qualifier un mega-cluster (default: 20)"
    )

    args = parser.parse_args()

    print("[OSMOSE] Chantier 0 — Phase 2 : Intégrité ClaimClusters")
    print(f"  Mode    : {'EXÉCUTION' if args.execute else 'DRY-RUN / DIAGNOSTIC'}")
    print(f"  Tenant  : {args.tenant}")

    print("\nConnexion à Neo4j...")
    driver = get_neo4j_driver()

    try:
        # Diagnostic
        print("Diagnostic en cours...")
        diagnosis = diagnose_integrity(driver, args.tenant)
        print_diagnosis(diagnosis)

        has_problems = (
            diagnosis["claim_count_mismatches"] > 0
            or diagnosis["doc_count_mismatches"] > 0
            or diagnosis["empty_clusters"] > 0
        )

        if not has_problems and not diagnosis["mega_clusters"]:
            print("\nAucun problème d'intégrité détecté.")
            return 0

        if args.execute:
            print("\n--- Corrections ---")

            # Étape 1: claim_count
            print("  Étape 1/3 : Synchronisation claim_count...")
            fixed_claims = fix_claim_counts(driver, args.tenant)
            print(f"    → {fixed_claims} clusters corrigés")

            # Étape 2: doc_count
            print("  Étape 2/3 : Synchronisation doc_count...")
            fixed_docs = fix_doc_counts(driver, args.tenant)
            print(f"    → {fixed_docs} clusters corrigés")

            # Étape 3: clusters vides
            print("  Étape 3/3 : Suppression clusters vides...")
            deleted = delete_empty_clusters(driver, args.tenant)
            print(f"    → {deleted} clusters supprimés")

            # Split optionnel
            if args.split and diagnosis["mega_clusters"]:
                print(f"\n  Splitting des mega-clusters (seuil: {args.split_threshold})...")
                print("    NOTE: Le splitting nécessite le ClaimClusterer et les embeddings.")
                print("    Cette fonctionnalité sera disponible dans une version ultérieure.")
                print("    Les mega-clusters restent identifiés dans le rapport ci-dessus.")

            # Vérification post-correction
            print("\nVérification post-correction...")
            post = diagnose_integrity(driver, args.tenant)

            print("\n" + "=" * 70)
            print("RAPPORT D'EXÉCUTION — Intégrité ClaimClusters")
            print("=" * 70)
            print(f"  claim_count corrigés   : {fixed_claims}")
            print(f"  doc_count corrigés     : {fixed_docs}")
            print(f"  Clusters vides supprimés : {deleted}")
            print(f"\n  Problèmes restants:")
            print(f"    claim_count incorrects : {post['claim_count_mismatches']} (attendu: 0)")
            print(f"    doc_count incorrects   : {post['doc_count_mismatches']} (attendu: 0)")
            print(f"    Clusters vides         : {post['empty_clusters']} (attendu: 0)")
            print(f"    Mega-clusters          : {len(post['mega_clusters'])}")

            ok = (
                post["claim_count_mismatches"] == 0
                and post["doc_count_mismatches"] == 0
                and post["empty_clusters"] == 0
            )
            print(f"\n  {'INTÉGRITÉ CORRIGÉE' if ok else 'ATTENTION — Problèmes résiduels'}")
            print("=" * 70)

        else:
            print("\n  MODE DRY-RUN / DIAGNOSTIC — Aucune modification effectuée")
            print("    Utilisez --execute pour corriger l'intégrité")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
