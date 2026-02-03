#!/usr/bin/env python3
"""
Script de nettoyage des entités garbage dans Neo4j.

Utilise la nouvelle validation is_valid_entity_name() pour identifier
et supprimer les entités invalides (déictiques, fragments de phrase, etc.).

Usage:
    # Mode dry-run (par défaut) - montre ce qui serait supprimé
    docker-compose exec app python scripts/cleanup_garbage_entities.py

    # Mode exécution - supprime réellement
    docker-compose exec app python scripts/cleanup_garbage_entities.py --execute

    # Avec limite
    docker-compose exec app python scripts/cleanup_garbage_entities.py --execute --limit 100
"""

import argparse
import sys
from typing import List, Tuple

import os

from neo4j import GraphDatabase

from knowbase.claimfirst.models.entity import is_valid_entity_name


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def fetch_all_entities(driver, tenant_id: str = "default") -> List[Tuple[str, str]]:
    """
    Récupère toutes les entités de Neo4j.

    Returns:
        Liste de tuples (entity_id, name)
    """
    query = """
    MATCH (e:Entity {tenant_id: $tenant_id})
    RETURN e.entity_id AS entity_id, e.name AS name
    ORDER BY e.name
    """

    with driver.session() as session:
        result = session.run(query, tenant_id=tenant_id)
        return [(record["entity_id"], record["name"]) for record in result]


def identify_garbage_entities(entities: List[Tuple[str, str]]) -> List[Tuple[str, str, str]]:
    """
    Identifie les entités qui ne passent pas la validation.

    Returns:
        Liste de tuples (entity_id, name, reason)
    """
    garbage = []

    for entity_id, name in entities:
        if not is_valid_entity_name(name):
            # Déterminer la raison du rejet
            reason = _get_rejection_reason(name)
            garbage.append((entity_id, name, reason))

    return garbage


def _get_rejection_reason(name: str) -> str:
    """Détermine pourquoi une entité est rejetée."""
    from knowbase.claimfirst.models.entity import (
        Entity,
        ENTITY_STOPLIST,
        PHRASE_FRAGMENT_INDICATORS,
    )
    import re

    if not name:
        return "empty"

    name_stripped = name.strip()
    normalized = Entity.normalize(name)

    # Trop court
    if len(normalized) < 3 and not re.match(r"^[A-Z]{2,5}$", name_stripped):
        return "too_short"

    # Trop long
    if len(normalized) > 80:
        return "too_long"

    # Dans la stoplist
    if normalized in ENTITY_STOPLIST:
        return "stoplist"

    # Commence par un déictique
    first_word = normalized.split()[0] if normalized.split() else ""
    if first_word in {"this", "that", "these", "those", "the", "a", "an",
                      "ce", "cette", "ces", "cet", "le", "la", "les", "un", "une"}:
        return "deictic_prefix"

    # Contient des indicateurs de fragment
    words = set(normalized.lower().split())
    if words & PHRASE_FRAGMENT_INDICATORS:
        return "phrase_fragment"

    # Trop de mots
    if len(normalized.split()) > 8:
        return "too_many_words"

    return "unknown"


def delete_entities(driver, entity_ids: List[str], tenant_id: str = "default") -> int:
    """
    Supprime les entités spécifiées de Neo4j.

    Returns:
        Nombre d'entités supprimées
    """
    # Supprime les entités et leurs relations ABOUT
    query = """
    UNWIND $entity_ids AS eid
    MATCH (e:Entity {entity_id: eid, tenant_id: $tenant_id})
    DETACH DELETE e
    RETURN count(*) AS deleted
    """

    with driver.session() as session:
        result = session.run(query, entity_ids=entity_ids, tenant_id=tenant_id)
        record = result.single()
        return record["deleted"] if record else 0


def print_report(garbage: List[Tuple[str, str, str]], total: int):
    """Affiche un rapport des entités garbage."""
    print("\n" + "=" * 70)
    print("RAPPORT D'ANALYSE DES ENTITÉS GARBAGE")
    print("=" * 70)

    print(f"\nTotal entités analysées: {total}")
    print(f"Entités garbage identifiées: {len(garbage)} ({100*len(garbage)/total:.1f}%)")

    # Grouper par raison
    by_reason = {}
    for entity_id, name, reason in garbage:
        if reason not in by_reason:
            by_reason[reason] = []
        by_reason[reason].append((entity_id, name))

    print("\n--- Répartition par type de problème ---")
    for reason, entities in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        print(f"\n{reason.upper()} ({len(entities)} entités):")
        # Afficher quelques exemples
        for entity_id, name in entities[:5]:
            print(f"  • \"{name}\"")
        if len(entities) > 5:
            print(f"  ... et {len(entities) - 5} autres")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Nettoie les entités garbage dans Neo4j"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Exécute réellement la suppression (sinon dry-run)"
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant ID (default: 'default')"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre de suppressions"
    )

    args = parser.parse_args()

    print("Connexion à Neo4j...")
    driver = get_neo4j_driver()

    try:
        print(f"Récupération des entités (tenant: {args.tenant})...")
        entities = fetch_all_entities(driver, args.tenant)
        print(f"  → {len(entities)} entités trouvées")

        print("Identification des entités garbage...")
        garbage = identify_garbage_entities(entities)

        # Afficher le rapport
        print_report(garbage, len(entities))

        if not garbage:
            print("\nAucune entité garbage à supprimer.")
            return 0

        if args.execute:
            # Appliquer la limite si spécifiée
            to_delete = garbage[:args.limit] if args.limit else garbage
            entity_ids = [eid for eid, _, _ in to_delete]

            print(f"\nSuppression de {len(entity_ids)} entités...")
            deleted = delete_entities(driver, entity_ids, args.tenant)
            print(f"  → {deleted} entités supprimées avec succès")

            if args.limit and len(garbage) > args.limit:
                print(f"\nNote: {len(garbage) - args.limit} entités restantes (limite atteinte)")
        else:
            print("\n⚠️  MODE DRY-RUN - Aucune suppression effectuée")
            print("    Utilisez --execute pour supprimer réellement")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
