#!/usr/bin/env python3
"""
Script de migration pour construire la Navigation Layer sur les documents existants.

Ce script est nécessaire pour les documents ingérés AVANT l'implémentation
de la Navigation Layer (ADR_NAVIGATION_LAYER.md).

Usage:
    python scripts/migrate_navigation_layer.py [options]

Options:
    --tenant TENANT_ID    Tenant à migrer (défaut: default)
    --doc-id DOC_ID       Migrer un seul document (optionnel)
    --dry-run             Afficher sans exécuter
    --verbose             Logs détaillés
    --batch-size N        Nombre de documents par batch (défaut: 50)

Exemple:
    # Migrer tous les documents du tenant default
    python scripts/migrate_navigation_layer.py --verbose

    # Tester sans exécuter
    python scripts/migrate_navigation_layer.py --dry-run

    # Migrer un seul document
    python scripts/migrate_navigation_layer.py --doc-id abc123

Author: Claude Code
Date: 2026-01-01
ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md
"""

import argparse
import logging
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Any

# Setup path
sys.path.insert(0, "/app/src")

from knowbase.config.settings import get_settings
from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.navigation import get_navigation_layer_builder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_documents_to_migrate(
    neo4j_client,
    tenant_id: str,
    document_id: Optional[str] = None,
    batch_size: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Récupère les documents à migrer.

    Returns:
        Liste de documents avec leurs IDs et noms
    """
    if document_id:
        query = """
        MATCH (d:Document {document_id: $doc_id, tenant_id: $tenant_id})
        RETURN d.document_id AS document_id,
               d.title AS title,
               d.document_type AS document_type
        """
        params = {"doc_id": document_id, "tenant_id": tenant_id}
    else:
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})
        RETURN d.document_id AS document_id,
               d.title AS title,
               d.document_type AS document_type
        ORDER BY d.document_id
        SKIP $offset
        LIMIT $limit
        """
        params = {"tenant_id": tenant_id, "offset": offset, "limit": batch_size}

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        result = session.run(query, params)
        return [dict(r) for r in result]


def get_concepts_for_document(
    neo4j_client,
    tenant_id: str,
    document_id: str
) -> Dict[str, List[str]]:
    """
    Récupère les concepts liés à un document, groupés par section.

    Supporte deux architectures:
    1. HybridAnchors (nouveau): Document ← HybridAnchor → CanonicalConcept
    2. Proto-based (legacy): DocumentChunk ← ProtoConcept → CanonicalConcept

    Returns:
        Dict[section_id, List[canonical_id]]
    """
    section_concepts: Dict[str, List[str]] = defaultdict(list)
    all_concept_ids: List[str] = []

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        # Essayer d'abord via HybridAnchors (nouveau)
        query_hybrid = """
        MATCH (d:Document {document_id: $doc_id, tenant_id: $tenant_id})
              <-[:ANCHORED_IN]-(ha:HybridAnchor {tenant_id: $tenant_id})
              -[:REPRESENTS]->(cc:CanonicalConcept {tenant_id: $tenant_id})
        OPTIONAL MATCH (ha)-[:IN_SECTION]->(sec)
        RETURN cc.canonical_id AS concept_id,
               cc.canonical_name AS concept_name,
               COALESCE(sec.section_path, ha.section_id, 'root') AS section_path
        """

        result = session.run(query_hybrid, {
            "doc_id": document_id,
            "tenant_id": tenant_id
        })
        records = list(result)

        # Si pas de résultats, essayer via ProtoConcepts (legacy)
        if not records:
            query_proto = """
            MATCH (dc:DocumentChunk {document_id: $doc_id, tenant_id: $tenant_id})
                  <-[:ANCHORED_IN]-(p:ProtoConcept {tenant_id: $tenant_id})
                  -[:INSTANCE_OF]->(cc:CanonicalConcept {tenant_id: $tenant_id})
            RETURN DISTINCT cc.canonical_id AS concept_id,
                   cc.canonical_name AS concept_name,
                   COALESCE(p.section_id, 'root') AS section_path
            """

            result = session.run(query_proto, {
                "doc_id": document_id,
                "tenant_id": tenant_id
            })
            records = list(result)

        for record in records:
            concept_id = record["concept_id"]
            section_path = record["section_path"] or "root"

            if concept_id:
                section_concepts[section_path].append(concept_id)
                if concept_id not in all_concept_ids:
                    all_concept_ids.append(concept_id)

    # Ajouter tous les concepts au niveau document
    section_concepts[f"doc:{document_id}"] = all_concept_ids

    return section_concepts


def check_existing_navigation(
    neo4j_client,
    tenant_id: str,
    document_id: str
) -> bool:
    """
    Vérifie si la Navigation Layer existe déjà pour ce document.

    Returns:
        True si déjà migrée
    """
    query = """
    MATCH (ctx:DocumentContext:ContextNode {doc_id: $doc_id, tenant_id: $tenant_id})
    RETURN count(ctx) > 0 AS exists
    """

    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        result = session.run(query, {
            "doc_id": document_id,
            "tenant_id": tenant_id
        })
        record = result.single()
        return record["exists"] if record else False


def migrate_document(
    builder,
    neo4j_client,
    tenant_id: str,
    document: Dict[str, Any],
    dry_run: bool = False,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Migre un seul document vers la Navigation Layer.

    Returns:
        Stats de migration
    """
    document_id = document["document_id"]
    document_name = document.get("title") or document_id
    document_type = document.get("document_type") or "unknown"

    # Vérifier si déjà migrée
    if check_existing_navigation(neo4j_client, tenant_id, document_id):
        if verbose:
            logger.info(f"  → Document {document_id} already has Navigation Layer, skipping")
        return {"status": "skipped", "reason": "already_migrated"}

    # Récupérer les concepts par section
    section_concepts = get_concepts_for_document(neo4j_client, tenant_id, document_id)

    total_concepts = len(section_concepts.get(f"doc:{document_id}", []))
    total_sections = len([s for s in section_concepts.keys() if not s.startswith("doc:")])

    if verbose:
        logger.info(
            f"  → Document {document_id}: {total_concepts} concepts, "
            f"{total_sections} sections"
        )

    if dry_run:
        return {
            "status": "dry_run",
            "concepts": total_concepts,
            "sections": total_sections
        }

    # Construire les sections pour le builder
    sections = []
    for section_path, concept_ids in section_concepts.items():
        if not section_path.startswith("doc:"):
            sections.append({
                "path": section_path,
                "level": 0,  # On ne connaît pas le niveau exact
                "concept_ids": concept_ids
            })

    # Concept mentions au niveau document
    concept_mentions = {
        f"doc:{document_id}": section_concepts.get(f"doc:{document_id}", [])
    }

    # Build navigation layer
    stats = builder.build_for_document(
        document_id=document_id,
        document_name=document_name,
        document_type=document_type,
        sections=sections,
        concept_mentions=concept_mentions
    )

    return {
        "status": "migrated",
        "stats": stats
    }


def main():
    parser = argparse.ArgumentParser(
        description="Migration Navigation Layer pour documents existants"
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant ID (défaut: default)"
    )
    parser.add_argument(
        "--doc-id",
        help="Migrer un seul document (optionnel)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Afficher sans exécuter"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Logs détaillés"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Documents par batch (défaut: 50)"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialiser clients
    settings = get_settings()
    neo4j_client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    if not neo4j_client.is_connected():
        logger.error("Failed to connect to Neo4j")
        sys.exit(1)

    builder = get_navigation_layer_builder(tenant_id=args.tenant)

    logger.info(f"=== Navigation Layer Migration ===")
    logger.info(f"Tenant: {args.tenant}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")

    # Stats globales
    total_docs = 0
    migrated = 0
    skipped = 0
    errors = 0
    start_time = time.time()

    # Paginer les documents
    offset = 0

    while True:
        documents = get_documents_to_migrate(
            neo4j_client,
            args.tenant,
            document_id=args.doc_id,
            batch_size=args.batch_size,
            offset=offset
        )

        if not documents:
            break

        logger.info(f"Processing batch: {len(documents)} documents (offset={offset})")

        for doc in documents:
            total_docs += 1
            doc_id = doc["document_id"]

            try:
                result = migrate_document(
                    builder=builder,
                    neo4j_client=neo4j_client,
                    tenant_id=args.tenant,
                    document=doc,
                    dry_run=args.dry_run,
                    verbose=args.verbose
                )

                if result["status"] == "migrated":
                    migrated += 1
                    if args.verbose:
                        logger.info(f"  ✓ Migrated {doc_id}: {result.get('stats', {})}")
                elif result["status"] == "skipped":
                    skipped += 1
                elif result["status"] == "dry_run":
                    migrated += 1  # Would be migrated

            except Exception as e:
                errors += 1
                logger.error(f"  ✗ Error migrating {doc_id}: {e}")

        # Si doc_id spécifique, pas de pagination
        if args.doc_id:
            break

        offset += args.batch_size

    # Résumé
    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=== Migration Complete ===")
    logger.info(f"Total documents: {total_docs}")
    logger.info(f"Migrated: {migrated}")
    logger.info(f"Skipped (already done): {skipped}")
    logger.info(f"Errors: {errors}")
    logger.info(f"Time: {elapsed:.1f}s")

    if args.dry_run:
        logger.info("")
        logger.info("(Dry run - no changes made)")


if __name__ == "__main__":
    main()
