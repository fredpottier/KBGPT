#!/usr/bin/env python3
"""
Extraction des QuestionSignatures Level A sur le corpus existant.

Lit toutes les claims depuis Neo4j, applique les patterns regex Level A,
et persiste les QuestionSignatures en tant que nœuds Neo4j.

Usage:
    python app/scripts/extract_question_signatures.py --dry-run   # Prévisualisation
    python app/scripts/extract_question_signatures.py              # Exécution réelle
    python app/scripts/extract_question_signatures.py --tenant-id acme
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stub claim pour l'extracteur (qui attend .claim_id, .text, .structured_form)
# ---------------------------------------------------------------------------

class _ClaimRecord:
    """Proxy léger pour les records Neo4j."""

    __slots__ = ("claim_id", "text", "doc_id", "structured_form")

    def __init__(self, claim_id: str, text: str, doc_id: str,
                 structured_form: Optional[Dict[str, Any]] = None):
        self.claim_id = claim_id
        self.text = text
        self.doc_id = doc_id
        self.structured_form = structured_form or {}


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def _fetch_claims_by_doc(tenant_id: str) -> Dict[str, List[_ClaimRecord]]:
    """Lit toutes les claims non-archivées groupées par doc_id."""
    from neo4j import GraphDatabase
    from knowbase.config.settings import get_settings

    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    query = """
    MATCH (c:Claim {tenant_id: $tid})
    WHERE NOT coalesce(c.archived, false)
      AND c.text IS NOT NULL
      AND size(c.text) >= 20
    RETURN c.claim_id AS claim_id,
           c.text AS text,
           c.doc_id AS doc_id,
           c.structured_form AS structured_form
    ORDER BY c.doc_id
    """

    claims_by_doc: Dict[str, List[_ClaimRecord]] = defaultdict(list)

    with driver.session() as session:
        result = session.run(query, tid=tenant_id)
        for record in result:
            sf = record["structured_form"]
            # Neo4j peut stocker comme string JSON
            if isinstance(sf, str):
                import json
                try:
                    sf = json.loads(sf)
                except (json.JSONDecodeError, TypeError):
                    sf = {}
            claims_by_doc[record["doc_id"]].append(_ClaimRecord(
                claim_id=record["claim_id"],
                text=record["text"],
                doc_id=record["doc_id"],
                structured_form=sf or {},
            ))

    driver.close()
    return claims_by_doc


def _persist_question_signatures(qs_list: list, tenant_id: str) -> int:
    """Persiste les QuestionSignatures dans Neo4j."""
    from neo4j import GraphDatabase
    from knowbase.config.settings import get_settings

    if not qs_list:
        return 0

    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    # Créer constraint si elle n'existe pas
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (qs:QuestionSignature) "
            "REQUIRE qs.qs_id IS UNIQUE"
        )

    # MERGE les nœuds QS + relation vers la Claim source
    merge_query = """
    UNWIND $batch AS props
    MERGE (qs:QuestionSignature {qs_id: props.qs_id})
    SET qs += props,
        qs.tenant_id = $tid
    WITH qs, props
    MATCH (c:Claim {claim_id: props.claim_id, tenant_id: $tid})
    MERGE (qs)-[:EXTRACTED_FROM]->(c)
    """

    batch = [qs.to_neo4j_properties() for qs in qs_list]
    created = 0

    with driver.session() as session:
        # Batch par 200
        for i in range(0, len(batch), 200):
            chunk = batch[i:i + 200]
            session.run(merge_query, batch=chunk, tid=tenant_id)
            created += len(chunk)

    driver.close()
    return created


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extraire les QuestionSignatures Level A depuis le corpus Neo4j"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Mode prévisualisation (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter réellement la persistence")
    parser.add_argument("--tenant-id", default="default",
                        help="Tenant ID (défaut: 'default')")
    args = parser.parse_args()

    dry_run = not args.execute

    logger.info(f"[OSMOSE:QS] Mode: {'DRY-RUN' if dry_run else 'EXÉCUTION'}")
    logger.info(f"[OSMOSE:QS] Tenant: {args.tenant_id}")

    # 1. Lire les claims
    logger.info("[OSMOSE:QS] Lecture des claims depuis Neo4j...")
    claims_by_doc = _fetch_claims_by_doc(args.tenant_id)
    total_claims = sum(len(v) for v in claims_by_doc.values())
    logger.info(f"[OSMOSE:QS] {total_claims} claims dans {len(claims_by_doc)} documents")

    # 2. Extraire les QS Level A
    from knowbase.claimfirst.extractors.question_signature_extractor import (
        extract_question_signatures_level_a,
    )

    all_qs = []
    stats_by_doc: Dict[str, int] = {}
    dim_key_counts: Dict[str, int] = defaultdict(int)

    for doc_id, claims in claims_by_doc.items():
        qs_list = extract_question_signatures_level_a(
            claims, doc_id, tenant_id=args.tenant_id
        )
        all_qs.extend(qs_list)
        stats_by_doc[doc_id] = len(qs_list)
        for qs in qs_list:
            dim_key_counts[qs.dimension_key] += 1

    logger.info(f"[OSMOSE:QS] Total: {len(all_qs)} QuestionSignatures Level A")
    logger.info(f"[OSMOSE:QS] Documents avec QS: {sum(1 for v in stats_by_doc.values() if v > 0)}/{len(claims_by_doc)}")

    # 3. Audit — top dimension_keys
    logger.info("[OSMOSE:QS] === Top dimension_keys ===")
    for dim_key, count in sorted(dim_key_counts.items(), key=lambda x: -x[1])[:20]:
        logger.info(f"  {dim_key}: {count}")

    # 4. Exemples
    logger.info("[OSMOSE:QS] === Exemples (5 premiers) ===")
    for qs in all_qs[:5]:
        logger.info(
            f"  [{qs.dimension_key}] {qs.extracted_value} "
            f"(claim={qs.claim_id[:30]}, doc={qs.doc_id[:30]})"
        )
        logger.info(f"    Q: {qs.question}")

    # 5. Persister si pas dry-run
    if dry_run:
        logger.info(f"[OSMOSE:QS] DRY-RUN terminé. {len(all_qs)} QS seraient créées.")
        logger.info("[OSMOSE:QS] Relancer avec --execute pour persister.")
    else:
        logger.info(f"[OSMOSE:QS] Persistence de {len(all_qs)} QS dans Neo4j...")
        created = _persist_question_signatures(all_qs, args.tenant_id)
        logger.info(f"[OSMOSE:QS] {created} QuestionSignatures persistées.")


if __name__ == "__main__":
    main()
