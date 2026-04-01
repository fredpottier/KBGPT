#!/usr/bin/env python3
"""
C4 Relations Evidence-First — Script de backfill complet.

Orchestre les 3 stages du pipeline C4 :
  Stage 1 : CandidateMiner  → mining paires candidates via embedding similarity
  Stage 2 : NLIAdjudicator  → adjudication LLM (Claude Haiku) avec seuils asymetriques
  Stage 3 : RelationPersister → persistance Neo4j avec preuves verbatim

Usage :
    python -m scripts.backfill_relations_c4 [--dry-run] [--cosine 0.85] [--max-pairs 5000]

Prerequis :
    - Neo4j avec claim_embedding vector index
    - Claims avec embeddings (backfill_claim_embeddings.py)
    - ANTHROPIC_API_KEY dans l'environnement
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

# Ajouter le parent pour import knowbase
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from neo4j import GraphDatabase

from knowbase.relations.candidate_miner_c4 import CandidateMinerC4
from knowbase.relations.nli_adjudicator import NLIAdjudicator
from knowbase.relations.relation_persister_c4 import RelationPersisterC4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Cree le driver Neo4j depuis les variables d'environnement."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def run_pipeline(
    *,
    tenant_id: str = "default",
    cosine_threshold: float = 0.85,
    max_pairs: int = 5000,
    max_workers: int = 3,
    dry_run: bool = False,
) -> dict:
    """Execute le pipeline C4 complet.

    Args:
        tenant_id: Identifiant du tenant
        cosine_threshold: Seuil cosine minimum pour mining
        max_pairs: Nombre max de paires candidates
        max_workers: Parallelisme pour l'adjudication LLM
        dry_run: Si True, ne persiste rien

    Returns:
        Dictionnaire de statistiques
    """
    start_total = time.time()
    driver = get_neo4j_driver()

    try:
        # ====================================================================
        # Stage 1 : Mining des paires candidates
        # ====================================================================
        logger.info("=" * 60)
        logger.info("STAGE 1 : Mining des paires candidates")
        logger.info("=" * 60)

        miner = CandidateMinerC4(driver, tenant_id=tenant_id)

        # Stats avant mining
        pre_stats = miner.get_mining_stats()
        logger.info(
            f"Corpus: {pre_stats['total_claims']} claims, "
            f"{pre_stats['total_docs']} docs, "
            f"{pre_stats['total_existing']} relations existantes"
        )

        pairs = miner.mine_candidates(
            cosine_threshold=cosine_threshold,
            max_neighbors=5,
            max_total_pairs=max_pairs,
            exclude_existing=True,
        )

        if not pairs:
            logger.warning("Aucune paire candidate trouvee. Fin.")
            return {"status": "no_candidates", "pairs": 0}

        logger.info(f"→ {len(pairs)} paires candidates a adjudiquer")

        # ====================================================================
        # Stage 2 : Adjudication NLI via LLM
        # ====================================================================
        logger.info("")
        logger.info("=" * 60)
        logger.info("STAGE 2 : Adjudication NLI (Claude Haiku)")
        logger.info("=" * 60)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY non definie. Impossible d'adjudiquer.")
            return {"status": "error", "error": "missing_api_key"}

        adjudicator = NLIAdjudicator(max_workers=max_workers)

        def on_adj_progress(done, total):
            logger.info(f"  Adjudication: {done}/{total} ({done*100//total}%)")

        results = adjudicator.adjudicate_batch(pairs, on_progress=on_adj_progress)

        if not results:
            logger.info("Aucune relation detectee apres adjudication. Fin.")
            return {
                "status": "no_relations",
                "pairs_mined": len(pairs),
                "relations_found": 0,
            }

        # Afficher les relations trouvees
        by_type = {}
        for r in results:
            by_type.setdefault(r.relation, []).append(r)

        logger.info(f"→ {len(results)} relations trouvees :")
        for rel_type, rels in sorted(by_type.items()):
            logger.info(f"  {rel_type}: {len(rels)}")
            for r in rels[:3]:  # Montrer les 3 premieres
                logger.info(
                    f"    [{r.confidence:.2f}] {r.doc_a_title[:30]} ↔ {r.doc_b_title[:30]}"
                )
                logger.info(f"      A: \"{r.evidence_a[:80]}\"")
                logger.info(f"      B: \"{r.evidence_b[:80]}\"")

        if dry_run:
            logger.info("\n[DRY RUN] Pas de persistance. Fin.")
            return {
                "status": "dry_run",
                "pairs_mined": len(pairs),
                "relations_found": len(results),
                "by_type": {k: len(v) for k, v in by_type.items()},
            }

        # ====================================================================
        # Stage 3 : Persistance Neo4j
        # ====================================================================
        logger.info("")
        logger.info("=" * 60)
        logger.info("STAGE 3 : Persistance Neo4j")
        logger.info("=" * 60)

        persister = RelationPersisterC4(driver, tenant_id=tenant_id)

        # Compteurs avant
        counts_before = persister.get_relation_counts()
        logger.info(f"Relations avant: {counts_before}")

        persist_stats = persister.persist_batch(results)

        # Compteurs apres
        counts_after = persister.get_relation_counts()
        logger.info(f"Relations apres: {counts_after}")

        # ====================================================================
        # Bilan
        # ====================================================================
        duration = time.time() - start_total
        logger.info("")
        logger.info("=" * 60)
        logger.info("BILAN C4 Relations Evidence-First")
        logger.info("=" * 60)
        logger.info(f"Duree totale: {duration:.1f}s")
        logger.info(f"Paires minees: {len(pairs)}")
        logger.info(f"Relations trouvees: {len(results)}")
        logger.info(f"  - Creees: {persist_stats.created}")
        logger.info(f"  - Mises a jour: {persist_stats.updated}")
        logger.info(f"  - Erreurs: {persist_stats.errors}")
        logger.info(f"Relations avant/apres:")
        for rtype in ["CONTRADICTS", "QUALIFIES", "REFINES"]:
            before = counts_before.get(rtype, 0)
            after = counts_after.get(rtype, 0)
            delta = after - before
            logger.info(f"  {rtype}: {before} → {after} (+{delta})")
        logger.info(
            f"  TOTAL: {counts_before.get('total', 0)} → {counts_after.get('total', 0)}"
        )

        # Sauvegarder le rapport
        report = {
            "timestamp": datetime.now().isoformat(),
            "duration_s": round(duration, 1),
            "config": {
                "cosine_threshold": cosine_threshold,
                "max_pairs": max_pairs,
                "max_workers": max_workers,
                "tenant_id": tenant_id,
            },
            "mining": {
                "corpus_claims": pre_stats["total_claims"],
                "corpus_docs": pre_stats["total_docs"],
                "pairs_mined": len(pairs),
            },
            "adjudication": {
                "relations_found": len(results),
                "by_type": {k: len(v) for k, v in by_type.items()},
            },
            "persistence": {
                "created": persist_stats.created,
                "updated": persist_stats.updated,
                "errors": persist_stats.errors,
            },
            "counts_before": counts_before,
            "counts_after": counts_after,
        }

        report_path = f"data/c4_relations_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("data", exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Rapport sauvegarde: {report_path}")

        return report

    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(
        description="C4 Relations Evidence-First — Backfill pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler sans persister les relations",
    )
    parser.add_argument(
        "--cosine",
        type=float,
        default=0.85,
        help="Seuil cosine minimum pour mining (default: 0.85)",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=5000,
        help="Nombre max de paires candidates (default: 5000)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=3,
        help="Parallelisme pour adjudication LLM (default: 3)",
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default="default",
        help="Tenant ID (default: default)",
    )

    args = parser.parse_args()

    logger.info("C4 Relations Evidence-First — Backfill")
    logger.info(f"Config: cosine={args.cosine}, max_pairs={args.max_pairs}, "
                f"workers={args.max_workers}, dry_run={args.dry_run}")

    report = run_pipeline(
        tenant_id=args.tenant,
        cosine_threshold=args.cosine,
        max_pairs=args.max_pairs,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
