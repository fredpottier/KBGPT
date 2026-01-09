#!/usr/bin/env python3
"""
Script de nettoyage des markers faux positifs dans Neo4j.

Ces markers ont ete inseres avant la correction du bug d'inversion
dans StructureNumberingGate (candidate_mining.py ligne 1802).

Usage:
    # Dry-run (voir ce qui serait nettoye)
    docker-compose exec app python scripts/cleanup_bad_markers.py --dry-run

    # Execution reelle
    docker-compose exec app python scripts/cleanup_bad_markers.py
"""

import argparse
import logging
from typing import List, Set

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Markers identifies comme faux positifs (numérotation structurelle)
BAD_MARKERS: Set[str] = {
    # Pattern "WORD N" avec N = numero de page/slide
    "Content 2",
    "Content 3",
    "Content 4",
    "Content 5",
    "PUBLIC 2",
    "PUBLIC 3",
    "PUBLIC 4",
    "PUBLIC 5",
    "Public 2",
    "Public 3",
    "Public 4",
    "Public 5",
    # Ajouter d'autres patterns si necessaire
}

# Pattern regex pour detection automatique (optionnel)
BAD_PATTERNS = [
    r"^Content \d+$",      # Content 2, Content 3, etc.
    r"^PUBLIC \d+$",       # PUBLIC 2, PUBLIC 3, etc.
    r"^Public \d+$",       # Public 2, Public 3, etc.
    r"^Chapter \d+$",      # Chapter 1, Chapter 2, etc.
    r"^Module \d+$",       # Module 1, Module 2, etc.
    r"^Section \d+$",      # Section 1, Section 2, etc.
    r"^Page \d+$",         # Page 1, Page 2, etc.
    r"^Slide \d+$",        # Slide 1, Slide 2, etc.
]


def get_neo4j_client():
    """Obtient le client Neo4j."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client()


def analyze_markers(dry_run: bool = True) -> dict:
    """
    Analyse et optionnellement nettoie les markers faux positifs.

    Returns:
        Statistiques de nettoyage
    """
    import re

    client = get_neo4j_client()

    # Compiler les patterns
    compiled_patterns = [re.compile(p) for p in BAD_PATTERNS]

    def is_bad_marker(marker: str) -> bool:
        """Verifie si un marker est un faux positif."""
        # Check liste explicite
        if marker in BAD_MARKERS:
            return True
        # Check patterns regex
        for pattern in compiled_patterns:
            if pattern.match(marker):
                return True
        return False

    # Recuperer tous les documents avec leurs markers
    query_get = """
    MATCH (d:Document)
    WHERE d.global_markers IS NOT NULL AND size(d.global_markers) > 0
    RETURN d.id AS doc_id, d.name AS doc_name, d.global_markers AS markers
    """

    stats = {
        "documents_analyzed": 0,
        "documents_modified": 0,
        "markers_removed": 0,
        "bad_markers_found": set(),
        "details": []
    }

    with client.driver.session(database="neo4j") as session:
        result = session.run(query_get)
        records = list(result)

        for record in records:
            doc_id = record["doc_id"]
            doc_name = record["doc_name"]
            markers = list(record["markers"])

            stats["documents_analyzed"] += 1

            # Identifier les mauvais markers
            bad_in_doc = [m for m in markers if is_bad_marker(m)]
            good_markers = [m for m in markers if not is_bad_marker(m)]

            if bad_in_doc:
                stats["documents_modified"] += 1
                stats["markers_removed"] += len(bad_in_doc)
                stats["bad_markers_found"].update(bad_in_doc)

                detail = {
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "removed": bad_in_doc,
                    "kept": good_markers
                }
                stats["details"].append(detail)

                logger.info(f"\n[{doc_name}]")
                logger.info(f"  - Suppression: {bad_in_doc}")
                logger.info(f"  - Conservation: {good_markers}")

                if not dry_run:
                    # Mettre a jour le document
                    update_query = """
                    MATCH (d:Document {id: $doc_id})
                    SET d.global_markers = $new_markers
                    RETURN d.id
                    """
                    session.run(update_query, doc_id=doc_id, new_markers=good_markers)

    # Convertir set en list pour affichage
    stats["bad_markers_found"] = list(stats["bad_markers_found"])

    return stats


def main():
    parser = argparse.ArgumentParser(description="Nettoie les markers faux positifs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche ce qui serait nettoye sans modifier la base"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("NETTOYAGE DES MARKERS FAUX POSITIFS")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("MODE: Dry-run (aucune modification)")
    else:
        logger.info("MODE: Execution reelle")

    logger.info("")

    stats = analyze_markers(dry_run=args.dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("RESUME")
    logger.info("=" * 60)
    logger.info(f"Documents analyses: {stats['documents_analyzed']}")
    logger.info(f"Documents modifies: {stats['documents_modified']}")
    logger.info(f"Markers supprimes: {stats['markers_removed']}")
    logger.info(f"Types de bad markers: {stats['bad_markers_found']}")

    if args.dry_run and stats['documents_modified'] > 0:
        logger.info("")
        logger.info("Pour appliquer les modifications, relancez sans --dry-run")


if __name__ == "__main__":
    main()
