"""
Run Corpus-Level Entity Resolution.

Usage:
    python scripts/run_corpus_er.py --dry-run      # Preview without merging
    python scripts/run_corpus_er.py                # Execute merges
    python scripts/run_corpus_er.py --limit 100    # Limit to 100 concepts
    python scripts/run_corpus_er.py --show-proposals  # Show pending proposals

Author: Claude Code
Date: 2026-01-01
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.consolidation import (
    CorpusERPipeline,
    CorpusERConfig,
    get_corpus_er_pipeline
)
from knowbase.consolidation.merge_store import get_merge_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_er(args):
    """Run Entity Resolution pipeline."""
    print("\n" + "=" * 60)
    print("  OSMOSE CORPUS ENTITY RESOLUTION")
    print("=" * 60)

    config = CorpusERConfig()

    # Adjust thresholds if requested
    if args.strict:
        config.lex_auto_threshold = 0.99
        config.sem_auto_threshold = 0.98
        print("  Mode: STRICT (higher thresholds)")
    elif args.lenient:
        config.lex_auto_threshold = 0.95
        config.lex_proposal_threshold = 0.80
        print("  Mode: LENIENT (lower thresholds)")
    else:
        print("  Mode: STANDARD")

    print(f"  Dry run: {args.dry_run}")
    print(f"  Limit: {args.limit or 'None'}")
    print(f"  Tenant: {args.tenant}")
    print("=" * 60 + "\n")

    pipeline = get_corpus_er_pipeline(tenant_id=args.tenant, config=config)

    try:
        stats = pipeline.run(dry_run=args.dry_run, limit=args.limit)

        print("\n" + "=" * 60)
        print("  RESULTS")
        print("=" * 60)
        print(f"  Concepts analyzed:    {stats.concepts_analyzed}")
        print(f"  Candidates found:     {stats.candidates_generated}")
        print(f"  Candidates scored:    {stats.candidates_scored}")
        print("-" * 60)
        print(f"  AUTO merges:          {stats.auto_merges}" +
              (" (dry run)" if args.dry_run else ""))
        print(f"  Proposals created:    {stats.proposals_created}")
        print(f"  Rejections:           {stats.rejections}")
        print("-" * 60)
        print(f"  Edges rewired:        {stats.edges_rewired}")
        print(f"  INSTANCE_OF rewired:  {stats.instance_of_rewired}")
        print(f"  Duration:             {stats.duration_ms:.0f}ms")

        if stats.errors:
            print("-" * 60)
            print(f"  Errors: {len(stats.errors)}")
            for err in stats.errors[:5]:
                print(f"    - {err[:80]}")

        print("=" * 60 + "\n")

        # Show pending proposals if any
        if stats.proposals_created > 0:
            print(f"  {stats.proposals_created} proposals created for manual review.")
            print("  Run with --show-proposals to see them.\n")

        return stats

    finally:
        pipeline.close()


def show_proposals(args):
    """Show pending merge proposals."""
    print("\n" + "=" * 60)
    print("  PENDING MERGE PROPOSALS")
    print("=" * 60 + "\n")

    store = get_merge_store(tenant_id=args.tenant)
    proposals = store.get_pending_proposals(limit=args.limit or 50)

    if not proposals:
        print("  No pending proposals.\n")
        return

    for i, p in enumerate(proposals, 1):
        print(f"  [{i}] {p['source_name'][:40]}")
        print(f"      → {p['target_name'][:40]}")
        print(f"      Scores: lex={p['lex_score']:.3f} sem={p['sem_score']:.3f}")
        print(f"      Reason: {p['reason']}")
        print(f"      ID: {p['proposal_id']}")
        print()

    print(f"  Total: {len(proposals)} pending proposals")
    print("=" * 60 + "\n")


def show_stats(args):
    """Show current merge statistics."""
    store = get_merge_store(tenant_id=args.tenant)
    stats = store.get_merge_stats()

    print("\n" + "=" * 60)
    print("  MERGE STATISTICS")
    print("=" * 60)
    print(f"  Total concepts:       {stats.get('total_concepts', 0)}")
    print(f"  Standalone:           {stats.get('standalone_concepts', 0)}")
    print(f"  Merged:               {stats.get('merged_concepts', 0)}")
    print(f"  Total proposals:      {stats.get('total_proposals', 0)}")
    print(f"  Applied proposals:    {stats.get('applied_proposals', 0)}")
    print("=" * 60 + "\n")


def analyze_duplicates(args):
    """Analyze duplicate concepts before running ER."""
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.config.settings import get_settings
    from knowbase.consolidation.lex_utils import compute_lex_key
    from collections import defaultdict

    print("\n" + "=" * 60)
    print("  DUPLICATE ANALYSIS (pre-ER)")
    print("=" * 60 + "\n")

    settings = get_settings()
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    try:
        # Get all concepts
        query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE c.er_status IS NULL OR c.er_status = 'STANDALONE'
        RETURN c.canonical_name AS name
        """

        with neo4j.driver.session(database="neo4j") as session:
            result = session.run(query, {"tenant_id": args.tenant})
            names = [r["name"] for r in result if r["name"]]

        # Group by lex_key
        groups = defaultdict(list)
        for name in names:
            key = compute_lex_key(name)
            groups[key].append(name)

        # Find duplicates
        duplicates = [(k, v) for k, v in groups.items() if len(v) > 1]
        duplicates.sort(key=lambda x: -len(x[1]))

        print(f"  Total concepts: {len(names)}")
        print(f"  Unique lex_keys: {len(groups)}")
        print(f"  Duplicate groups: {len(duplicates)}")
        print()

        if duplicates:
            print("  Top duplicate groups:")
            print("-" * 60)
            for key, names_list in duplicates[:20]:
                print(f"  [{len(names_list)}x] {key[:50]}")
                for name in names_list[:3]:
                    print(f"       • {name[:55]}")
                if len(names_list) > 3:
                    print(f"       ... +{len(names_list) - 3} more")
                print()

        print("=" * 60 + "\n")

    finally:
        neo4j.close()


def main():
    parser = argparse.ArgumentParser(
        description="Corpus-Level Entity Resolution",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--tenant", default="default", help="Tenant ID")
    parser.add_argument("--limit", type=int, help="Limit concepts to process")

    # Actions
    parser.add_argument("--dry-run", action="store_true",
                       help="Preview without executing merges")
    parser.add_argument("--show-proposals", action="store_true",
                       help="Show pending merge proposals")
    parser.add_argument("--stats", action="store_true",
                       help="Show merge statistics")
    parser.add_argument("--analyze", action="store_true",
                       help="Analyze duplicates before ER")

    # Threshold modes
    parser.add_argument("--strict", action="store_true",
                       help="Use stricter thresholds (fewer auto-merges)")
    parser.add_argument("--lenient", action="store_true",
                       help="Use lenient thresholds (more auto-merges)")

    args = parser.parse_args()

    if args.show_proposals:
        show_proposals(args)
    elif args.stats:
        show_stats(args)
    elif args.analyze:
        analyze_duplicates(args)
    else:
        run_er(args)


if __name__ == "__main__":
    main()
