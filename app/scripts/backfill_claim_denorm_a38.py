"""Backfill A3.8-prep — Dénormaliser structured_form_json → props directes.

Cf doc/ongoing/POST_A38_ROOT_CAUSE_AUDIT_2026-05-21.md §6.

Pour les 4488 claims existants ayant `structured_form_json`, parse le JSON et
écrit en propriétés directes :
- `subject_canonical` = structured_form.subject
- `predicate` = structured_form.predicate
- `object_canonical` = structured_form.object

Idempotent : safe à relancer (ON CREATE/ON MATCH semantics via SET conditionnel).

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/backfill_claim_denorm_a38.py --dry-run'
    docker exec knowbase-app sh -c 'cd /app && python scripts/backfill_claim_denorm_a38.py --commit'
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill_claim_denorm_a38")


def main():
    parser = argparse.ArgumentParser(description="Backfill subject/predicate/object props on :Claim")
    parser.add_argument("--commit", action="store_true",
                        help="Actually write to Neo4j (default: dry-run)")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    dry_run = not args.commit
    mode = "DRY-RUN" if dry_run else "COMMIT"
    logger.info("Mode: %s | tenant=%s | batch=%d", mode, args.tenant_id, args.batch_size)

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    client = get_neo4j_client()

    # 1) Count target claims
    r = client.execute_query(
        """
        MATCH (c:Claim {tenant_id: $tid})
        WHERE c.structured_form_json IS NOT NULL
        RETURN count(c) AS n_total,
               count(c.subject_canonical) AS n_already_done
        """,
        tid=args.tenant_id,
    )
    n_total = r[0]["n_total"]
    n_already = r[0]["n_already_done"]
    n_todo = n_total - n_already
    logger.info(
        "Claims with structured_form_json: %d total, %d already denormalized, %d to backfill",
        n_total, n_already, n_todo,
    )
    if n_todo == 0:
        logger.info("Nothing to do. Exiting.")
        return 0

    # 2) Batches
    processed = 0
    skipped_invalid_json = 0
    skipped_no_fields = 0
    updated = 0

    while processed < n_todo:
        # Pick claims not yet backfilled
        rows = client.execute_query(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.structured_form_json IS NOT NULL
              AND c.subject_canonical IS NULL
            RETURN c.claim_id AS claim_id, c.structured_form_json AS sfj
            LIMIT $limit
            """,
            tid=args.tenant_id,
            limit=args.batch_size,
        )
        if not rows:
            break

        batch_updates: List[Dict[str, Any]] = []
        for row in rows:
            try:
                sf = json.loads(row["sfj"])
            except Exception as exc:
                skipped_invalid_json += 1
                logger.debug("Skip %s: invalid JSON (%s)", row["claim_id"], exc)
                continue

            update = {"claim_id": row["claim_id"]}
            if sf.get("subject"):
                update["subject_canonical"] = sf["subject"]
            if sf.get("predicate"):
                update["predicate"] = sf["predicate"]
            if sf.get("object"):
                update["object_canonical"] = sf["object"]

            if len(update) == 1:  # only claim_id, no useful fields
                skipped_no_fields += 1
                continue

            batch_updates.append(update)

        if not batch_updates:
            processed += len(rows)
            continue

        if dry_run:
            logger.info(
                "Would write batch of %d (sample claim_id=%s, props=%s)",
                len(batch_updates),
                batch_updates[0]["claim_id"],
                {k: v for k, v in batch_updates[0].items() if k != "claim_id"},
            )
        else:
            # Write batch
            client.execute_query(
                """
                UNWIND $batch AS row
                MATCH (c:Claim {claim_id: row.claim_id})
                SET c.subject_canonical = row.subject_canonical,
                    c.predicate = row.predicate,
                    c.object_canonical = row.object_canonical
                """,
                batch=batch_updates,
            )

        updated += len(batch_updates)
        processed += len(rows)
        logger.info(
            "Progress: %d processed / %d todo | updated=%d skipped_invalid=%d skipped_empty=%d",
            processed, n_todo, updated, skipped_invalid_json, skipped_no_fields,
        )

    # 3) Verify
    r2 = client.execute_query(
        """
        MATCH (c:Claim {tenant_id: $tid})
        WHERE c.structured_form_json IS NOT NULL
        RETURN
          count(c) AS total,
          count(c.subject_canonical) AS has_subject,
          count(c.predicate) AS has_predicate,
          count(c.object_canonical) AS has_object
        """,
        tid=args.tenant_id,
    )
    stats = r2[0]
    logger.info(
        "%s done. Total claims with structured_form_json=%d | subject=%d | predicate=%d | object=%d",
        mode, stats["total"], stats["has_subject"], stats["has_predicate"], stats["has_object"],
    )
    if not dry_run:
        logger.info(
            "Coverage final: subject %.1f%% / predicate %.1f%% / object %.1f%%",
            (stats["has_subject"] / stats["total"]) * 100,
            (stats["has_predicate"] / stats["total"]) * 100,
            (stats["has_object"] / stats["total"]) * 100,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
