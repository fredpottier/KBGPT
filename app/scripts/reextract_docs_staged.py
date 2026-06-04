#!/usr/bin/env python
"""
reextract_docs_staged.py — Ré-extraction ciblée de docs (purge par doc + claimfirst staged
+ mini post-import : embeddings + lignée explicite).

Usage (burst actif requis) :
    docker exec -e CLAIMFIRST_STAGED_PIPELINE=1 -e CLAIMFIRST_GROUNDING_GATE=1 \
        knowbase-app python scripts/reextract_docs_staged.py --tenant default <doc_id> [...]
"""

from __future__ import annotations

import argparse
import json
import time


def log(msg: str) -> None:
    print(f"[REEXTRACT {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--skip-postimport", action="store_true")
    ap.add_argument("doc_ids", nargs="+")
    args = ap.parse_args()

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    # 1. Purge ciblée par doc (claims + DocumentContext ; entités partagées intactes)
    with driver.session() as s:
        for d in args.doc_ids:
            n = s.run(
                "MATCH (c:Claim {tenant_id: $t, doc_id: $d}) DETACH DELETE c RETURN count(c) AS n",
                t=args.tenant, d=d,
            ).single()["n"]
            dc = s.run(
                "MATCH (x:DocumentContext {doc_id: $d}) DETACH DELETE x RETURN count(x) AS n",
                d=d,
            ).single()["n"]
            log(f"purge {d}: {n} claims, {dc} DocumentContext")

    # 2. Burst in-process
    from knowbase.ingestion.burst.provider_switch import (
        get_burst_state_from_redis, activate_burst_providers, is_burst_mode_active,
    )
    st = get_burst_state_from_redis()
    if not (st and st.get("active")):
        log("⚠️ burst NON actif — ABANDON (l'extraction partirait sur DeepInfra)")
        return 2
    activate_burst_providers(st["vllm_url"], st.get("embeddings_url"), st.get("vllm_model"))
    log(f"burst actif in-process: {is_burst_mode_active()} ({st['vllm_url']})")

    # 3. Ré-ingestion staged
    from knowbase.claimfirst.worker_job import claimfirst_process_job
    t0 = time.time()
    res = claimfirst_process_job(
        doc_ids=args.doc_ids, tenant_id=args.tenant, cache_dir="/data/extraction_cache"
    )
    log(f"ingestion: {(time.time()-t0)/60:.0f} min — processed={res.get('processed')} "
        f"failed={res.get('failed')} claims={res.get('total_claims')}")
    if res.get("errors"):
        log("erreurs: " + json.dumps(res["errors"], ensure_ascii=False)[:800])

    # 4. Mini post-import : embeddings (incrémental) + lignée explicite
    if not args.skip_postimport:
        from knowbase.api.routers.post_import import run_pipeline_job
        out = run_pipeline_job(["claim_embeddings", "explicit_lineage"], args.tenant)
        log("mini post-import: " + json.dumps(out, ensure_ascii=False, default=str)[:600])

    # 5. Lignée résultante
    with driver.session() as s:
        for r in s.run(
            "MATCH path=(h:Document {tenant_id:$t})-[:SUPERSEDES_DOC*1..]->(x:Document) "
            "WHERE NOT (:Document)-[:SUPERSEDES_DOC]->(h) "
            "RETURN [n IN nodes(path) | coalesce(n.reg_key, n.doc_id)] AS chain "
            "ORDER BY size(chain) DESC LIMIT 10",
            t=args.tenant,
        ):
            log("chaîne: " + " ▶ ".join(r["chain"]))
    log("✅ terminé")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
