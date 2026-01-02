"""
Setup script for Corpus Consolidation infrastructure.

Creates:
- Index on CanonicalConcept.lex_key
- Index on CanonicalConcept.er_status
- Constraint on MergeProposal.proposal_id

Author: Claude Code
Date: 2026-01-01
"""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def setup_indices(neo4j: Neo4jClient) -> None:
    """Create indices for corpus consolidation."""

    indices = [
        # lex_key for fast blocking
        (
            "idx_canonical_lex_key",
            "CREATE INDEX idx_canonical_lex_key IF NOT EXISTS FOR (c:CanonicalConcept) ON (c.lex_key)"
        ),
        # er_status for filtering active concepts
        (
            "idx_canonical_er_status",
            "CREATE INDEX idx_canonical_er_status IF NOT EXISTS FOR (c:CanonicalConcept) ON (c.er_status)"
        ),
        # merged_into_id for rollback queries
        (
            "idx_canonical_merged_into",
            "CREATE INDEX idx_canonical_merged_into IF NOT EXISTS FOR (c:CanonicalConcept) ON (c.merged_into_id)"
        ),
        # MergeProposal indices
        (
            "idx_proposal_tenant",
            "CREATE INDEX idx_proposal_tenant IF NOT EXISTS FOR (p:MergeProposal) ON (p.tenant_id)"
        ),
        (
            "idx_proposal_applied",
            "CREATE INDEX idx_proposal_applied IF NOT EXISTS FOR (p:MergeProposal) ON (p.applied)"
        ),
    ]

    with neo4j.driver.session(database="neo4j") as session:
        for name, query in indices:
            try:
                session.run(query)
                logger.info(f"[Setup] Created index: {name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"[Setup] Index already exists: {name}")
                else:
                    logger.warning(f"[Setup] Failed to create index {name}: {e}")


def setup_constraints(neo4j: Neo4jClient) -> None:
    """Create constraints for corpus consolidation."""

    constraints = [
        # Unique proposal_id
        (
            "constraint_proposal_id",
            "CREATE CONSTRAINT constraint_proposal_id IF NOT EXISTS FOR (p:MergeProposal) REQUIRE p.proposal_id IS UNIQUE"
        ),
    ]

    with neo4j.driver.session(database="neo4j") as session:
        for name, query in constraints:
            try:
                session.run(query)
                logger.info(f"[Setup] Created constraint: {name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"[Setup] Constraint already exists: {name}")
                else:
                    logger.warning(f"[Setup] Failed to create constraint {name}: {e}")


def initialize_er_status(neo4j: Neo4jClient, tenant_id: str = "default") -> int:
    """Initialize er_status to STANDALONE for concepts that don't have it."""

    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c.er_status IS NULL
    SET c.er_status = 'STANDALONE'
    RETURN count(c) AS updated
    """

    with neo4j.driver.session(database="neo4j") as session:
        result = session.run(query, {"tenant_id": tenant_id})
        record = result.single()
        updated = record["updated"] if record else 0
        logger.info(f"[Setup] Initialized er_status for {updated} concepts")
        return updated


def compute_missing_lex_keys(neo4j: Neo4jClient, tenant_id: str = "default") -> int:
    """Compute lex_key for concepts that don't have it."""
    from knowbase.consolidation.lex_utils import compute_lex_key

    # Get concepts without lex_key
    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c.lex_key IS NULL AND c.canonical_name IS NOT NULL
    RETURN c.canonical_id AS id, c.canonical_name AS name
    LIMIT 1000
    """

    with neo4j.driver.session(database="neo4j") as session:
        result = session.run(query, {"tenant_id": tenant_id})
        concepts = [dict(r) for r in result]

    if not concepts:
        logger.info("[Setup] All concepts have lex_key")
        return 0

    # Compute lex_keys
    updates = []
    for c in concepts:
        lex_key = compute_lex_key(c["name"])
        updates.append({"id": c["id"], "lex_key": lex_key})

    # Batch update
    update_query = """
    UNWIND $updates AS u
    MATCH (c:CanonicalConcept {canonical_id: u.id, tenant_id: $tenant_id})
    SET c.lex_key = u.lex_key
    """

    with neo4j.driver.session(database="neo4j") as session:
        session.run(update_query, {"updates": updates, "tenant_id": tenant_id})

    logger.info(f"[Setup] Computed lex_key for {len(updates)} concepts")
    return len(updates)


def show_stats(neo4j: Neo4jClient, tenant_id: str = "default") -> None:
    """Show current corpus consolidation stats."""

    query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WITH count(c) AS total,
         sum(CASE WHEN c.er_status = 'STANDALONE' OR c.er_status IS NULL THEN 1 ELSE 0 END) AS standalone,
         sum(CASE WHEN c.er_status = 'MERGED' THEN 1 ELSE 0 END) AS merged,
         sum(CASE WHEN c.lex_key IS NOT NULL THEN 1 ELSE 0 END) AS with_lex_key

    OPTIONAL MATCH (p:MergeProposal {tenant_id: $tenant_id})
    WITH total, standalone, merged, with_lex_key,
         count(p) AS proposals,
         sum(CASE WHEN p.applied THEN 1 ELSE 0 END) AS applied

    RETURN total, standalone, merged, with_lex_key, proposals, applied
    """

    with neo4j.driver.session(database="neo4j") as session:
        result = session.run(query, {"tenant_id": tenant_id})
        record = result.single()

        if record:
            print("\n" + "=" * 50)
            print("  CORPUS CONSOLIDATION STATS")
            print("=" * 50)
            print(f"  Total concepts:     {record['total']}")
            print(f"  Standalone:         {record['standalone']}")
            print(f"  Merged:             {record['merged']}")
            print(f"  With lex_key:       {record['with_lex_key']}")
            print(f"  Merge proposals:    {record['proposals']}")
            print(f"  Applied proposals:  {record['applied']}")
            print("=" * 50 + "\n")


def main():
    """Run setup."""
    import argparse

    parser = argparse.ArgumentParser(description="Setup Corpus Consolidation")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    parser.add_argument("--skip-lex-keys", action="store_true",
                       help="Skip lex_key computation (can be slow)")
    args = parser.parse_args()

    settings = get_settings()
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    try:
        print("\n[1/5] Creating indices...")
        setup_indices(neo4j)

        print("\n[2/5] Creating constraints...")
        setup_constraints(neo4j)

        print("\n[3/5] Initializing er_status...")
        initialize_er_status(neo4j, args.tenant)

        if not args.skip_lex_keys:
            print("\n[4/5] Computing lex_keys...")
            # Run in batches until done
            total = 0
            while True:
                updated = compute_missing_lex_keys(neo4j, args.tenant)
                total += updated
                if updated < 1000:  # Less than batch size = done
                    break
            print(f"       Total lex_keys computed: {total}")
        else:
            print("\n[4/5] Skipping lex_key computation")

        print("\n[5/5] Stats:")
        show_stats(neo4j, args.tenant)

        print("Setup complete!")

    finally:
        neo4j.close()


if __name__ == "__main__":
    main()
