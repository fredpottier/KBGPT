#!/usr/bin/env python3
"""
Dry-run du candidate gating + scope resolver sur le corpus Neo4j.

Usage:
    docker exec knowbase-app python scripts/dryrun_qs_gating.py --sample 500
    docker exec knowbase-app python scripts/dryrun_qs_gating.py  # Toutes les claims
"""

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] dryrun_qs_gating")


@dataclass
class SimpleClaim:
    claim_id: str
    text: str
    doc_id: str
    claim_type: Optional[str] = None
    structured_form: Optional[Dict] = None


def load_claims(client, tenant_id: str, sample: int = 0) -> List[SimpleClaim]:
    """Charge les claims avec structured_form et entités ABOUT."""
    query = """
    MATCH (c:Claim {tenant_id: $tenant_id})
    OPTIONAL MATCH (c)-[:ABOUT]->(e)
    WITH c, collect(DISTINCT e.name) AS entity_names
    RETURN c.claim_id AS claim_id,
           c.text AS text,
           c.claim_type AS claim_type,
           c.doc_id AS doc_id,
           c.structured_form_json AS structured_form_json,
           entity_names
    """
    if sample > 0:
        query += f" LIMIT {sample}"

    with client.driver.session(database=client.database) as session:
        result = session.run(query, tenant_id=tenant_id)
        records = [dict(r) for r in result]

    claims = []
    for rec in records:
        # Reconstruire structured_form avec les entités
        sf = None
        sf_json = rec.get("structured_form_json")
        if sf_json:
            try:
                sf = json.loads(sf_json) if isinstance(sf_json, str) else sf_json
            except (json.JSONDecodeError, TypeError):
                sf = None

        # Injecter les entités ABOUT dans structured_form
        entity_names = rec.get("entity_names") or []
        if entity_names:
            if sf is None:
                sf = {}
            sf["entities"] = [{"name": n} for n in entity_names if n]

        claims.append(SimpleClaim(
            claim_id=rec["claim_id"],
            text=rec.get("text") or "",
            doc_id=rec.get("doc_id") or "",
            claim_type=rec.get("claim_type"),
            structured_form=sf,
        ))
    return claims


def main(sample: int = 0, tenant_id: str = "default"):
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.extractors.comparability_gate import candidate_gate
    from knowbase.claimfirst.extractors.scope_resolver import resolve_scope

    client = get_neo4j_client()
    claims = load_claims(client, tenant_id, sample)
    logger.info("Claims chargées: %d", len(claims))

    retained_count = 0
    signal_counter = Counter()
    rejection_counter = Counter()
    scope_status_counter = Counter()
    example_retained = []

    for claim in claims:
        gating = candidate_gate(claim)

        if gating.retained:
            retained_count += 1
            for sig in gating.signals:
                signal_counter[sig] += 1

            scope = resolve_scope(claim=claim)
            scope_status_counter[scope.scope_status] += 1

            if len(example_retained) < 5:
                example_retained.append((claim.text[:100], gating.signals))
        else:
            rejection_counter[gating.rejection_reason or "unknown"] += 1

    # Rapport
    total = len(claims)
    logger.info("=" * 60)
    logger.info("RAPPORT GATING")
    logger.info("=" * 60)
    logger.info("Total claims: %d", total)
    logger.info("Retenues: %d (%.1f%%)", retained_count, 100 * retained_count / max(total, 1))
    logger.info("Rejetées: %d (%.1f%%)", total - retained_count, 100 * (total - retained_count) / max(total, 1))

    logger.info("\nDistribution signaux:")
    for sig, count in signal_counter.most_common():
        logger.info("  %s: %d", sig, count)

    logger.info("\nRaisons de rejet:")
    for reason, count in rejection_counter.most_common():
        logger.info("  %s: %d", reason, count)

    logger.info("\nDistribution scope_status (claims retenues):")
    for status, count in scope_status_counter.most_common():
        logger.info("  %s: %d", status, count)

    if example_retained:
        logger.info("\nExemples de claims retenues:")
        for text, signals in example_retained:
            logger.info("  [%s] %s", ", ".join(signals), text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dry-run QS gating")
    parser.add_argument("--sample", type=int, default=0, help="Limiter à N claims (0=tout)")
    parser.add_argument("--tenant-id", type=str, default="default")
    args = parser.parse_args()

    main(sample=args.sample, tenant_id=args.tenant_id)
