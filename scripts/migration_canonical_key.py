#!/usr/bin/env python3
"""
Migration Script - Phase 2.8.1 Canonical Deduplication Fix

Ce script effectue deux opérations critiques:
1. M1 - Backfill: Ajoute canonical_key à tous les CanonicalConcepts existants
2. M2 - Merge: Fusionne les doublons (même canonical_key) en redirigeant les relations

Usage:
    docker exec knowbase-app python /app/scripts/migration_canonical_key.py [--dry-run] [--tenant-id default]

Options:
    --dry-run       Affiche les opérations sans les exécuter
    --tenant-id     ID du tenant (default: "default")
    --skip-backup   Ne pas créer de backup des nodes avant fusion

Auteur: Claude Code + ChatGPT (collaboration Phase 2.8.1)
Date: 2025-12-21
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Setup path for imports
sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

# Import normalize function
try:
    from knowbase.utils.normalize import normalize_canonical_key, compute_canonical_key_fallback
except ImportError:
    # Fallback si exécuté hors container
    import re
    import unicodedata

    _WEAK_PUNCT_RE = re.compile(r"[.,;:!?()\[\]{}'\"`''""]")
    _WS_RE = re.compile(r"\s+")
    _DASH_RE = re.compile(r"[—–]")

    def normalize_canonical_key(name: Optional[str]) -> str:
        if not name:
            return ""
        key = name.strip().lower()
        key = unicodedata.normalize("NFKC", key)
        key = _DASH_RE.sub("-", key)
        key = _WEAK_PUNCT_RE.sub("", key)
        key = _WS_RE.sub(" ", key)
        return key.strip()

    def compute_canonical_key_fallback(canonical_id: str) -> str:
        return f"__empty__:{canonical_id}"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="[MIGRATION] %(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Neo4j connection settings
NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"

# Relation types to remap during merge (order matters for logging)
RELATION_TYPES_INCOMING = [
    ("ProtoConcept", "PROMOTED_TO"),
    ("RawAssertion", "HAS_SUBJECT"),
    ("RawAssertion", "HAS_OBJECT"),
]


def get_driver():
    """Crée une connexion Neo4j."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def create_index_if_not_exists(session, dry_run: bool = False):
    """Crée l'index sur canonical_key s'il n'existe pas."""
    # Vérifier si l'index existe via SHOW INDEXES (Neo4j 5.x syntax)
    check_query = """
    SHOW INDEXES
    YIELD name
    WHERE name = 'canonical_concept_key_idx'
    RETURN count(*) as count
    """
    try:
        result = session.run(check_query)
        record = result.single()
        if record and record["count"] > 0:
            logger.info("Index canonical_concept_key_idx existe déjà")
            return
    except Exception as e:
        # Si SHOW INDEXES échoue, continuer avec création (IF NOT EXISTS)
        logger.debug(f"Check index query failed: {e}, proceeding with creation")

    if dry_run:
        logger.info("[DRY-RUN] Créerait index canonical_concept_key_idx")
        return

    create_query = """
    CREATE INDEX canonical_concept_key_idx IF NOT EXISTS
    FOR (c:CanonicalConcept) ON (c.tenant_id, c.canonical_key)
    """
    session.run(create_query)
    logger.info("Index canonical_concept_key_idx créé")


def phase_m1_backfill(session, tenant_id: str, dry_run: bool = False) -> int:
    """
    M1 - Backfill canonical_key sur tous les CanonicalConcepts.

    Returns:
        Nombre de concepts mis à jour
    """
    logger.info("=" * 60)
    logger.info("PHASE M1 - Backfill canonical_key")
    logger.info("=" * 60)

    # Récupérer tous les concepts sans canonical_key
    fetch_query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c.canonical_key IS NULL OR c.canonical_key = ""
    RETURN c.canonical_id AS canonical_id, c.canonical_name AS canonical_name
    """
    result = session.run(fetch_query, tenant_id=tenant_id)
    records = list(result)

    if not records:
        logger.info("Aucun concept à mettre à jour (tous ont déjà canonical_key)")
        return 0

    logger.info(f"Concepts à traiter: {len(records)}")

    # Calculer les canonical_keys
    updates = []
    empty_count = 0
    for record in records:
        canonical_id = record["canonical_id"]
        canonical_name = record["canonical_name"] or ""

        key = normalize_canonical_key(canonical_name)
        if not key:
            key = compute_canonical_key_fallback(canonical_id)
            empty_count += 1

        updates.append({
            "canonical_id": canonical_id,
            "canonical_key": key
        })

    if empty_count > 0:
        logger.warning(f"  {empty_count} concepts ont un nom vide/invalide (fallback key utilisée)")

    if dry_run:
        logger.info(f"[DRY-RUN] Mettrait à jour {len(updates)} concepts")
        for u in updates[:5]:
            logger.info(f"  - {u['canonical_id'][:20]}... → key='{u['canonical_key'][:30]}...'")
        if len(updates) > 5:
            logger.info(f"  ... et {len(updates) - 5} autres")
        return len(updates)

    # Batch update (500 par batch)
    batch_size = 500
    updated = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        update_query = """
        UNWIND $rows AS row
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id, canonical_id: row.canonical_id})
        SET c.canonical_key = row.canonical_key,
            c.updated_at = datetime()
        RETURN count(*) AS updated
        """
        result = session.run(update_query, tenant_id=tenant_id, rows=batch)
        record = result.single()
        updated += record["updated"] if record else 0
        logger.info(f"  Batch {i // batch_size + 1}: {len(batch)} concepts mis à jour")

    logger.info(f"M1 terminé: {updated} concepts mis à jour avec canonical_key")
    return updated


def phase_m2_find_duplicates(session, tenant_id: str) -> Dict[str, List[Dict]]:
    """
    Trouve les groupes de doublons (même canonical_key).

    Returns:
        Dict[canonical_key, List[{canonical_id, canonical_name, created_at}]]
    """
    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c.canonical_key IS NOT NULL AND c.canonical_key <> ""
    WITH c.canonical_key AS key, collect({
        canonical_id: c.canonical_id,
        canonical_name: c.canonical_name,
        created_at: c.created_at,
        chunk_ids: c.chunk_ids
    }) AS concepts
    WHERE size(concepts) > 1
    RETURN key, concepts
    ORDER BY size(concepts) DESC
    """
    result = session.run(query, tenant_id=tenant_id)

    duplicates = {}
    for record in result:
        duplicates[record["key"]] = record["concepts"]

    return duplicates


def phase_m2_merge_group(
    session,
    tenant_id: str,
    canonical_key: str,
    concepts: List[Dict],
    dry_run: bool = False
) -> Tuple[str, List[str], Dict[str, int]]:
    """
    Fusionne un groupe de doublons.

    Strategy:
    1. Winner = le plus ancien (created_at)
    2. Remap toutes les relations vers winner
    3. Fusionner chunk_ids
    4. Supprimer les losers

    Returns:
        (winner_id, loser_ids, stats)
    """
    # Trier par created_at (plus ancien = winner)
    sorted_concepts = sorted(
        concepts,
        key=lambda x: x.get("created_at") or datetime.min
    )

    winner = sorted_concepts[0]
    losers = sorted_concepts[1:]

    winner_id = winner["canonical_id"]
    loser_ids = [c["canonical_id"] for c in losers]

    stats = {"relations_remapped": 0, "chunk_ids_merged": 0}

    if dry_run:
        logger.info(f"  [DRY-RUN] key='{canonical_key[:30]}': winner={winner_id[:15]}..., losers={len(loser_ids)}")
        return winner_id, loser_ids, stats

    # Pour chaque loser, remapper les relations
    for loser_id in loser_ids:
        for source_label, rel_type in RELATION_TYPES_INCOMING:
            remap_query = f"""
            MATCH (src:{source_label} {{tenant_id: $tenant_id}})-[r:{rel_type}]->(loser:CanonicalConcept {{canonical_id: $loser_id}})
            MATCH (winner:CanonicalConcept {{tenant_id: $tenant_id, canonical_id: $winner_id}})
            MERGE (src)-[:{rel_type}]->(winner)
            DELETE r
            RETURN count(*) AS remapped
            """
            result = session.run(
                remap_query,
                tenant_id=tenant_id,
                loser_id=loser_id,
                winner_id=winner_id
            )
            record = result.single()
            if record and record["remapped"] > 0:
                stats["relations_remapped"] += record["remapped"]
                logger.debug(f"    Remapped {record['remapped']} {rel_type} from {loser_id[:10]} to winner")

        # Fusionner chunk_ids
        merge_chunks_query = """
        MATCH (winner:CanonicalConcept {tenant_id: $tenant_id, canonical_id: $winner_id})
        MATCH (loser:CanonicalConcept {tenant_id: $tenant_id, canonical_id: $loser_id})
        WITH winner, loser,
             coalesce(winner.chunk_ids, []) AS wc,
             coalesce(loser.chunk_ids, []) AS lc
        SET winner.chunk_ids = wc + [x IN lc WHERE NOT x IN wc],
            winner.updated_at = datetime()
        RETURN size(winner.chunk_ids) AS new_size
        """
        result = session.run(
            merge_chunks_query,
            tenant_id=tenant_id,
            winner_id=winner_id,
            loser_id=loser_id
        )
        record = result.single()
        if record:
            stats["chunk_ids_merged"] += 1

        # Supprimer le loser
        delete_query = """
        MATCH (loser:CanonicalConcept {tenant_id: $tenant_id, canonical_id: $loser_id})
        DETACH DELETE loser
        RETURN count(*) AS deleted
        """
        session.run(delete_query, tenant_id=tenant_id, loser_id=loser_id)

    return winner_id, loser_ids, stats


def phase_m2_merge(session, tenant_id: str, dry_run: bool = False) -> Dict:
    """
    M2 - Fusion des doublons.

    Returns:
        Stats de la fusion
    """
    logger.info("=" * 60)
    logger.info("PHASE M2 - Fusion des doublons")
    logger.info("=" * 60)

    duplicates = phase_m2_find_duplicates(session, tenant_id)

    if not duplicates:
        logger.info("Aucun doublon détecté")
        return {"groups": 0, "losers_deleted": 0, "relations_remapped": 0}

    total_losers = sum(len(concepts) - 1 for concepts in duplicates.values())
    logger.info(f"Groupes de doublons: {len(duplicates)}")
    logger.info(f"Concepts à fusionner (losers): {total_losers}")

    stats = {
        "groups": len(duplicates),
        "losers_deleted": 0,
        "relations_remapped": 0,
        "chunk_ids_merged": 0
    }

    for canonical_key, concepts in duplicates.items():
        winner_id, loser_ids, group_stats = phase_m2_merge_group(
            session, tenant_id, canonical_key, concepts, dry_run
        )
        stats["losers_deleted"] += len(loser_ids)
        stats["relations_remapped"] += group_stats.get("relations_remapped", 0)
        stats["chunk_ids_merged"] += group_stats.get("chunk_ids_merged", 0)

    if not dry_run:
        logger.info(f"M2 terminé:")
        logger.info(f"  - Groupes fusionnés: {stats['groups']}")
        logger.info(f"  - Concepts supprimés: {stats['losers_deleted']}")
        logger.info(f"  - Relations remappées: {stats['relations_remapped']}")

    return stats


def verify_results(session, tenant_id: str):
    """Vérifie les résultats de la migration."""
    logger.info("=" * 60)
    logger.info("VERIFICATION DES RESULTATS")
    logger.info("=" * 60)

    queries = {
        "Total CanonicalConcepts": """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            RETURN count(c) AS count
        """,
        "Concepts avec canonical_key": """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WHERE c.canonical_key IS NOT NULL AND c.canonical_key <> ""
            RETURN count(c) AS count
        """,
        "Doublons restants": """
            MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
            WITH c.canonical_key AS key, count(*) AS cnt
            WHERE cnt > 1
            RETURN count(*) AS count
        """,
        "ProtoConcepts avec PROMOTED_TO": """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[:PROMOTED_TO]->(:CanonicalConcept)
            RETURN count(DISTINCT p) AS count
        """,
        "ProtoConcepts orphelins": """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})
            WHERE NOT (p)-[:PROMOTED_TO]->(:CanonicalConcept)
            RETURN count(p) AS count
        """
    }

    for label, query in queries.items():
        result = session.run(query, tenant_id=tenant_id)
        record = result.single()
        count = record["count"] if record else 0
        logger.info(f"  {label}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Migration canonical_key - Phase 2.8.1"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les opérations sans les exécuter"
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="ID du tenant (default: 'default')"
    )
    parser.add_argument(
        "--skip-m1",
        action="store_true",
        help="Sauter la phase M1 (backfill)"
    )
    parser.add_argument(
        "--skip-m2",
        action="store_true",
        help="Sauter la phase M2 (merge)"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("MIGRATION CANONICAL_KEY - Phase 2.8.1")
    logger.info("=" * 60)
    logger.info(f"Tenant: {args.tenant_id}")
    logger.info(f"Mode: {'DRY-RUN' if args.dry_run else 'EXECUTION'}")

    driver = get_driver()

    try:
        with driver.session() as session:
            # Créer index si nécessaire
            create_index_if_not_exists(session, args.dry_run)

            # Phase M1 - Backfill
            if not args.skip_m1:
                phase_m1_backfill(session, args.tenant_id, args.dry_run)

            # Phase M2 - Merge
            if not args.skip_m2:
                phase_m2_merge(session, args.tenant_id, args.dry_run)

            # Vérification
            if not args.dry_run:
                verify_results(session, args.tenant_id)

        logger.info("=" * 60)
        logger.info("MIGRATION TERMINÉE")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Erreur lors de la migration: {e}")
        raise
    finally:
        driver.close()


if __name__ == "__main__":
    main()
