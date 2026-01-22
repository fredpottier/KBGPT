#!/usr/bin/env python3
"""
Run Pass 2 on existing documents in Neo4j.

Usage:
    python scripts/run_pass2_on_existing.py --doc-id "022_Business-Scope..."
    python scripts/run_pass2_on_existing.py --sample 3  # Top 3 by concept count
    python scripts/run_pass2_on_existing.py --all
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
from knowbase.ingestion.pass2_orchestrator import (
    Pass2Orchestrator,
    Pass2Mode,
    Pass2Phase,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_documents(neo4j_client, tenant_id: str, sample: int = None) -> List[Dict[str, Any]]:
    """Get documents from Neo4j."""
    query = """
    MATCH (sc:SectionContext {tenant_id: $tenant_id})
    WITH sc.doc_id as doc_id, count(sc) as sections
    MATCH (pc:ProtoConcept {doc_id: doc_id, tenant_id: $tenant_id})
    WITH doc_id, sections, count(DISTINCT pc) as concepts
    WHERE concepts > 0
    RETURN doc_id, sections, concepts
    ORDER BY concepts DESC
    """

    if sample:
        query += f" LIMIT {sample}"

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, tenant_id=tenant_id)
        return [dict(r) for r in result]


def get_concepts_for_document(neo4j_client, doc_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """Get ProtoConcepts for a document."""
    query = """
    MATCH (pc:ProtoConcept {doc_id: $doc_id, tenant_id: $tenant_id})
    OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)
    RETURN
        pc.concept_id as id,
        pc.concept_name as name,
        COALESCE(cc.canonical_id, pc.concept_id) as canonical_id,
        COALESCE(cc.label, cc.canonical_name, pc.concept_name) as canonical_name,
        pc.concept_type as type_heuristic
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, doc_id=doc_id, tenant_id=tenant_id)
        return [dict(r) for r in result]


async def run_pass2_for_document(
    orchestrator: Pass2Orchestrator,
    doc_id: str,
    concepts: List[Dict[str, Any]],
    phases: List[Pass2Phase],
) -> Dict[str, Any]:
    """Run Pass 2 for a single document."""
    logger.info(f"Running Pass 2 for {doc_id} ({len(concepts)} concepts)")

    job = await orchestrator.schedule_pass2(
        document_id=doc_id,
        concepts=concepts,
        mode=Pass2Mode.INLINE,  # Execute immediately
        priority=1,
    )

    return {
        "doc_id": doc_id,
        "job_id": job.job_id,
        "concepts_count": len(concepts),
    }


async def main():
    parser = argparse.ArgumentParser(description="Run Pass 2 on existing documents")
    parser.add_argument("--doc-id", type=str, help="Specific document ID")
    parser.add_argument("--sample", type=int, default=1, help="Number of top documents to process")
    parser.add_argument("--all", action="store_true", help="Process all documents")
    parser.add_argument("--tenant", type=str, default="default", help="Tenant ID")
    parser.add_argument("--phases", type=str, default="enrich_relations",
                        help="Comma-separated phases: corpus_promotion,structural_topics,classify_fine,enrich_relations,semantic_consolidation")

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

    # Parse phases
    phase_names = [p.strip() for p in args.phases.split(",")]
    phases = [Pass2Phase(p) for p in phase_names]
    logger.info(f"Phases to run: {[p.value for p in phases]}")

    # Get documents
    if args.doc_id:
        documents = [{"doc_id": args.doc_id}]
    elif args.all:
        documents = get_documents(neo4j_client, args.tenant)
    else:
        documents = get_documents(neo4j_client, args.tenant, sample=args.sample)

    logger.info(f"Documents to process: {len(documents)}")

    # Initialize orchestrator with only the requested phases
    orchestrator = Pass2Orchestrator(tenant_id=args.tenant)
    orchestrator.enabled_phases = phases

    # Process each document
    results = []
    for doc in documents:
        doc_id = doc["doc_id"]

        # Get concepts for this document
        concepts = get_concepts_for_document(neo4j_client, doc_id, args.tenant)

        if not concepts:
            logger.warning(f"No concepts found for {doc_id}, skipping")
            continue

        result = await run_pass2_for_document(orchestrator, doc_id, concepts, phases)
        results.append(result)

    # Summary
    print("\n" + "=" * 70)
    print("PASS 2 EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Documents processed: {len(results)}")
    print(f"Phases executed: {[p.value for p in phases]}")

    # Check results in Neo4j
    print("\n" + "-" * 70)
    print("RESULTS IN NEO4J")
    print("-" * 70)

    with neo4j_client.driver.session(database="neo4j") as session:
        # RawAssertions by kind
        result = session.run("""
            MATCH (ra:RawAssertion {tenant_id: $tenant_id})
            RETURN ra.assertion_kind as kind, count(*) as cnt
            ORDER BY cnt DESC
        """, tenant_id=args.tenant)
        print("\nRawAssertion par assertion_kind:")
        for r in result:
            print(f"  {r['kind'] or 'NULL'}: {r['cnt']}")

        # RawAssertions DISCURSIVE by basis
        result = session.run("""
            MATCH (ra:RawAssertion {tenant_id: $tenant_id})
            WHERE ra.assertion_kind = "DISCURSIVE"
            RETURN ra.discursive_basis as basis, count(*) as cnt
            ORDER BY cnt DESC
        """, tenant_id=args.tenant)
        print("\nRawAssertion DISCURSIVE par basis:")
        for r in result:
            print(f"  {r['basis']}: {r['cnt']}")

        # SCOPE specific
        result = session.run("""
            MATCH (ra:RawAssertion {tenant_id: $tenant_id})
            WHERE ra.discursive_basis CONTAINS "SCOPE"
            RETURN ra.relation_type as rel_type, count(*) as cnt
            ORDER BY cnt DESC
        """, tenant_id=args.tenant)
        print("\nRelations SCOPE par type:")
        for r in result:
            print(f"  {r['rel_type']}: {r['cnt']}")

    print("\n" + "=" * 70)
    print("FIN")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
