#!/usr/bin/env python
"""
reset_and_rerun_relations.py — Reset des artefacts de relations cross-doc puis
re-run du pipeline relationnel complet + résolution par lignée (ADR).

RESET (tenant ciblé UNIQUEMENT — claims/entités/facets/embeddings CONSERVÉS) :
  - nœuds  : ConflictPending, ClaimCluster
  - arêtes : CONTRADICTS, REFINES, QUALIFIES, COMPLEMENTS, SPECIALIZES,
             EVOLVES_TO, EVOLUTION_OF, CHAINS_TO, SAME_AS (claim↔claim)
  - champs : invalidated_at/valid_until/invalidated_by/invalidation_reason posés
             par 'doc_lineage' + lifecycle 'withdrawn' posés par container_cancelled
             (pour une re-application propre et mesurable)
  - CONSERVÉS : SUPERSEDES_DOC / DECLARES_SUPERSESSION (MERGE idempotent)

RE-RUN : cluster_cross_doc → chains_cross_doc → detect_contradictions →
         c4_relations → c6_pivots → explicit_lineage → lineage_resolution

    docker exec knowbase-app python scripts/reset_and_rerun_relations.py --tenant default
"""

from __future__ import annotations

import argparse
import json
import time

REL_TYPES = "CONTRADICTS|REFINES|QUALIFIES|COMPLEMENTS|SPECIALIZES|EVOLVES_TO|EVOLUTION_OF|CHAINS_TO|SAME_AS"
STEPS = [
    "cluster_cross_doc",
    "chains_cross_doc",
    "detect_contradictions",
    "c4_relations",
    "c6_pivots",
    "explicit_lineage",
    "lineage_resolution",
]


def log(msg: str) -> None:
    print(f"[RESET-RERUN {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--skip-reset", action="store_true")
    args = ap.parse_args()
    t = args.tenant

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    if not args.skip_reset:
        with driver.session() as s:
            n = s.run(
                f"MATCH (:Claim {{tenant_id: $t}})-[r:{REL_TYPES}]-(:Claim) "
                "DELETE r RETURN count(r) AS n", t=t,
            ).single()["n"]
            log(f"arêtes relations supprimées : {n}")
            for label in ("ConflictPending", "ClaimCluster"):
                n = s.run(
                    f"MATCH (x:{label} {{tenant_id: $t}}) DETACH DELETE x RETURN count(x) AS n",
                    t=t,
                ).single()["n"]
                log(f"nœuds {label} supprimés : {n}")
            # Champs posés par la résolution lignée (re-application propre)
            n = s.run(
                "MATCH (c:Claim {tenant_id: $t}) WHERE c.invalidation_reason = 'doc_lineage' "
                "SET c.invalidated_at = NULL, c.valid_until = NULL, "
                "    c.invalidated_by = NULL, c.invalidation_reason = NULL "
                "RETURN count(c) AS n", t=t,
            ).single()["n"]
            log(f"invalidations doc_lineage réinitialisées : {n}")
            n = s.run(
                "MATCH (c:Claim {tenant_id: $t}) "
                "WHERE c.lifecycle_status_reason STARTS WITH 'container_cancelled_by:' "
                "SET c.lifecycle_status_current = NULL, c.lifecycle_status_reason = NULL, "
                "    c.lifecycle_status_change_date = NULL RETURN count(c) AS n", t=t,
            ).single()["n"]
            log(f"marqueurs withdrawn réinitialisés : {n}")

    from knowbase.api.routers.post_import import run_pipeline_job
    log(f"re-run pipeline relationnel : {STEPS}")
    t0 = time.time()
    out = run_pipeline_job(STEPS, t)
    log(f"pipeline terminé en {(time.time() - t0) / 60:.0f} min")
    log("résumé : " + json.dumps(out, ensure_ascii=False, default=str)[:1200])

    # Mesure finale
    with driver.session() as s:
        for q, lbl in [
            ("MATCH (:Claim {tenant_id:$t})-[r:CONTRADICTS]->() RETURN count(r) AS n", "CONTRADICTS vifs"),
            ("MATCH (:Claim {tenant_id:$t})-[r:SUPERSEDES]->() RETURN count(r) AS n", "SUPERSEDES (résolus)"),
            ("MATCH (c:Claim {tenant_id:$t}) WHERE c.invalidated_at IS NOT NULL RETURN count(c) AS n", "claims invalidés"),
            ("MATCH (c:Claim {tenant_id:$t}) WHERE c.lifecycle_status_current='withdrawn' RETURN count(c) AS n", "claims withdrawn (épistémique)"),
            ("MATCH (cp:ConflictPending {tenant_id:$t}) RETURN count(cp) AS n", "ConflictPending"),
            ("MATCH (:Document {tenant_id:$t})-[r:SUPERSEDES_DOC]->() RETURN count(r) AS n", "SUPERSEDES_DOC"),
        ]:
            log(f"final {lbl} : {s.run(q, t=t).single()['n']}")
    log("✅ terminé")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
