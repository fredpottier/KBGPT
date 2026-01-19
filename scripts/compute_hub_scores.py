#!/usr/bin/env python3
"""
Compute Hub Scores for CanonicalConcepts

Script batch pour calculer et stocker les scores de "hub" sur les concepts.
Un concept "hub" est un concept très fréquent mais peu relationnel.

Features (agnostiques):
- doc_frequency: nb de documents où le concept apparaît
- section_spread: nb de sections distinctes
- validated_relation_degree: nb de relations prouvées
- list_context_ratio: % de mentions dans des sections LOW/VERY_LOW

Usage:
    docker exec knowbase-app python scripts/compute_hub_scores.py
    docker exec knowbase-app python scripts/compute_hub_scores.py --dry-run

Author: Claude Code
Date: 2026-01-09
Spec: ChatGPT Clean-Room Agnostique Phase 1
"""

import argparse
import logging
import sys
from typing import Dict, List, Tuple
import numpy as np

# Setup path pour imports
sys.path.insert(0, "/app/src")

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.config.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# Seuil pour être considéré comme HUB
HUB_SCORE_THRESHOLD = 0.65


def compute_concept_stats(neo4j_client, tenant_id: str = "default") -> List[Dict]:
    """
    Calcule les statistiques de base pour chaque concept.

    Returns:
        Liste de {concept_id, doc_frequency, section_spread,
                  validated_relation_degree, list_context_ratio}
    """
    # Requête combinée pour toutes les stats
    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})

    // Doc frequency et section spread
    OPTIONAL MATCH (c)-[:MENTIONED_IN]->(s:SectionContext)
    WITH c,
         count(DISTINCT s.doc_id) AS doc_frequency,
         count(DISTINCT s.context_id) AS section_spread,
         count(s) AS total_mentions,
         sum(CASE
             WHEN s.relation_likelihood_tier IN ['LOW', 'VERY_LOW'] THEN 1
             ELSE 0
         END) AS low_tier_mentions

    // Validated relation degree (relations avec evidence)
    OPTIONAL MATCH (c)-[r]->(o:CanonicalConcept {tenant_id: $tenant_id})
    WHERE type(r) <> 'MENTIONED_IN'
      AND type(r) <> 'CO_OCCURS_IN_CORPUS'
      AND r.evidence_context_ids IS NOT NULL
      AND size(r.evidence_context_ids) > 0
    WITH c, doc_frequency, section_spread, total_mentions, low_tier_mentions,
         count(r) AS outgoing_relations

    OPTIONAL MATCH (i:CanonicalConcept {tenant_id: $tenant_id})-[r2]->(c)
    WHERE type(r2) <> 'MENTIONED_IN'
      AND type(r2) <> 'CO_OCCURS_IN_CORPUS'
      AND r2.evidence_context_ids IS NOT NULL
      AND size(r2.evidence_context_ids) > 0
    WITH c, doc_frequency, section_spread, total_mentions, low_tier_mentions,
         outgoing_relations, count(r2) AS incoming_relations

    RETURN c.canonical_id AS concept_id,
           c.canonical_name AS label,
           doc_frequency,
           section_spread,
           (outgoing_relations + incoming_relations) AS validated_relation_degree,
           total_mentions,
           low_tier_mentions,
           CASE WHEN total_mentions = 0 THEN 0.0
                ELSE toFloat(low_tier_mentions) / total_mentions
           END AS list_context_ratio
    """

    concepts = []
    with neo4j_client.driver.session(database=neo4j_client.database) as session:
        result = session.run(query, tenant_id=tenant_id)
        for record in result:
            concepts.append({
                "concept_id": record["concept_id"],
                "label": record["label"],
                "doc_frequency": record["doc_frequency"] or 0,
                "section_spread": record["section_spread"] or 0,
                "validated_relation_degree": record["validated_relation_degree"] or 0,
                "list_context_ratio": record["list_context_ratio"] or 0.0,
                "total_mentions": record["total_mentions"] or 0
            })

    return concepts


def compute_percentiles(concepts: List[Dict]) -> Tuple[float, float]:
    """
    Calcule les P95 pour normalisation.

    Returns:
        (p95_doc_frequency, p95_section_spread)
    """
    if not concepts:
        return (1.0, 1.0)

    doc_freqs = [c["doc_frequency"] for c in concepts if c["doc_frequency"] > 0]
    section_spreads = [c["section_spread"] for c in concepts if c["section_spread"] > 0]

    p95_doc = np.percentile(doc_freqs, 95) if doc_freqs else 1.0
    p95_section = np.percentile(section_spreads, 95) if section_spreads else 1.0

    return (max(1.0, p95_doc), max(1.0, p95_section))


def compute_hub_score(
    doc_frequency: int,
    section_spread: int,
    list_context_ratio: float,
    validated_relation_degree: int,
    p95_doc: float,
    p95_section: float
) -> float:
    """
    Calcule le hub_score selon la formule agnostique.

    Un hub_score élevé = concept très présent mais peu relationnel.
    """
    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    doc_norm = clamp01(doc_frequency / p95_doc)
    sec_norm = clamp01(section_spread / p95_section)
    list_ratio = clamp01(list_context_ratio)
    rel_norm = clamp01(validated_relation_degree / 5.0)

    # Formule: présence élevée + contexte liste - relations prouvées
    score = (
        0.40 * doc_norm +
        0.25 * sec_norm +
        0.35 * list_ratio -
        0.30 * rel_norm
    )

    return clamp01(score)


def update_concept_hub_score(
    neo4j_client,
    concept_id: str,
    stats: Dict,
    hub_score: float,
    is_hub: bool,
    tenant_id: str = "default"
) -> bool:
    """
    Met à jour les propriétés hub sur un concept.
    """
    query = """
    MATCH (c:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
    SET c.doc_frequency = $doc_frequency,
        c.section_spread = $section_spread,
        c.validated_relation_degree = $validated_relation_degree,
        c.list_context_ratio = $list_context_ratio,
        c.hub_score = $hub_score,
        c.is_hub = $is_hub
    RETURN c.canonical_id AS updated
    """

    try:
        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            result = session.run(
                query,
                concept_id=concept_id,
                tenant_id=tenant_id,
                doc_frequency=stats["doc_frequency"],
                section_spread=stats["section_spread"],
                validated_relation_degree=stats["validated_relation_degree"],
                list_context_ratio=stats["list_context_ratio"],
                hub_score=hub_score,
                is_hub=is_hub
            )
            return result.single() is not None
    except Exception as e:
        logger.error(f"[ComputeHubScore] Failed to update {concept_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Compute hub scores for CanonicalConcepts"
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
        help="Show hub concepts details"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=HUB_SCORE_THRESHOLD,
        help=f"Hub score threshold (default: {HUB_SCORE_THRESHOLD})"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("[ComputeHubScore] Starting hub score computation")
    logger.info(f"[ComputeHubScore] Tenant: {args.tenant_id}")
    logger.info(f"[ComputeHubScore] Hub threshold: {args.threshold}")
    logger.info(f"[ComputeHubScore] Dry-run: {args.dry_run}")
    logger.info("=" * 60)

    # Connexion Neo4j
    settings = get_settings()
    neo4j_client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    if not neo4j_client.is_connected():
        logger.error("[ComputeHubScore] Failed to connect to Neo4j")
        sys.exit(1)

    # Récupérer stats des concepts
    logger.info("[ComputeHubScore] Computing concept statistics...")
    concepts = compute_concept_stats(neo4j_client, args.tenant_id)
    logger.info(f"[ComputeHubScore] Found {len(concepts)} concepts")

    if not concepts:
        logger.warning("[ComputeHubScore] No concepts found, exiting")
        return

    # Calculer P95 pour normalisation
    p95_doc, p95_section = compute_percentiles(concepts)
    logger.info(f"[ComputeHubScore] P95 doc_frequency: {p95_doc:.1f}")
    logger.info(f"[ComputeHubScore] P95 section_spread: {p95_section:.1f}")

    # Calculer hub_score pour chaque concept
    hub_count = 0
    updated_count = 0
    hub_concepts = []

    for concept in concepts:
        hub_score = compute_hub_score(
            doc_frequency=concept["doc_frequency"],
            section_spread=concept["section_spread"],
            list_context_ratio=concept["list_context_ratio"],
            validated_relation_degree=concept["validated_relation_degree"],
            p95_doc=p95_doc,
            p95_section=p95_section
        )

        is_hub = hub_score >= args.threshold

        if is_hub:
            hub_count += 1
            hub_concepts.append({
                "label": concept["label"],
                "hub_score": hub_score,
                "doc_frequency": concept["doc_frequency"],
                "section_spread": concept["section_spread"],
                "list_context_ratio": concept["list_context_ratio"],
                "validated_relation_degree": concept["validated_relation_degree"]
            })

        if not args.dry_run:
            if update_concept_hub_score(
                neo4j_client,
                concept["concept_id"],
                concept,
                hub_score,
                is_hub,
                args.tenant_id
            ):
                updated_count += 1

    # Résumé
    logger.info("=" * 60)
    logger.info("[ComputeHubScore] COMPLETED")
    logger.info(f"[ComputeHubScore] Concepts processed: {len(concepts)}")
    logger.info(f"[ComputeHubScore] Concepts updated: {updated_count}")
    logger.info(f"[ComputeHubScore] Hub concepts identified: {hub_count} ({(hub_count/len(concepts))*100:.1f}%)")
    logger.info("=" * 60)

    # Afficher les hubs si verbose
    if args.verbose and hub_concepts:
        logger.info("[ComputeHubScore] Hub concepts (sorted by score):")
        hub_concepts.sort(key=lambda x: x["hub_score"], reverse=True)
        for h in hub_concepts[:20]:  # Top 20
            logger.info(
                f"  - {h['label'][:40]}: "
                f"score={h['hub_score']:.2f}, "
                f"docs={h['doc_frequency']}, "
                f"sections={h['section_spread']}, "
                f"list_ratio={h['list_context_ratio']:.2f}, "
                f"relations={h['validated_relation_degree']}"
            )


if __name__ == "__main__":
    main()
