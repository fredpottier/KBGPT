#!/usr/bin/env python3
"""
Backfill MENTIONED_IN Relations

Ce script crée les relations MENTIONED_IN manquantes entre
CanonicalConcepts et SectionContexts à partir des données ProtoConcept existantes.

Usage:
    docker exec knowbase-app python scripts/backfill_mentioned_in.py
    docker exec knowbase-app python scripts/backfill_mentioned_in.py --document-id DOC_ID
    docker exec knowbase-app python scripts/backfill_mentioned_in.py --dry-run

Author: Claude Code
Date: 2026-01-09
"""

import argparse
import logging
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Any

# Setup path pour imports
sys.path.insert(0, "/app/src")

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.config.settings import get_settings
from knowbase.navigation.navigation_layer_builder import NavigationLayerBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def get_documents(neo4j_client, tenant_id: str = "default") -> List[str]:
    """Récupère la liste des documents avec des ProtoConcepts."""
    query = """
    MATCH (p:ProtoConcept {tenant_id: $tenant_id})
    RETURN DISTINCT p.doc_id AS document_id
    ORDER BY document_id
    """
    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        result = session.run(query, tenant_id=tenant_id)
        return [r["document_id"] for r in result if r["document_id"]]


def get_sections_with_concepts(
    neo4j_client,
    document_id: str,
    tenant_id: str = "default"
) -> Dict[str, List[str]]:
    """
    Récupère les sections d'un document avec leurs CanonicalConcepts.

    Returns:
        Dict[section_id, List[canonical_id]]
    """
    # Requête pour obtenir les sections et leurs concepts canoniques
    query = """
    MATCH (p:ProtoConcept {document_id: $document_id, tenant_id: $tenant_id})
    OPTIONAL MATCH (p)-[:INSTANCE_OF]->(cc:CanonicalConcept {tenant_id: $tenant_id})
    WHERE p.section_id IS NOT NULL
    RETURN p.section_id AS section_id,
           collect(DISTINCT cc.canonical_id) AS canonical_ids
    """

    sections: Dict[str, List[str]] = defaultdict(list)

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        result = session.run(
            query,
            document_id=document_id,
            tenant_id=tenant_id
        )

        for record in result:
            section_id = record["section_id"]
            canonical_ids = [cid for cid in record["canonical_ids"] if cid]

            if section_id and canonical_ids:
                sections[section_id].extend(canonical_ids)

    # Dédupliquer les canonical_ids par section
    return {
        section_id: list(set(cids))
        for section_id, cids in sections.items()
    }


def backfill_document(
    builder: NavigationLayerBuilder,
    neo4j_client,
    document_id: str,
    tenant_id: str = "default",
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Backfill les relations MENTIONED_IN pour un document.

    Returns:
        Stats du backfill
    """
    logger.info(f"[Backfill] Processing document: {document_id}")

    # 1. Récupérer sections avec concepts
    sections_data = get_sections_with_concepts(neo4j_client, document_id, tenant_id)

    if not sections_data:
        logger.warning(f"[Backfill] No sections found for {document_id}")
        return {"sections": 0, "mentions": 0, "skipped": 0}

    logger.info(f"[Backfill] Found {len(sections_data)} sections with concepts")

    stats = {
        "sections_created": 0,
        "mentions_created": 0,
        "concepts_linked": 0
    }

    if dry_run:
        # Mode dry-run: juste compter
        total_concepts = sum(len(cids) for cids in sections_data.values())
        logger.info(f"[Backfill:DRY-RUN] Would create {len(sections_data)} sections")
        logger.info(f"[Backfill:DRY-RUN] Would create ~{total_concepts} MENTIONED_IN relations")
        return {
            "sections": len(sections_data),
            "mentions": total_concepts,
            "dry_run": True
        }

    # 2. Créer DocumentContext
    builder.create_document_context(
        document_id=document_id,
        document_name=document_id
    )

    # 3. Pour chaque section, créer SectionContext et liens
    for section_path, canonical_ids in sections_data.items():
        # Extraire le niveau de la section (basé sur le préfixe numérique)
        section_level = _extract_section_level(section_path)

        # Créer SectionContext
        section_ctx = builder.create_section_context(
            document_id=document_id,
            section_path=section_path,
            section_level=section_level
        )

        if section_ctx:
            stats["sections_created"] += 1

            # Lier les concepts à cette section
            links = builder.link_concepts_to_section(
                document_id=document_id,
                section_path=section_path,
                concept_ids=canonical_ids
            )

            stats["mentions_created"] += links
            stats["concepts_linked"] += len(canonical_ids)

            logger.debug(
                f"[Backfill] Section '{section_path[:50]}...': "
                f"{len(canonical_ids)} concepts, {links} links"
            )

    # 4. Calculer les poids
    builder.compute_weights(document_id=document_id)

    logger.info(
        f"[Backfill] Completed {document_id}: "
        f"{stats['sections_created']} sections, "
        f"{stats['mentions_created']} mentions"
    )

    return stats


def _extract_section_level(section_path: str) -> int:
    """Extrait le niveau hiérarchique d'une section."""
    # Format typique: "1. Title / cluster_0" ou "1.2. Subtitle / cluster_0"
    if not section_path:
        return 0

    # Compte les points dans le préfixe numérique
    parts = section_path.split(".")
    level = 0
    for part in parts:
        if part.strip() and part.strip()[0].isdigit():
            level += 1
        else:
            break

    return max(0, level - 1)  # Level 0 = top-level


def main():
    parser = argparse.ArgumentParser(
        description="Backfill MENTIONED_IN relations from existing ProtoConcepts"
    )
    parser.add_argument(
        "--document-id",
        help="Process only this document (default: all documents)"
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="Tenant ID (default: 'default')"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create anything, just show what would be done"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("[Backfill] Starting MENTIONED_IN backfill")
    logger.info(f"[Backfill] Tenant: {args.tenant_id}")
    logger.info(f"[Backfill] Dry-run: {args.dry_run}")
    logger.info("=" * 60)

    # Connexion Neo4j
    settings = get_settings()
    neo4j_client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    if not neo4j_client.is_connected():
        logger.error("[Backfill] Failed to connect to Neo4j")
        sys.exit(1)

    # Builder
    builder = NavigationLayerBuilder(
        neo4j_client=neo4j_client,
        tenant_id=args.tenant_id
    )

    # Documents à traiter
    if args.document_id:
        documents = [args.document_id]
    else:
        documents = get_documents(neo4j_client, args.tenant_id)

    logger.info(f"[Backfill] Found {len(documents)} documents to process")

    # Traitement
    total_stats = defaultdict(int)

    for doc_id in documents:
        try:
            stats = backfill_document(
                builder=builder,
                neo4j_client=neo4j_client,
                document_id=doc_id,
                tenant_id=args.tenant_id,
                dry_run=args.dry_run
            )

            for key, value in stats.items():
                total_stats[key] += value

        except Exception as e:
            logger.error(f"[Backfill] Error processing {doc_id}: {e}")
            total_stats["errors"] += 1

    # Résumé
    logger.info("=" * 60)
    logger.info("[Backfill] COMPLETED")
    logger.info(f"[Backfill] Documents processed: {len(documents)}")
    logger.info(f"[Backfill] Sections created: {total_stats.get('sections_created', total_stats.get('sections', 0))}")
    logger.info(f"[Backfill] MENTIONED_IN created: {total_stats.get('mentions_created', total_stats.get('mentions', 0))}")
    if total_stats.get("errors"):
        logger.warning(f"[Backfill] Errors: {total_stats['errors']}")
    logger.info("=" * 60)

    # Cleanup
    builder.close()


if __name__ == "__main__":
    main()
