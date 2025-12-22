#!/usr/bin/env python3
"""
Script de réparation Phase 2.8.1 - Lier les ProtoConcepts orphelins

Ce script lie les ProtoConcepts orphelins aux CanonicalConcepts existants
en utilisant la clé canonical_key pour le matching.

Usage:
    docker exec knowbase-app python /app/scripts/repair_orphan_protos.py [--dry-run] [--tenant-id default]

Auteur: Claude Code
Date: 2025-12-21
"""

import argparse
import logging
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

try:
    from knowbase.utils.normalize import normalize_canonical_key
except ImportError:
    import re
    import unicodedata

    _WEAK_PUNCT_RE = re.compile(r"[.,;:!?()\\[\\]{}'\"`''\"\"']")
    _WS_RE = re.compile(r"\\s+")
    _DASH_RE = re.compile(r"[—–]")

    def normalize_canonical_key(name):
        if not name:
            return ""
        key = name.strip().lower()
        key = unicodedata.normalize("NFKC", key)
        key = _DASH_RE.sub("-", key)
        key = _WEAK_PUNCT_RE.sub("", key)
        key = _WS_RE.sub(" ", key)
        return key.strip()

logging.basicConfig(
    level=logging.INFO,
    format="[REPAIR] %(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphiti_neo4j_pass"


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def find_orphans(session, tenant_id: str) -> List[Dict]:
    """Trouve tous les ProtoConcepts orphelins."""
    query = """
    MATCH (p:ProtoConcept {tenant_id: $tenant_id})
    WHERE NOT (p)-[:PROMOTED_TO]->(:CanonicalConcept)
    RETURN p.concept_id AS proto_id,
           p.concept_name AS proto_name,
           p.segment_id AS segment_id
    ORDER BY p.concept_name
    """
    result = session.run(query, tenant_id=tenant_id)
    return [dict(record) for record in result]


def find_matching_canonical(session, tenant_id: str, proto_name: str) -> Tuple[str, str]:
    """Trouve le CanonicalConcept correspondant via canonical_key."""
    canonical_key = normalize_canonical_key(proto_name)
    if not canonical_key:
        return None, None

    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c.canonical_key = $canonical_key
    RETURN c.canonical_id AS canonical_id, c.canonical_name AS canonical_name
    LIMIT 1
    """
    result = session.run(query, tenant_id=tenant_id, canonical_key=canonical_key)
    record = result.single()

    if record:
        return record["canonical_id"], record["canonical_name"]
    return None, None


def link_orphan_to_canonical(session, tenant_id: str, proto_id: str, canonical_id: str) -> bool:
    """Crée la relation PROMOTED_TO entre un proto orphelin et un canonical."""
    query = """
    MATCH (proto:ProtoConcept {concept_id: $proto_id, tenant_id: $tenant_id})
    MATCH (canonical:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})

    // Agréger chunk_ids
    WITH proto, canonical,
         COALESCE(canonical.chunk_ids, []) AS existing_chunks,
         COALESCE(proto.chunk_ids, []) AS proto_chunks

    WITH proto, canonical,
         existing_chunks + proto_chunks AS all_chunks_raw

    // Dédupliquer
    UNWIND CASE WHEN SIZE(all_chunks_raw) = 0 THEN [null] ELSE all_chunks_raw END AS chunk_item
    WITH proto, canonical, chunk_item
    WHERE chunk_item IS NOT NULL
    WITH proto, canonical, COLLECT(DISTINCT chunk_item) AS aggregated_chunks

    // Mettre à jour canonical
    SET canonical.chunk_ids = aggregated_chunks,
        canonical.updated_at = datetime()

    // Créer relation
    MERGE (proto)-[:PROMOTED_TO {
        promoted_at: datetime(),
        deduplication: true,
        repair_script: true
    }]->(canonical)

    RETURN canonical.canonical_id AS linked_to
    """
    try:
        result = session.run(query, tenant_id=tenant_id, proto_id=proto_id, canonical_id=canonical_id)
        record = result.single()
        return record is not None
    except Exception as e:
        logger.error(f"Error linking proto {proto_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Repair orphan ProtoConcepts - Phase 2.8.1")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("REPAIR ORPHAN PROTOCONCEPTS - Phase 2.8.1")
    logger.info("=" * 60)
    logger.info(f"Tenant: {args.tenant_id}")
    logger.info(f"Mode: {'DRY-RUN' if args.dry_run else 'EXECUTION'}")

    driver = get_driver()

    try:
        with driver.session() as session:
            # Trouver les orphelins
            orphans = find_orphans(session, args.tenant_id)
            logger.info(f"Found {len(orphans)} orphan ProtoConcepts")

            if not orphans:
                logger.info("No orphans to repair!")
                return

            # Stats
            linked_count = 0
            no_match_count = 0
            failed_count = 0

            # Grouper par nom pour logs lisibles
            seen_names = {}

            for orphan in orphans:
                proto_id = orphan["proto_id"]
                proto_name = orphan["proto_name"]
                segment_id = orphan["segment_id"]

                # Chercher le canonical correspondant
                canonical_id, canonical_name = find_matching_canonical(
                    session, args.tenant_id, proto_name
                )

                if not canonical_id:
                    if proto_name not in seen_names:
                        seen_names[proto_name] = "NO_MATCH"
                        logger.debug(f"No canonical found for '{proto_name}'")
                    no_match_count += 1
                    continue

                if args.dry_run:
                    if proto_name not in seen_names:
                        seen_names[proto_name] = canonical_name
                        logger.info(f"[DRY-RUN] Would link '{proto_name}' -> '{canonical_name}'")
                    linked_count += 1
                else:
                    success = link_orphan_to_canonical(
                        session, args.tenant_id, proto_id, canonical_id
                    )
                    if success:
                        if proto_name not in seen_names:
                            seen_names[proto_name] = canonical_name
                            logger.info(f"Linked '{proto_name}' ({segment_id}) -> '{canonical_name}'")
                        linked_count += 1
                    else:
                        failed_count += 1

            # Résumé
            logger.info("=" * 60)
            logger.info("SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Total orphans processed: {len(orphans)}")
            logger.info(f"Successfully linked: {linked_count}")
            logger.info(f"No matching canonical: {no_match_count}")
            logger.info(f"Failed to link: {failed_count}")

            # Vérification post-repair
            if not args.dry_run:
                remaining_orphans = find_orphans(session, args.tenant_id)
                logger.info(f"Remaining orphans after repair: {len(remaining_orphans)}")

    except Exception as e:
        logger.error(f"Error during repair: {e}")
        raise
    finally:
        driver.close()


if __name__ == "__main__":
    main()
