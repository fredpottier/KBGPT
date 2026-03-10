#!/usr/bin/env python3
"""
Audit Dimension Quality — Analyse la santé du registre QuestionDimension.

Usage:
    docker exec knowbase-app python scripts/audit_dimension_quality.py --tenant-id default

Produit un rapport avec :
- Dimensions healthy / needs_review / should_split
- Paires candidates au merge (cosine > 0.85)
- Suggestions de scope_policy
"""

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Audit dimension quality")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--no-embeddings", action="store_true",
                        help="Skip embedding-based merge detection")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of text")
    args = parser.parse_args()

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.models.question_dimension import QuestionDimension
    from knowbase.claimfirst.extractors.dimension_governance import (
        DimensionAuditor, AuditReport
    )

    client = get_neo4j_client()

    # 1. Charger le registre
    logger.info("Loading dimension registry...")
    cypher_dims = """
    MATCH (qd:QuestionDimension {tenant_id: $tid})
    RETURN qd
    """
    with client.driver.session(database=client.database) as session:
        result = session.run(cypher_dims, tid=args.tenant_id)
        registry = []
        for record in result:
            node = record["qd"]
            props = dict(node)
            registry.append(QuestionDimension.from_neo4j_record(props))

    logger.info(f"Loaded {len(registry)} dimensions")

    # 2. Charger les données QS par dimension
    logger.info("Loading QS data per dimension...")
    cypher_qs = """
    MATCH (qs:QuestionSignature {tenant_id: $tid})
    RETURN qs.dimension_id AS dimension_id,
           collect(qs.extracted_value) AS values,
           collect(qs.scope_anchor_label) AS scopes,
           collect(qs.doc_id) AS doc_ids
    """
    qs_data = {}
    with client.driver.session(database=client.database) as session:
        result = session.run(cypher_qs, tid=args.tenant_id)
        for record in result:
            dim_id = record["dimension_id"]
            qs_data[dim_id] = {
                "values": [v for v in record["values"] if v],
                "scopes": [s for s in record["scopes"] if s],
                "doc_ids": [d for d in record["doc_ids"] if d],
            }

    # 3. Audit
    auditor = DimensionAuditor(use_embeddings=not args.no_embeddings)
    report = auditor.full_audit(registry, qs_data)

    # 4. Output
    if args.json:
        output = {
            "total_dimensions": report.total_dimensions,
            "healthy": report.healthy_count,
            "needs_review": report.needs_review_count,
            "should_split": report.should_split_count,
            "merge_pairs": [
                {"dim_a": a, "dim_b": b, "similarity": round(s, 3)}
                for a, b, s in report.merge_pairs
            ],
            "scope_policy_suggestions": report.scope_policy_suggestions,
            "dimension_reports": [
                {
                    "dimension_id": r.dimension_id,
                    "dimension_key": r.dimension_key,
                    "qs_count": r.qs_count,
                    "doc_count": r.doc_count,
                    "distinct_values": r.distinct_values,
                    "distinct_scopes": r.distinct_scopes,
                    "health_status": r.health_status,
                    "split_suggestion": r.split_suggestion,
                }
                for r in report.dimension_reports
                if r.health_status != "healthy"
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'='*60}")
        print(f"DIMENSION QUALITY AUDIT — tenant={args.tenant_id}")
        print(f"{'='*60}\n")
        print(f"Total dimensions:  {report.total_dimensions}")
        print(f"  Healthy:         {report.healthy_count}")
        print(f"  Needs review:    {report.needs_review_count}")
        print(f"  Should split:    {report.should_split_count}")
        print(f"  Merge pairs:     {len(report.merge_pairs)}")
        print()

        if report.should_split_count > 0:
            print("--- SHOULD SPLIT ---")
            for r in report.dimension_reports:
                if r.health_status == "should_split":
                    print(f"  [{r.dimension_key}] {r.qs_count} QS, "
                          f"{r.distinct_values} values, {r.distinct_scopes} scopes")
                    if r.split_suggestion:
                        for s in r.split_suggestion:
                            print(f"    → {s}")
            print()

        if report.needs_review_count > 0:
            print("--- NEEDS REVIEW ---")
            for r in report.dimension_reports:
                if r.health_status == "needs_review":
                    print(f"  [{r.dimension_key}] {r.qs_count} QS, "
                          f"{r.distinct_values} values, {r.distinct_scopes} scopes")
            print()

        if report.merge_pairs:
            print("--- MERGE CANDIDATES ---")
            dim_by_id = {d.dimension_id: d for d in registry}
            for a_id, b_id, sim in report.merge_pairs:
                a = dim_by_id.get(a_id)
                b = dim_by_id.get(b_id)
                a_key = a.dimension_key if a else a_id
                b_key = b.dimension_key if b else b_id
                print(f"  [{a_key}] ↔ [{b_key}] (cosine={sim:.3f})")
            print()

        if report.scope_policy_suggestions:
            print("--- SCOPE POLICY SUGGESTIONS ---")
            for s in report.scope_policy_suggestions:
                print(f"  [{s['dimension_key']}] → {s['suggested_policy']}")
                print(f"    {s['reason']}")
            print()


if __name__ == "__main__":
    main()
