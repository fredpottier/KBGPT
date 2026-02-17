#!/usr/bin/env python3
"""
Détection rétroactive des chaînes S/P/O sur les claims existantes dans Neo4j.

Pour chaque document, si claim_A.object == claim_B.subject (normalisé),
crée une relation CHAINS_TO entre les deux claims.

Usage (dans le conteneur Docker) :
    python scripts/detect_existing_chains.py --dry-run --tenant default
    python scripts/detect_existing_chains.py --execute --tenant default
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


def load_claims_with_sf(session, tenant_id: str) -> List[dict]:
    """Charge les claims avec structured_form depuis Neo4j."""
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NOT NULL
        RETURN c.claim_id AS claim_id,
               c.doc_id AS doc_id,
               c.structured_form_json AS structured_form_json,
               c.confidence AS confidence
        ORDER BY c.doc_id
        """,
        tenant_id=tenant_id,
    )
    claims = []
    for record in result:
        try:
            sf = json.loads(record["structured_form_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        claims.append({
            "claim_id": record["claim_id"],
            "doc_id": record["doc_id"],
            "structured_form": sf,
            "confidence": record["confidence"] or 0.5,
        })
    return claims


def count_existing_chains(session, tenant_id: str) -> int:
    """Compte les relations CHAINS_TO existantes."""
    result = session.run(
        """
        MATCH (c1:Claim {tenant_id: $tenant_id})-[r:CHAINS_TO]->(c2:Claim)
        RETURN count(r) AS chain_count
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["chain_count"] if record else 0


def persist_chain(session, link, tenant_id: str) -> bool:
    """Persiste un ChainLink comme edge CHAINS_TO dans Neo4j."""
    result = session.run(
        """
        MATCH (c1:Claim {claim_id: $source_id, tenant_id: $tenant_id})
        MATCH (c2:Claim {claim_id: $target_id, tenant_id: $tenant_id})
        MERGE (c1)-[r:CHAINS_TO]->(c2)
        SET r.confidence = 1.0,
            r.basis = $basis,
            r.join_key = $join_key,
            r.method = 'spo_join',
            r.derived = true,
            r.join_key_freq = $freq
        RETURN r IS NOT NULL AS created
        """,
        source_id=link.source_claim_id,
        target_id=link.target_claim_id,
        tenant_id=tenant_id,
        basis=f"join_key={link.join_key}",
        join_key=link.join_key,
        freq=link.join_key_freq,
    )
    record = result.single()
    return bool(record and record["created"])


def main():
    parser = argparse.ArgumentParser(
        description="Détection rétroactive des chaînes S/P/O dans Neo4j"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--max-edges-per-key", type=int, default=10,
                        help="Max edges par join_key par document (default: 10)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    from knowbase.claimfirst.composition.chain_detector import ChainDetector

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Charger les claims avec structured_form
            logger.info(f"[OSMOSE] Chargement des claims avec structured_form "
                        f"(tenant={args.tenant})...")
            claims = load_claims_with_sf(session, args.tenant)
            logger.info(f"  → {len(claims)} claims avec structured_form")

            if not claims:
                logger.info("Aucune claim avec structured_form à traiter.")
                return

            # Stats par document
            by_doc: Dict[str, int] = defaultdict(int)
            for c in claims:
                by_doc[c["doc_id"]] += 1
            logger.info(f"  → {len(by_doc)} documents")
            for doc_id, count in sorted(by_doc.items()):
                logger.info(f"    {doc_id}: {count} claims")

            # 2. Détecter les chaînes
            logger.info(f"\n[OSMOSE] Détection des chaînes (max_edges_per_key="
                        f"{args.max_edges_per_key})...")
            detector = ChainDetector(max_edges_per_key=args.max_edges_per_key)
            links = detector.get_chain_links_from_dicts(claims)
            logger.info(f"  → {len(links)} chaînes détectées")

            # Stats
            stats = detector.get_stats()
            logger.info(f"  → claims_with_sf: {stats['claims_with_sf']}")
            logger.info(f"  → docs_processed: {stats['docs_processed']}")
            logger.info(f"  → join_keys_found: {stats['join_keys_found']}")
            logger.info(f"  → join_keys_capped: {stats['join_keys_capped']}")

            # Détails des chaînes
            chains_by_doc: Dict[str, int] = defaultdict(int)
            join_keys_used: Dict[str, int] = defaultdict(int)
            for link in links:
                chains_by_doc[link.doc_id] += 1
                join_keys_used[link.join_key] += 1

            logger.info(f"\n  Chaînes par document:")
            for doc_id, count in sorted(chains_by_doc.items(),
                                          key=lambda x: x[1], reverse=True):
                logger.info(f"    {doc_id}: {count}")

            logger.info(f"\n  Top join_keys:")
            for jk, count in sorted(join_keys_used.items(),
                                     key=lambda x: x[1], reverse=True)[:20]:
                logger.info(f"    '{jk}': {count} edges")

            # Métriques qualité
            total_edges = len(links)
            unique_join_keys = len(join_keys_used)
            if total_edges > 0:
                ratio = unique_join_keys / total_edges
                logger.info(f"\n  Ratio join_keys/edges: {ratio:.3f}")
                if ratio < 0.1:
                    logger.warning("  ⚠ Concentration excessive de join_keys")

                top3_edges = sum(
                    count for _, count in sorted(
                        join_keys_used.items(), key=lambda x: x[1], reverse=True
                    )[:3]
                )
                top3_pct = top3_edges / total_edges * 100
                logger.info(f"  Top-3 join_keys: {top3_pct:.1f}% des edges")
                if top3_pct > 50:
                    logger.warning("  ⚠ Top-3 join_keys représentent >50% des edges")

            # 3. Compter les CHAINS_TO existantes
            existing = count_existing_chains(session, args.tenant)
            logger.info(f"\n  CHAINS_TO existantes: {existing}")

            # 4. Résumé
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ DÉTECTION DE CHAÎNES")
            logger.info(f"{'='*60}")
            logger.info(f"Claims avec SF    : {len(claims)}")
            logger.info(f"Documents traités : {len(by_doc)}")
            logger.info(f"Chaînes détectées : {len(links)}")
            logger.info(f"CHAINS_TO existantes: {existing}")
            logger.info(f"Nouvelles à créer   : {len(links)}")

            if args.dry_run:
                logger.info("\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 5. Persister les chaînes
            logger.info(f"\n[OSMOSE] Persistance des {len(links)} chaînes...")
            persisted = 0
            for link in links:
                if persist_chain(session, link, args.tenant):
                    persisted += 1

            logger.info(f"  → {persisted} edges CHAINS_TO créés/mis à jour")

            # Vérification finale
            final_count = count_existing_chains(session, args.tenant)
            logger.info(f"  → Total CHAINS_TO après persistance: {final_count}")

            logger.info("\n[OSMOSE] Détection de chaînes terminée.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
