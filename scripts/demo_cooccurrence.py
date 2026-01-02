#!/usr/bin/env python3
"""
Démo: Trouver les concepts qui co-occurent dans le corpus.

Ce script montre la valeur de la Navigation Layer:
- Les concepts qui apparaissent souvent ensemble
- Sans nécessairement avoir de relation sémantique

Usage:
    python scripts/demo_cooccurrence.py
    python scripts/demo_cooccurrence.py --concept "ransomware"
"""

import argparse
import sys
sys.path.insert(0, "/app/src")

from knowbase.config.settings import get_settings
from knowbase.common.clients.neo4j_client import get_neo4j_client


def find_top_cooccurrences(neo4j, limit=15):
    """Trouve les paires de concepts qui apparaissent le plus souvent ensemble."""
    query = """
    MATCH (c1:CanonicalConcept)-[:MENTIONED_IN]->(ctx:ContextNode)<-[:MENTIONED_IN]-(c2:CanonicalConcept)
    WHERE ctx.kind = 'document' AND c1.canonical_name < c2.canonical_name
    WITH c1.canonical_name AS concept1, c2.canonical_name AS concept2, count(DISTINCT ctx) AS docs_shared
    ORDER BY docs_shared DESC
    LIMIT $limit
    RETURN concept1, concept2, docs_shared
    """

    with neo4j.driver.session(database=neo4j.database) as session:
        results = session.run(query, {"limit": limit})
        return [(r["concept1"], r["concept2"], r["docs_shared"]) for r in results]


def find_cooccurrences_for_concept(neo4j, concept_name, limit=10):
    """Trouve les concepts qui co-occurent avec un concept donné."""
    query = """
    MATCH (c1:CanonicalConcept)-[:MENTIONED_IN]->(ctx:ContextNode)<-[:MENTIONED_IN]-(c2:CanonicalConcept)
    WHERE ctx.kind = 'document'
      AND toLower(c1.canonical_name) CONTAINS toLower($concept)
      AND c1.canonical_id <> c2.canonical_id
    WITH c1.canonical_name AS source, c2.canonical_name AS related, count(DISTINCT ctx) AS docs_shared
    ORDER BY docs_shared DESC
    LIMIT $limit
    RETURN source, related, docs_shared
    """

    with neo4j.driver.session(database=neo4j.database) as session:
        results = session.run(query, {"concept": concept_name, "limit": limit})
        return [(r["source"], r["related"], r["docs_shared"]) for r in results]


def check_semantic_relation(neo4j, concept1, concept2):
    """Vérifie s'il existe une relation sémantique entre deux concepts."""
    query = """
    MATCH (c1:CanonicalConcept)-[r]->(c2:CanonicalConcept)
    WHERE toLower(c1.canonical_name) CONTAINS toLower($c1)
      AND toLower(c2.canonical_name) CONTAINS toLower($c2)
      AND NOT type(r) IN ['INSTANCE_OF', 'MERGED_INTO']
    RETURN c1.canonical_name AS from_concept, type(r) AS relation, c2.canonical_name AS to_concept
    LIMIT 5
    """

    with neo4j.driver.session(database=neo4j.database) as session:
        results = session.run(query, {"c1": concept1, "c2": concept2})
        return [(r["from_concept"], r["relation"], r["to_concept"]) for r in results]


def main():
    parser = argparse.ArgumentParser(description="Démo Navigation Layer - Co-occurrences")
    parser.add_argument("--concept", "-c", help="Chercher co-occurrences pour ce concept")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Nombre de résultats")
    args = parser.parse_args()

    settings = get_settings()
    neo4j = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    if args.concept:
        print(f"\n=== Concepts qui co-occurent avec '{args.concept}' ===\n")
        results = find_cooccurrences_for_concept(neo4j, args.concept, args.limit)

        if not results:
            print(f"Aucun résultat pour '{args.concept}'")
            return

        for source, related, docs in results:
            # Vérifier s'il y a une relation sémantique
            sem_rels = check_semantic_relation(neo4j, source, related)
            sem_indicator = " [SEM]" if sem_rels else ""
            print(f"  {docs:2d} docs: {related}{sem_indicator}")

        print("\n[SEM] = relation sémantique existante")
        print("Sans [SEM] = seulement co-occurrence (Navigation Layer)")

    else:
        print("\n=== Top paires de concepts co-occurents ===\n")
        results = find_top_cooccurrences(neo4j, args.limit)

        for c1, c2, docs in results:
            print(f"  {docs:2d} docs: {c1} <-> {c2}")

    print()


if __name__ == "__main__":
    main()
