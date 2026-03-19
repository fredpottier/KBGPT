#!/usr/bin/env python3
"""
backfill_facet_registry.py — Rétroactif pour les documents existants.

1. Lire tous les documents depuis Neo4j
2. Pour chaque doc : reconstruire DocumentContext, appeler FacetCandidateExtractor
3. Enregistrer dans FacetRegistry (accumulation cross-doc)
4. Persister les facettes (candidates + promues)
5. Ré-assigner les claims existantes aux facettes validées

Usage :
    docker compose exec app python app/scripts/backfill_facet_registry.py --dry-run
    docker compose exec app python app/scripts/backfill_facet_registry.py --execute
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] backfill_facets")


def get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def load_documents(session, tenant_id: str) -> list:
    """Charge tous les documents avec leurs claims depuis Neo4j."""
    result = session.run(
        """
        MATCH (d:Document {tenant_id: $tid})
        OPTIONAL MATCH (d)<-[:FROM]-(p:Passage)<-[:SUPPORTED_BY]-(c:Claim)
        WITH d, collect(DISTINCT c.text) AS claim_texts, count(DISTINCT c) AS claim_count
        RETURN d.doc_id AS doc_id,
               d.title AS title,
               d.summary AS summary,
               claim_texts[..10] AS sample_claims,
               claim_count
        ORDER BY claim_count DESC
        """,
        tid=tenant_id,
    )
    docs = []
    for r in result:
        docs.append({
            "doc_id": r["doc_id"],
            "title": r["title"] or r["doc_id"],
            "summary": r["summary"] or "",
            "sample_claims": [c for c in (r["sample_claims"] or []) if c],
            "claim_count": r["claim_count"] or 0,
        })
    return docs


def load_claims_for_doc(session, doc_id: str, tenant_id: str) -> list:
    """Charge les claim_ids d'un document."""
    result = session.run(
        """
        MATCH (c:Claim {doc_id: $did, tenant_id: $tid})
        RETURN c.claim_id AS claim_id, c.text AS text
        """,
        did=doc_id,
        tid=tenant_id,
    )
    return [{"claim_id": r["claim_id"], "text": r["text"]} for r in result]


def main():
    parser = argparse.ArgumentParser(description="Backfill Facet Registry")
    parser.add_argument(
        "--execute", action="store_true",
        help="Exécuter réellement (défaut: dry-run)"
    )
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--max-docs", type=int, default=0, help="Limiter le nombre de docs (0=tous)")
    args = parser.parse_args()

    dry_run = not args.execute
    tenant_id = args.tenant_id

    logger.info(f"Mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")
    logger.info(f"Tenant: {tenant_id}")

    driver = get_neo4j_driver()

    from knowbase.claimfirst.extractors.facet_candidate_extractor import (
        FacetCandidateExtractor,
    )
    from knowbase.claimfirst.linkers.facet_registry import FacetRegistry
    from knowbase.claimfirst.linkers.facet_matcher import FacetMatcher

    # Initialiser
    registry = FacetRegistry(tenant_id)
    registry.load_from_neo4j(driver)
    extractor = FacetCandidateExtractor()
    matcher = FacetMatcher()

    stats = {
        "docs_processed": 0,
        "total_candidates": 0,
        "facets_promoted": 0,
        "near_duplicates": 0,
        "claims_assigned": 0,
        "errors": 0,
    }

    start = time.time()

    with driver.session() as session:
        # 1. Charger les documents
        docs = load_documents(session, tenant_id)
        logger.info(f"Trouvé {len(docs)} documents")

        if args.max_docs > 0:
            docs = docs[:args.max_docs]
            logger.info(f"Limité à {len(docs)} documents")

        # 2. Extraire les facettes candidates par document
        for i, doc in enumerate(docs):
            try:
                logger.info(
                    f"[{i+1}/{len(docs)}] {doc['title'][:60]} "
                    f"({doc['claim_count']} claims)"
                )

                # Créer un mock DocumentContext minimal
                from unittest.mock import MagicMock
                doc_ctx = MagicMock()
                doc_ctx.doc_id = doc["doc_id"]
                doc_ctx.raw_subjects = [doc["title"]]

                # Créer des mock claims
                mock_claims = []
                for ct in doc["sample_claims"]:
                    mc = MagicMock()
                    mc.text = ct
                    mock_claims.append(mc)

                candidates = extractor.extract(
                    doc_context=doc_ctx,
                    claims=mock_claims,
                    doc_title=doc["title"],
                    doc_summary=doc["summary"],
                )

                stats["total_candidates"] += len(candidates)
                registry.register_candidates(candidates)

                for c in candidates:
                    logger.info(f"  → {c.dimension_key} ({c.facet_family}, conf={c.confidence:.2f})")

                stats["docs_processed"] += 1

            except Exception as e:
                logger.error(f"  ERREUR: {e}")
                stats["errors"] += 1

    # 3. Statistiques du registre
    reg_stats = registry.get_stats()
    stats["facets_promoted"] = reg_stats["by_lifecycle"].get("validated", 0)
    stats["near_duplicates"] = reg_stats["near_duplicates"]

    # 4. Afficher les near-duplicates
    dups = registry.get_near_duplicate_queue()
    if dups:
        logger.info(f"\n--- Near-Duplicates ({len(dups)}) ---")
        for k1, k2, score in dups[:20]:
            logger.info(f"  '{k1}' ≈ '{k2}' (score={score:.2f})")

    # 5. Afficher les facettes par lifecycle
    logger.info(f"\n--- Facettes par lifecycle ---")
    for lc in ["candidate", "validated", "deprecated"]:
        facets = [f for f in registry.get_all_facets() if f.lifecycle.value == lc]
        logger.info(f"  {lc}: {len(facets)}")
        for f in facets[:10]:
            logger.info(f"    {f.domain} ({f.facet_family.value}, docs={f.source_doc_count})")

    # 6. Ré-assigner les claims
    if not dry_run:
        logger.info("\n--- Ré-assignation des claims ---")
        validated = registry.get_validated_facets()
        logger.info(f"  {len(validated)} facettes validées disponibles")

        with driver.session() as session:
            # Persister le registre
            persisted = registry.persist_to_neo4j(driver)
            logger.info(f"  {persisted} facettes persistées dans Neo4j")

            # Ré-assigner les claims par document
            for doc in docs:
                claims_data = load_claims_for_doc(session, doc["doc_id"], tenant_id)
                if not claims_data:
                    continue

                # Mock claims pour le matcher
                mock_claims = []
                for cd in claims_data:
                    mc = MagicMock()
                    mc.claim_id = cd["claim_id"]
                    mc.text = cd["text"] or ""
                    mc.scope = None
                    mc.section_id = ""
                    mock_claims.append(mc)

                # Trouver les doc_facet_ids
                doc_facets = [
                    f.domain for f in registry.get_all_facets()
                    if doc["doc_id"] in f.source_doc_ids
                ]

                _, links = matcher.match(
                    claims=mock_claims,
                    tenant_id=tenant_id,
                    validated_facets=validated,
                    doc_facet_ids=doc_facets,
                )

                # Persister les liens
                from datetime import datetime, timezone
                now_iso = datetime.now(timezone.utc).isoformat()
                for claim_id, facet_id in links:
                    session.run(
                        """
                        MATCH (c:Claim {claim_id: $cid})
                        MATCH (f:Facet {facet_id: $fid})
                        MERGE (c)-[r:BELONGS_TO_FACET]->(f)
                        SET r.assigned_at = $now,
                            r.method = 'backfill_v1'
                        """,
                        cid=claim_id,
                        fid=facet_id,
                        now=now_iso,
                    )
                    stats["claims_assigned"] += 1

    elapsed = time.time() - start

    # Résumé final
    logger.info(f"\n{'='*60}")
    logger.info(f"BACKFILL FACET REGISTRY {'(DRY-RUN)' if dry_run else '(EXECUTED)'}")
    logger.info(f"{'='*60}")
    logger.info(f"  Documents traités:    {stats['docs_processed']}")
    logger.info(f"  Candidates extraites: {stats['total_candidates']}")
    logger.info(f"  Facettes promues:     {stats['facets_promoted']}")
    logger.info(f"  Near-duplicates:      {stats['near_duplicates']}")
    logger.info(f"  Claims assignées:     {stats['claims_assigned']}")
    logger.info(f"  Erreurs:              {stats['errors']}")
    logger.info(f"  Durée:                {elapsed:.1f}s")
    logger.info(f"{'='*60}")

    driver.close()


if __name__ == "__main__":
    main()
