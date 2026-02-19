#!/usr/bin/env python3
"""
Canonicalisation rétroactive des entities dans Neo4j via MergeArbiter.

Remplace l'ancienne approche rule-based par le MergeArbiter hybride :
1. Phase déterministe : prefix-dedup, case-only, version stripping
2. Phase LLM : corpus-grounded merge arbiter
3. Relations SIMILAR_TO pour les cas incertains
4. Annotation des hubs

Domain-agnostic (INV-25) : fonctionne pour tout domaine.

Usage (dans le conteneur Docker) :
    python scripts/canonicalize_existing_entities.py --dry-run --tenant default
    python scripts/canonicalize_existing_entities.py --execute --tenant default
    python scripts/canonicalize_existing_entities.py --execute --tenant default --batch-size 20
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def load_entities_with_context(
    session,
    tenant_id: str,
    limit: int = 0,
) -> tuple:
    """Charge entités + 1 claim excerpt par entité depuis Neo4j."""
    query = """
        MATCH (e:Entity {tenant_id: $tenant_id})
        OPTIONAL MATCH (e)<-[:ABOUT]-(c:Claim)
        WITH e, count(c) AS claim_count, collect(c.text)[0] AS sample_claim
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.normalized_name AS normalized_name,
               e.aliases AS aliases,
               e.entity_type AS entity_type,
               claim_count,
               sample_claim
        ORDER BY e.name
    """
    if limit > 0:
        query += f" LIMIT {limit}"

    result = session.run(query, tenant_id=tenant_id)

    entities: List[dict] = []
    claim_contexts: Dict[str, str] = {}
    for record in result:
        e = dict(record)
        entities.append(e)
        if e.get("sample_claim"):
            claim_contexts[e["entity_id"]] = e["sample_claim"]

    return entities, claim_contexts


def merge_entity_in_neo4j(session, source_id: str, target_id: str, tenant_id: str) -> None:
    """Fusionne source_entity dans target_entity dans Neo4j."""
    session.run(
        """
        MATCH (source:Entity {entity_id: $source_id, tenant_id: $tenant_id})
        MATCH (target:Entity {entity_id: $target_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (c:Claim)-[r:ABOUT]->(source)
        WITH source, target, collect(c) AS claims, collect(r) AS rels
        FOREACH (r IN rels | DELETE r)
        WITH source, target, claims
        UNWIND claims AS c
        MERGE (c)-[:ABOUT]->(target)
        WITH source, target
        SET target.aliases = CASE
            WHEN target.aliases IS NULL THEN [source.name]
            WHEN NOT source.name IN target.aliases THEN target.aliases + source.name
            ELSE target.aliases
        END
        WITH source, target
        DETACH DELETE source
        """,
        source_id=source_id,
        target_id=target_id,
        tenant_id=tenant_id,
    )


def create_similar_to(session, id1: str, id2: str, tenant_id: str,
                      confidence: float, reason: str, evidence: str) -> None:
    """Crée une relation SIMILAR_TO entre deux entités."""
    session.run(
        """
        MATCH (e1:Entity {entity_id: $id1, tenant_id: $tid})
        MATCH (e2:Entity {entity_id: $id2, tenant_id: $tid})
        MERGE (e1)-[r:SIMILAR_TO]->(e2)
        SET r.confidence = $confidence,
            r.reason = $reason,
            r.evidence = $evidence
        """,
        id1=id1,
        id2=id2,
        tid=tenant_id,
        confidence=confidence,
        reason=reason,
        evidence=evidence,
    )


def annotate_hubs(session, tenant_id: str, threshold: int = 50) -> int:
    """Annote les entities hub (>threshold claims ABOUT)."""
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})<-[:ABOUT]-(c:Claim)
        WITH e, count(c) AS degree
        WHERE degree > $threshold
        SET e.is_hub = true, e.hub_degree = degree
        RETURN count(e) AS hubs_annotated
        """,
        tenant_id=tenant_id,
        threshold=threshold,
    )
    record = result.single()
    return record["hubs_annotated"] if record else 0


def main():
    parser = argparse.ArgumentParser(
        description="Canonicalisation rétroactive des entities Neo4j via MergeArbiter"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limite d'entités à charger (0 = toutes)")
    parser.add_argument("--batch-size", type=int, default=15,
                        help="Taille batch LLM (default: 15)")
    parser.add_argument("--hub-threshold", type=int, default=50,
                        help="Seuil de claims pour annoter un hub (default: 50)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Charger entités + contexte
            logger.info(f"[OSMOSE] Chargement des entities (tenant={args.tenant})...")
            entities, claim_contexts = load_entities_with_context(
                session, args.tenant, limit=args.limit,
            )
            logger.info(f"  → {len(entities)} entities chargées, "
                        f"{len(claim_contexts)} avec contexte claim")

            if not entities:
                logger.info("Aucune entity à traiter.")
                return

            # 2. MergeArbiter resolve
            from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter

            logger.info("[OSMOSE] Exécution du MergeArbiter...")
            arbiter = MergeArbiter(batch_size=args.batch_size, max_concurrent=3)
            merge_result = arbiter.resolve(entities, claim_contexts)

            # 3. Afficher le résumé
            stats = merge_result.stats
            all_merges = merge_result.deterministic_merges + merge_result.llm_merges

            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ CANONICALISATION (MergeArbiter)")
            logger.info(f"{'='*60}")
            logger.info(f"Entities initiales     : {len(entities)}")
            logger.info(f"Prefix dedup           : {stats['prefix_dedup']}")
            logger.info(f"Case-only              : {stats['case_only']}")
            logger.info(f"Version stripping      : {stats['version_strip']}")
            logger.info(f"LLM merges             : {stats['llm_merge']}")
            logger.info(f"LLM distinct           : {stats['llm_distinct']}")
            logger.info(f"LLM similar (soft-link): {stats['llm_similar']}")
            logger.info(f"Total fusions          : {len(all_merges)}")
            logger.info(f"Relations SIMILAR_TO    : {len(merge_result.similar_pairs)}")

            # Afficher les merges
            for merge in all_merges[:20]:
                logger.info(
                    f"  MERGE [{merge.rule}]: {merge.source_ids} → "
                    f"'{merge.canonical_name}' ({merge.target_id})"
                )
            if len(all_merges) > 20:
                logger.info(f"  ... et {len(all_merges) - 20} autres")

            # Afficher les SIMILAR_TO
            for pair in merge_result.similar_pairs[:10]:
                logger.info(
                    f"  SIMILAR: {pair.entity_id_1} ↔ {pair.entity_id_2} "
                    f"({pair.reason})"
                )

            if args.dry_run:
                logger.info(f"\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 4. Appliquer les merges
            if all_merges:
                logger.info(f"\n[OSMOSE] Application des fusions...")
                merged_count = 0
                for merge in all_merges:
                    for source_id in merge.source_ids:
                        merge_entity_in_neo4j(
                            session, source_id, merge.target_id, args.tenant,
                        )
                        merged_count += 1
                logger.info(f"  → {merged_count} entities fusionnées")

            # 5. Créer les relations SIMILAR_TO
            if merge_result.similar_pairs:
                logger.info(f"\n[OSMOSE] Création des relations SIMILAR_TO...")
                similar_count = 0
                for pair in merge_result.similar_pairs:
                    create_similar_to(
                        session,
                        pair.entity_id_1,
                        pair.entity_id_2,
                        args.tenant,
                        pair.confidence,
                        pair.reason,
                        pair.evidence,
                    )
                    similar_count += 1
                logger.info(f"  → {similar_count} relations SIMILAR_TO créées")

            # 6. Annoter les hubs
            logger.info(f"\n[OSMOSE] Annotation des hubs (seuil: {args.hub_threshold})...")
            hubs = annotate_hubs(session, args.tenant, args.hub_threshold)
            logger.info(f"  → {hubs} entities annotées comme hubs")

            logger.info("\n[OSMOSE] Canonicalisation terminée.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
