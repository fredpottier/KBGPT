"""
Retrigger 11 aerospace orphans sequentially (1 doc per job).

Avec 1 worker actif, les jobs en queue se traitent sequentiellement.
On enqueue 1 job par doc, le worker prend le suivant des qu'il a fini.
"""

from __future__ import annotations

import sys
import time

ORPHAN_DOCS = [
    "cs25_change_amdt_28_69cf602f",   # small (priority 1, validation fix)
    "cs25_change_amdt_24_cdd7474b",   # small
    "cs25_change_amdt_26_28f2c375",   # small
    "cs25_amdt_28_32f1a9ac",          # medium
    "dualuse_del_2023_66_cdc2b691",   # medium
    "dualuse_del_2024_2547_cb08f84b", # medium
    "dualuse_reg_2021_821_original_65eef5dc",   # large
    "dualuse_reg_428_2009_original_372b7ac3",   # large
    "cs25_amdt_27_992260a7",          # large (1777 chunks)
    "cs25_amdt_26_6450b31e",          # very large (3525 chunks)
]


def main() -> int:
    from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process

    print(f"=== Retrigger {len(ORPHAN_DOCS)} orphans (sequential) ===")
    enqueued: list[str] = []
    for i, doc_id in enumerate(ORPHAN_DOCS, 1):
        try:
            job = enqueue_claimfirst_process(
                doc_ids=[doc_id],
                tenant_id="default",
                cache_dir="/data/extraction_cache",
            )
            print(f"  [{i:2}/{len(ORPHAN_DOCS)}] {job.id}  doc={doc_id[:40]}")
            enqueued.append(job.id)
            time.sleep(0.2)  # eviter race RQ
        except Exception as e:
            print(f"  [{i:2}/{len(ORPHAN_DOCS)}] FAIL doc={doc_id}: {e}", file=sys.stderr)

    print(f"\nEnqueued {len(enqueued)} jobs on 'reprocess' queue.")
    print("Watch progress :")
    print("  docker logs knowbase-worker -f")
    print("Or :")
    print("  curl -s http://localhost:6379 ... (RQ inspection)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
