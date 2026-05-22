"""A4.3 — Backfill subject_canonical sur 7134 claims orphelins.

Parcourt MATCH (c:Claim) WHERE c.subject_canonical IS NULL, appelle
SubjectIndexer (Qwen2.5-14B-AWQ via vLLM burst) pour chaque, et update
Neo4j en batch UNWIND.

Idempotent : par défaut skip les claims déjà processés (avec subject_canonical
ou marginal=True). Resume support natif.

Parallélisme : ThreadPoolExecutor avec MAX_WORKERS workers concurrent.
vLLM burst gère plusieurs requests concurrent → ~5-8x speedup vs sequential.

Estimation : ~7134 / 4 workers × 1.9s = ~3400s = ~55 min.

Usage:
    # Run complet (background recommandé)
    docker exec knowbase-app sh -c 'cd /app && python scripts/backfill_subject_canonical_a43.py'

    # Dry-run (1 claim, vérifie le flow sans écrire en KG)
    docker exec knowbase-app sh -c 'cd /app && python scripts/backfill_subject_canonical_a43.py --dry-run --limit 1'

    # Limit pour test rapide
    docker exec knowbase-app sh -c 'cd /app && python scripts/backfill_subject_canonical_a43.py --limit 100'
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill_a43")


# Parallélisme : vLLM burst supporte plusieurs concurrent.
# Trop élevé = risque de saturation / OOM côté burst.
MAX_WORKERS = 4

# Taille des batches d'update Neo4j (UNWIND)
NEO4J_BATCH_SIZE = 100

# Sauvegarde incrémentale des résultats tous les N claims
CHECKPOINT_EVERY = 200


def fetch_null_claims(neo4j, limit: int | None = None) -> List[Dict[str, Any]]:
    """Charge les claims sans subject_canonical."""
    cypher = """
    MATCH (c:Claim {tenant_id: 'default'})
    WHERE c.subject_canonical IS NULL
      AND c.marginal IS NULL
    RETURN c.claim_id AS claim_id,
           coalesce(c.text, c.verbatim_quote, '') AS text,
           c.claim_type AS claim_type
    """
    if limit is not None and limit > 0:
        cypher += f" LIMIT {limit}"
    return neo4j.execute_query(cypher)


def update_claims_batch(neo4j, batch: List[Dict[str, Any]]) -> None:
    """Update batch via UNWIND pour perf."""
    if not batch:
        return
    neo4j.execute_query(
        """
        UNWIND $batch AS row
        MATCH (c:Claim {claim_id: row.claim_id, tenant_id: 'default'})
        SET c.subject_canonical = row.subject_canonical,
            c.marginal = row.marginal,
            c.subject_extraction_confidence = row.confidence
        """,
        batch=batch,
    )


def process_one_claim(claim: Dict[str, Any], indexer) -> Dict[str, Any]:
    """Indexe un claim. Retourne dict prêt pour batch update Neo4j."""
    result = indexer.index_one(claim["claim_id"], claim["text"])
    return {
        "claim_id": claim["claim_id"],
        "subject_canonical": result.subject,  # None si marginal
        "marginal": result.marginal,
        "confidence": result.confidence,
        "_failure_reason": result.failure_reason,
        "_duration_s": result.duration_s,
    }


def main():
    parser = argparse.ArgumentParser(description="A4.3 backfill subject_canonical")
    parser.add_argument("--limit", type=int, default=None, help="Limit total claims processed")
    parser.add_argument("--dry-run", action="store_true", help="Pas d'update Neo4j (juste mesure)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="Concurrent workers")
    args = parser.parse_args()

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.subject_indexer import SubjectIndexer

    neo = get_neo4j_client()
    indexer = SubjectIndexer()

    print("\n" + "=" * 80)
    print(f"A4.3 BACKFILL subject_canonical — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)
    print(f"  Workers           : {args.workers}")
    print(f"  Dry-run           : {args.dry_run}")
    print(f"  Limit             : {args.limit or 'no limit'}")
    print(f"  Neo4j batch size  : {NEO4J_BATCH_SIZE}")
    print(f"  Checkpoint every  : {CHECKPOINT_EVERY}")

    # 1. Fetch
    print("\n[1/3] Loading NULL claims...")
    t0 = time.perf_counter()
    claims = fetch_null_claims(neo, args.limit)
    print(f"  → {len(claims)} claims to process in {time.perf_counter()-t0:.1f}s")

    if not claims:
        print("\n✅ Aucun claim à traiter (subject_canonical déjà rempli ou marginal=True).")
        return 0

    # 2. Process en parallèle
    print(f"\n[2/3] Processing {len(claims)} claims with {args.workers} workers...")
    t_start = time.perf_counter()
    all_results: List[Dict[str, Any]] = []
    update_batch: List[Dict[str, Any]] = []
    n_done = 0
    n_extracted = 0
    n_marginal = 0
    n_errors = 0

    # Output dir pour checkpoints
    out_dir = Path("/app/data/benchmark/a43_backfill")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    checkpoint_file = out_dir / f"backfill_{ts}.jsonl"

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_one_claim, c, indexer): c for c in claims}

        with open(checkpoint_file, "w", encoding="utf-8") as cp_f:
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    all_results.append(res)
                    cp_f.write(json.dumps(res, ensure_ascii=False) + "\n")

                    if res["subject_canonical"]:
                        n_extracted += 1
                    elif res["marginal"]:
                        n_marginal += 1
                    if res.get("_failure_reason"):
                        n_errors += 1

                    update_batch.append({
                        "claim_id": res["claim_id"],
                        "subject_canonical": res["subject_canonical"],
                        "marginal": res["marginal"],
                        "confidence": res["confidence"],
                    })

                    n_done += 1

                    # Flush batch tous les NEO4J_BATCH_SIZE
                    if len(update_batch) >= NEO4J_BATCH_SIZE:
                        if not args.dry_run:
                            update_claims_batch(neo, update_batch)
                        update_batch = []

                    # Progress
                    if n_done % CHECKPOINT_EVERY == 0:
                        elapsed = time.perf_counter() - t_start
                        rate = n_done / elapsed
                        eta = (len(claims) - n_done) / rate if rate > 0 else 0
                        print(
                            f"  [{n_done}/{len(claims)}] "
                            f"elapsed={elapsed:.0f}s rate={rate:.1f}/s eta={eta:.0f}s "
                            f"extracted={n_extracted} marginal={n_marginal} errors={n_errors}"
                        )
                        cp_f.flush()
                except Exception as exc:
                    logger.exception("Worker failed")
                    n_errors += 1

    # Flush dernier batch
    if update_batch and not args.dry_run:
        update_claims_batch(neo, update_batch)

    total_dur = time.perf_counter() - t_start

    # 3. Stats finales + verification garde-fou
    print(f"\n[3/3] Final stats")
    print(f"  Duration            : {total_dur:.0f}s ({total_dur/60:.1f}min)")
    print(f"  Avg latency / claim : {total_dur/max(n_done,1):.2f}s")
    print(f"  Total processed     : {n_done}/{len(claims)}")
    print(f"  Subjects extracted  : {n_extracted}/{n_done} ({n_extracted/max(n_done,1):.0%})")
    print(f"  Flagged marginal    : {n_marginal}/{n_done} ({n_marginal/max(n_done,1):.0%})")
    print(f"  Errors              : {n_errors}/{n_done}")

    # Garde-fou final : count NULL post-backfill (target < 5%)
    if not args.dry_run:
        print(f"\n[GUARDRAIL] Re-checking KG coverage...")
        coverage_rows = neo.execute_query(
            """
            MATCH (c:Claim {tenant_id: 'default'})
            RETURN
              count(c) AS total,
              count(CASE WHEN c.subject_canonical IS NOT NULL THEN 1 END) AS n_subject,
              count(CASE WHEN c.marginal = true THEN 1 END) AS n_marginal,
              count(CASE WHEN c.subject_canonical IS NULL AND (c.marginal IS NULL OR c.marginal = false) THEN 1 END) AS n_orphan
            """,
        )
        cov = coverage_rows[0]
        total = cov["total"]
        coverage_pct = cov["n_subject"] / total
        orphan_pct = cov["n_orphan"] / total
        print(f"  Total claims        : {total}")
        print(f"  Has subject_canonical: {cov['n_subject']} ({coverage_pct:.1%})")
        print(f"  Flagged marginal    : {cov['n_marginal']} ({cov['n_marginal']/total:.1%})")
        print(f"  Still orphan        : {cov['n_orphan']} ({orphan_pct:.1%})")

        if orphan_pct <= 0.05:
            print(f"\n  ✅ GUARDRAIL PASS — orphans ≤ 5%")
        else:
            print(f"\n  ⚠ GUARDRAIL FAIL — orphans {orphan_pct:.1%} > 5% (cible)")
            print(f"     Possible : claims créés depuis le fetch initial, ou échecs LLM systémiques.")
            print(f"     Re-run le backfill pour les rattraper, ou investiguer les erreurs ci-dessus.")

    # Persist summary
    summary_file = out_dir / f"summary_{ts}.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "duration_s": total_dur,
            "n_processed": n_done,
            "n_extracted": n_extracted,
            "n_marginal": n_marginal,
            "n_errors": n_errors,
            "dry_run": args.dry_run,
            "workers": args.workers,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nDétails : {checkpoint_file}")
    print(f"Summary : {summary_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
