#!/usr/bin/env python3
"""
Compute Relation Likelihood for SectionContexts

Script batch pour calculer et stocker les features de relation likelihood
sur les nœuds SectionContext dans Neo4j.

Usage:
    docker exec knowbase-app python scripts/compute_section_likelihood.py
    docker exec knowbase-app python scripts/compute_section_likelihood.py --document-id DOC_ID
    docker exec knowbase-app python scripts/compute_section_likelihood.py --dry-run

Author: Claude Code
Date: 2026-01-09
Spec: ChatGPT Clean-Room Agnostique Phase 1
"""

import argparse
import logging
import sys
from collections import defaultdict
from typing import Dict, List, Optional

# Setup path pour imports
sys.path.insert(0, "/app/src")

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.config.settings import get_settings
from knowbase.structural.relation_likelihood import (
    compute_features,
    RelationLikelihoodFeatures,
    log_features
)
from qdrant_client.models import Filter, FieldCondition, MatchValue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def get_all_section_contexts(
    neo4j_client,
    tenant_id: str = "default",
    document_id: Optional[str] = None
) -> List[Dict]:
    """
    Récupère tous les SectionContext à traiter.

    Returns:
        Liste de {context_id, doc_id, section_path}
    """
    if document_id:
        query = """
        MATCH (s:SectionContext {tenant_id: $tenant_id})
        WHERE s.doc_id = $document_id
        RETURN s.context_id AS context_id,
               s.doc_id AS doc_id,
               s.section_path AS section_path
        """
        params = {"tenant_id": tenant_id, "document_id": document_id}
    else:
        query = """
        MATCH (s:SectionContext {tenant_id: $tenant_id})
        RETURN s.context_id AS context_id,
               s.doc_id AS doc_id,
               s.section_path AS section_path
        """
        params = {"tenant_id": tenant_id}

    sections = []
    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        result = session.run(query, **params)
        for record in result:
            sections.append({
                "context_id": record["context_id"],
                "doc_id": record["doc_id"],
                "section_path": record["section_path"]
            })

    return sections


def get_section_text_from_qdrant(
    qdrant_client,
    context_id: str,
    collection_name: str = "knowbase"
) -> str:
    """
    Récupère le texte d'une section depuis Qdrant.

    Concatène tous les chunks ayant ce context_id.
    """
    try:
        scroll_result = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="context_id",
                        match=MatchValue(value=context_id)
                    )
                ]
            ),
            limit=50,
            with_payload=True,
            with_vectors=False
        )

        points, _ = scroll_result
        texts = []
        for point in points:
            if point.payload and "text" in point.payload:
                texts.append(point.payload["text"])

        return "\n\n".join(texts)

    except Exception as e:
        logger.warning(f"[ComputeLikelihood] Failed to get text for {context_id}: {e}")
        return ""


def update_section_likelihood(
    neo4j_client,
    context_id: str,
    features: RelationLikelihoodFeatures,
    tenant_id: str = "default"
) -> bool:
    """
    Met à jour les propriétés de relation likelihood sur un SectionContext.
    """
    query = """
    MATCH (s:SectionContext {context_id: $context_id, tenant_id: $tenant_id})
    SET s.relation_likelihood = $relation_likelihood,
        s.relation_likelihood_tier = $tier,
        s.bullet_ratio = $bullet_ratio,
        s.verb_density = $verb_density,
        s.enumeration_ratio = $enumeration_ratio,
        s.sentence_count = $sentence_count
    RETURN s.context_id AS updated
    """

    try:
        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            result = session.run(
                query,
                context_id=context_id,
                tenant_id=tenant_id,
                relation_likelihood=features.relation_likelihood,
                tier=features.tier,
                bullet_ratio=features.bullet_ratio,
                verb_density=features.verb_density,
                enumeration_ratio=features.enumeration_ratio,
                sentence_count=features.sentence_count
            )
            return result.single() is not None
    except Exception as e:
        logger.error(f"[ComputeLikelihood] Failed to update {context_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Compute relation likelihood features for SectionContexts"
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
        help="Don't write to Neo4j, just show stats"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed features for each section"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("[ComputeLikelihood] Starting relation likelihood computation")
    logger.info(f"[ComputeLikelihood] Tenant: {args.tenant_id}")
    logger.info(f"[ComputeLikelihood] Document: {args.document_id or 'ALL'}")
    logger.info(f"[ComputeLikelihood] Dry-run: {args.dry_run}")
    logger.info("=" * 60)

    # Connexions
    settings = get_settings()
    neo4j_client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    if not neo4j_client.is_connected():
        logger.error("[ComputeLikelihood] Failed to connect to Neo4j")
        sys.exit(1)

    qdrant_client = get_qdrant_client()

    # Récupérer les sections
    sections = get_all_section_contexts(
        neo4j_client,
        tenant_id=args.tenant_id,
        document_id=args.document_id
    )

    logger.info(f"[ComputeLikelihood] Found {len(sections)} sections to process")

    # Stats par tier
    tier_stats = defaultdict(int)
    updated_count = 0
    skipped_count = 0

    for i, section in enumerate(sections):
        context_id = section["context_id"]
        doc_id = section["doc_id"]

        # Récupérer texte depuis Qdrant
        text = get_section_text_from_qdrant(qdrant_client, context_id)

        if not text:
            skipped_count += 1
            continue

        # Calculer features
        features = compute_features(text)
        tier_stats[features.tier] += 1

        if args.verbose:
            log_features(features, context_id)
            logger.info(
                f"[ComputeLikelihood] [{i+1}/{len(sections)}] "
                f"{context_id[:30]}... → {features.tier} "
                f"(score={features.relation_likelihood:.2f})"
            )

        # Écrire dans Neo4j
        if not args.dry_run:
            if update_section_likelihood(neo4j_client, context_id, features, args.tenant_id):
                updated_count += 1

        # Progress
        if (i + 1) % 50 == 0:
            logger.info(f"[ComputeLikelihood] Progress: {i+1}/{len(sections)}")

    # Résumé
    logger.info("=" * 60)
    logger.info("[ComputeLikelihood] COMPLETED")
    logger.info(f"[ComputeLikelihood] Sections processed: {len(sections)}")
    logger.info(f"[ComputeLikelihood] Sections updated: {updated_count}")
    logger.info(f"[ComputeLikelihood] Sections skipped (no text): {skipped_count}")
    logger.info("[ComputeLikelihood] Distribution by tier:")
    for tier in ["HIGH", "MEDIUM", "LOW", "VERY_LOW"]:
        count = tier_stats[tier]
        pct = (count / max(1, len(sections) - skipped_count)) * 100
        logger.info(f"  - {tier}: {count} ({pct:.1f}%)")
    logger.info("=" * 60)

    # Sections "allowed" pour candidats (HIGH + MEDIUM)
    allowed = tier_stats["HIGH"] + tier_stats["MEDIUM"]
    total_valid = len(sections) - skipped_count
    logger.info(
        f"[ComputeLikelihood] Sections allowed for candidates: "
        f"{allowed}/{total_valid} ({(allowed/max(1,total_valid))*100:.1f}%)"
    )


if __name__ == "__main__":
    main()
