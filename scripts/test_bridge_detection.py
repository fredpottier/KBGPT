#!/usr/bin/env python3
"""
Test bridge detection dans SCOPE mining.

Ce script analyse les candidats générés par le SCOPE miner
et affiche les stats sur la présence de bridge spans.

Usage:
    python scripts/test_bridge_detection.py --sample 5
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.config.settings import get_settings
from knowbase.relations.scope_candidate_miner import (
    ScopeCandidateMiner,
    get_mining_stats,
)
from knowbase.relations.types import ScopeMiningConfig, EvidenceSpanRole

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_sections_with_concepts(neo4j_client, tenant_id: str, limit: int = 5) -> List[str]:
    """Récupère les sections avec le plus de concepts."""
    query = """
    MATCH (sc:SectionContext {tenant_id: $tenant_id})
    MATCH (sc)-[:CONTAINS]->(di:DocItem)
    MATCH (pc:ProtoConcept)-[:ANCHORED_IN]->(di)
    WITH sc.context_id as section_id, count(DISTINCT pc) as concept_count
    WHERE concept_count >= 3
    RETURN section_id, concept_count
    ORDER BY concept_count DESC
    LIMIT $limit
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, tenant_id=tenant_id, limit=limit)
        return [(r["section_id"], r["concept_count"]) for r in result]


def main():
    parser = argparse.ArgumentParser(description="Test bridge detection")
    parser.add_argument("--sample", type=int, default=5, help="Nombre de sections à analyser")
    parser.add_argument("--tenant", type=str, default="default", help="Tenant ID")
    args = parser.parse_args()

    # Connect to Neo4j
    settings = get_settings()
    neo4j_client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database="neo4j"
    )

    if not neo4j_client.is_connected():
        logger.error("Cannot connect to Neo4j")
        return

    # Récupère les sections
    sections = get_sections_with_concepts(neo4j_client, args.tenant, args.sample)
    logger.info(f"Sections à analyser: {len(sections)}")

    # Initialise le miner
    config = ScopeMiningConfig()
    miner = ScopeCandidateMiner(
        neo4j_driver=neo4j_client.driver,
        config=config,
        tenant_id=args.tenant,
    )

    # Stats globales
    total_candidates = 0
    total_with_bridge = 0
    total_without_bridge = 0

    # Mine chaque section
    for section_id, concept_count in sections:
        result = miner.mine_section(section_id)

        section_with_bridge = 0
        section_without_bridge = 0

        for candidate in result.candidates:
            bundle = candidate.evidence_bundle
            if bundle.has_bridge:
                section_with_bridge += 1
            else:
                section_without_bridge += 1

        total_candidates += len(result.candidates)
        total_with_bridge += section_with_bridge
        total_without_bridge += section_without_bridge

        logger.info(
            f"Section {section_id[:40]}... ({concept_count} concepts): "
            f"{len(result.candidates)} candidates, "
            f"WITH_BRIDGE: {section_with_bridge}, "
            f"NO_BRIDGE: {section_without_bridge}"
        )

    # Résumé
    print("\n" + "=" * 70)
    print("BRIDGE DETECTION STATS")
    print("=" * 70)
    print(f"Sections analysées: {len(sections)}")
    print(f"Candidats totaux: {total_candidates}")
    print(f"  - Avec BRIDGE (A+B ensemble): {total_with_bridge} ({100*total_with_bridge/max(1,total_candidates):.1f}%)")
    print(f"  - Sans BRIDGE (A et B séparés): {total_without_bridge} ({100*total_without_bridge/max(1,total_candidates):.1f}%)")
    print("=" * 70)

    if total_with_bridge > 0:
        print("\n✅ La détection de bridge fonctionne!")
        print("   Les candidats AVEC bridge seront vérifiés par le LLM.")
        print("   Les candidats SANS bridge seront ABSTAIN (économie de tokens).")
    else:
        print("\n⚠️ Aucun bridge détecté!")
        print("   Vérifiez les données: les concepts sont peut-être dans des DocItems séparés.")


if __name__ == "__main__":
    main()
