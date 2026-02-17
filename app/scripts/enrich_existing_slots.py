#!/usr/bin/env python3
"""
Enrichissement rétroactif des structured_form manquants via LLM.

Charge les claims SANS structured_form depuis Neo4j, envoie des batches
au LLM pour extraire {subject, predicate, object}, et met à jour Neo4j.

Usage (dans le conteneur Docker) :
    python scripts/enrich_existing_slots.py --dry-run --tenant default --limit 100
    python scripts/enrich_existing_slots.py --execute --tenant default
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
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


def load_claims_without_sf(session, tenant_id: str, limit: int = 0) -> List[dict]:
    """Charge les claims SANS structured_form, avec leurs entities liées."""
    query = """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NULL
        OPTIONAL MATCH (c)-[:ABOUT]->(e:Entity)
        RETURN c.claim_id AS claim_id,
               c.text AS text,
               c.claim_type AS claim_type,
               c.doc_id AS doc_id,
               collect(e.name) AS entity_names
    """
    if limit > 0:
        query += f"\n        LIMIT {limit}"

    result = session.run(query, tenant_id=tenant_id)
    claims = []
    for record in result:
        claims.append({
            "claim_id": record["claim_id"],
            "text": record["text"],
            "claim_type": record["claim_type"] or "FACTUAL",
            "doc_id": record["doc_id"],
            "entity_names": record["entity_names"] or [],
        })
    return claims


def get_coverage_stats(session, tenant_id: str) -> dict:
    """Retourne les stats de couverture structured_form."""
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WITH count(c) AS total,
             sum(CASE WHEN c.structured_form_json IS NOT NULL THEN 1 ELSE 0 END) AS with_sf
        RETURN with_sf, total,
               CASE WHEN total > 0 THEN toFloat(with_sf)/total * 100 ELSE 0 END AS pct
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    if record:
        return {
            "total": record["total"],
            "with_sf": record["with_sf"],
            "pct": record["pct"],
        }
    return {"total": 0, "with_sf": 0, "pct": 0}


def update_claim_sf(session, claim_id: str, structured_form: dict, tenant_id: str) -> bool:
    """Met à jour le structured_form_json d'une claim."""
    result = session.run(
        """
        MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tenant_id})
        SET c.structured_form_json = $sf_json
        RETURN c.claim_id AS updated
        """,
        claim_id=claim_id,
        tenant_id=tenant_id,
        sf_json=json.dumps(structured_form),
    )
    record = result.single()
    return bool(record)


def main():
    parser = argparse.ArgumentParser(
        description="Enrichissement rétroactif des structured_form via LLM"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limiter le nombre de claims à traiter (0 = toutes)")
    parser.add_argument("--batch-size", type=int, default=15,
                        help="Taille des batches LLM (default: 15)")
    parser.add_argument("--max-concurrent", type=int, default=10,
                        help="Max appels LLM concurrents (default: 10)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    from knowbase.claimfirst.composition.slot_enricher import SlotEnricher

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Stats initiales
            logger.info(f"[OSMOSE] Stats de couverture initiales (tenant={args.tenant})...")
            before_stats = get_coverage_stats(session, args.tenant)
            logger.info(
                f"  → {before_stats['with_sf']}/{before_stats['total']} "
                f"claims avec structured_form ({before_stats['pct']:.1f}%)"
            )

            # 2. Charger les claims sans structured_form
            logger.info(f"[OSMOSE] Chargement des claims sans structured_form...")
            limit_msg = f" (limit={args.limit})" if args.limit else ""
            logger.info(f"  → {limit_msg}")

            claims = load_claims_without_sf(session, args.tenant, args.limit)
            logger.info(f"  → {len(claims)} claims chargées")

            if not claims:
                logger.info("Aucune claim sans structured_form à traiter.")
                return

            # Stats par document
            by_doc: Dict[str, int] = defaultdict(int)
            with_entities = 0
            for c in claims:
                by_doc[c["doc_id"]] += 1
                if c["entity_names"]:
                    with_entities += 1

            logger.info(f"  → {len(by_doc)} documents")
            logger.info(f"  → {with_entities}/{len(claims)} claims avec entities "
                        f"connues ({with_entities/len(claims)*100:.0f}%)")

            # Estimation
            n_batches = (len(claims) + args.batch_size - 1) // args.batch_size
            estimated_seconds = n_batches * 2 / min(args.max_concurrent, n_batches)
            logger.info(
                f"  → ~{n_batches} batches, ~{estimated_seconds:.0f}s estimées "
                f"(concurrence {args.max_concurrent})"
            )

            if args.dry_run:
                logger.info(f"\n{'='*60}")
                logger.info("RÉSUMÉ ENRICHISSEMENT (DRY-RUN)")
                logger.info(f"{'='*60}")
                logger.info(f"Claims sans SF      : {len(claims)}")
                logger.info(f"Batches nécessaires : {n_batches}")
                logger.info(f"Appels LLM estimés  : {n_batches}")
                logger.info(f"\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 3. Enrichir via LLM
            logger.info(f"\n[OSMOSE] Enrichissement LLM en cours...")
            enricher = SlotEnricher(
                batch_size=args.batch_size,
                max_concurrent=args.max_concurrent,
            )
            enriched = enricher.enrich_from_dicts(claims)

            logger.info(f"  → {len(enriched)} claims enrichies")

            # Stats enrichissement
            enricher_stats = enricher.get_stats()
            logger.info(f"  → LLM calls: {enricher_stats['llm_calls']}")
            logger.info(f"  → enriched: {enricher_stats['claims_enriched']}")
            logger.info(f"  → null: {enricher_stats['claims_null']}")
            logger.info(f"  → rejected: {enricher_stats['claims_rejected']}")

            # 4. Persister les résultats
            if enriched:
                logger.info(f"\n[OSMOSE] Mise à jour Neo4j ({len(enriched)} claims)...")
                updated = 0
                for item in enriched:
                    if update_claim_sf(
                        session, item["claim_id"], item["structured_form"], args.tenant
                    ):
                        updated += 1

                logger.info(f"  → {updated} claims mises à jour")

            # 5. Stats finales
            after_stats = get_coverage_stats(session, args.tenant)
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ ENRICHISSEMENT")
            logger.info(f"{'='*60}")
            logger.info(f"Avant  : {before_stats['with_sf']}/{before_stats['total']} "
                        f"({before_stats['pct']:.1f}%)")
            logger.info(f"Après  : {after_stats['with_sf']}/{after_stats['total']} "
                        f"({after_stats['pct']:.1f}%)")
            logger.info(f"Delta  : +{after_stats['with_sf'] - before_stats['with_sf']} claims")

            logger.info("\n[OSMOSE] Enrichissement terminé.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
