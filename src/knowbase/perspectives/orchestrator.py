# src/knowbase/perspectives/orchestrator.py
"""
Orchestrateur batch pour la construction des Perspectives.

Usage :
    python -m knowbase.perspectives.orchestrator [--tenant default] [--dry-run] [--skip-llm]
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Dict, List

from .builder import build_perspectives_for_subject, collect_claims_for_subject
from .models import PerspectiveConfig
from .persister import delete_perspectives_for_subject, persist_perspectives

logger = logging.getLogger(__name__)


def _get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def _get_eligible_subjects(driver, tenant_id: str, min_claims: int = 10) -> List[Dict]:
    """Recupere les sujets eligibles (>= min_claims)."""
    with driver.session() as session:
        # SubjectAnchors
        result = session.run("""
            MATCH (sa:SubjectAnchor)<-[:ABOUT_SUBJECT]-(dc:DocumentContext)
            RETURN sa.subject_id AS subject_id,
                   sa.canonical_name AS name,
                   'SubjectAnchor' AS subject_type,
                   collect(DISTINCT dc.doc_id) AS doc_ids
        """)
        sa_rows = [dict(r) for r in result]

        # Claim count par doc_id
        result = session.run("""
            MATCH (c:Claim {tenant_id: $tid})
            RETURN c.doc_id AS doc_id, count(c) AS cnt
        """, tid=tenant_id)
        claims_per_doc = {r["doc_id"]: r["cnt"] for r in result}

    subjects = []
    seen_names = set()
    for row in sa_rows:
        claim_count = sum(claims_per_doc.get(did, 0) for did in row["doc_ids"])
        if claim_count >= min_claims and row["name"] not in seen_names:
            seen_names.add(row["name"])
            subjects.append({
                "subject_id": row["subject_id"],
                "name": row["name"],
                "claim_count": claim_count,
                "doc_count": len(row["doc_ids"]),
            })

    return sorted(subjects, key=lambda s: -s["claim_count"])


async def run_perspective_engine(
    tenant_id: str = "default",
    dry_run: bool = False,
    skip_llm: bool = False,
    config: PerspectiveConfig = PerspectiveConfig(),
    max_subjects: int = 20,
) -> Dict:
    """
    Execute le pipeline Perspective pour tous les sujets eligibles.

    Args:
        tenant_id: Tenant ID
        dry_run: Si True, ne pas persister
        skip_llm: Si True, ne pas labelliser (debug clustering)
        config: Configuration du builder
        max_subjects: Nombre max de sujets a traiter

    Returns:
        Stats globales
    """
    start = time.time()
    driver = _get_neo4j_driver()

    logger.info(f"{'='*60}")
    logger.info(f"PERSPECTIVE ENGINE — {'DRY RUN' if dry_run else 'PRODUCTION'}")
    logger.info(f"{'='*60}")
    logger.info(f"Tenant: {tenant_id}")
    logger.info(f"Config: facet_weight={config.facet_weight}, embedding_weight={config.embedding_weight}")
    logger.info(f"Skip LLM: {skip_llm}")

    # 1. Sujets eligibles
    subjects = _get_eligible_subjects(driver, tenant_id, config.min_subject_claims)
    subjects = subjects[:max_subjects]
    logger.info(f"Sujets eligibles: {len(subjects)}")

    global_stats = {
        "subjects_processed": 0,
        "perspectives_total": 0,
        "claims_linked_total": 0,
        "subjects_skipped": 0,
        "errors": 0,
    }

    for i, subj in enumerate(subjects):
        logger.info(f"\n[{i+1}/{len(subjects)}] {subj['name']} ({subj['claim_count']} claims, {subj['doc_count']} docs)")

        try:
            # Build
            perspectives, claim_assignments = await build_perspectives_for_subject(
                driver, tenant_id,
                subj["subject_id"], subj["name"],
                config=config, skip_llm=skip_llm,
            )

            if not perspectives:
                global_stats["subjects_skipped"] += 1
                continue

            # Log les perspectives
            for p in perspectives:
                logger.info(
                    f"  [{p.label}] {p.claim_count} claims, {p.doc_count} docs, "
                    f"{p.tension_count} tensions, coverage={p.coverage_ratio:.1%}"
                )

            # Persist
            if not dry_run:
                delete_perspectives_for_subject(driver, tenant_id, subj["subject_id"])
                stats = persist_perspectives(
                    driver, tenant_id, subj["subject_id"],
                    perspectives, claim_assignments,
                )
                global_stats["claims_linked_total"] += stats["claims_linked"]

            global_stats["subjects_processed"] += 1
            global_stats["perspectives_total"] += len(perspectives)

        except Exception as e:
            logger.error(f"  ERREUR: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            global_stats["errors"] += 1

    elapsed = time.time() - start
    logger.info(f"\n{'='*60}")
    logger.info(f"TERMINE en {elapsed:.1f}s")
    logger.info(f"Sujets traites: {global_stats['subjects_processed']}")
    logger.info(f"Perspectives creees: {global_stats['perspectives_total']}")
    logger.info(f"Claims lies: {global_stats['claims_linked_total']}")
    logger.info(f"Sujets skip: {global_stats['subjects_skipped']}")
    logger.info(f"Erreurs: {global_stats['errors']}")

    driver.close()
    return global_stats


def main():
    """Point d'entree CLI."""
    import argparse
    parser = argparse.ArgumentParser(description="OSMOSIS Perspective Engine")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-llm", action="store_true", help="Debug: skip LLM labelling")
    parser.add_argument("--facet-weight", type=float, default=0.5)
    parser.add_argument("--embedding-weight", type=float, default=0.5)
    parser.add_argument("--max-subjects", type=int, default=20)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = PerspectiveConfig(
        facet_weight=args.facet_weight,
        embedding_weight=args.embedding_weight,
    )

    asyncio.run(run_perspective_engine(
        tenant_id=args.tenant,
        dry_run=args.dry_run,
        skip_llm=args.skip_llm,
        config=config,
        max_subjects=args.max_subjects,
    ))


if __name__ == "__main__":
    main()
