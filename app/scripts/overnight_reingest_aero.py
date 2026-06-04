#!/usr/bin/env python
"""
overnight_reingest_aero.py — Ré-ingestion STAGED complète du corpus aéro (P1.4-bis, 03-04/06/2026).

Séquence autonome (lancer avec CLAIMFIRST_STAGED_PIPELINE=1 CLAIMFIRST_GROUNDING_GATE=1) :
  1. Capture des doc_ids aéro actuels (tenant default) + les 4 nouveaux docs (staging).
  2. Purge Neo4j des tenants `default` et `staged_val` UNIQUEMENT (batché).
     ⚠️ sap_ref intact. ⚠️ extraction_cache et Qdrant chunks PRÉSERVÉS.
  3. Ré-ingestion staged des ~23 docs depuis extraction_cache (petits d'abord),
     burst g6 activé in-process.
  4. Post-import complet (tous les steps, ordre du registre) sur `default`.

Usage :
    docker exec -e CLAIMFIRST_STAGED_PIPELINE=1 -e CLAIMFIRST_GROUNDING_GATE=1 \
        knowbase-app python scripts/overnight_reingest_aero.py
"""

from __future__ import annotations

import json
import os
import time

# Les 4 nouveaux docs (préfixes de doc_id — résolus via le cache)
NEW_DOC_PREFIXES = [
    "ETSO-C39b_",
    "AC_25.785-1A_cancelled_",
    "AC_25.785-1B_",
    "AC_25-17_1991_cancelled_",
]


def log(msg: str) -> None:
    print(f"[OVERNIGHT {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    assert os.getenv("CLAIMFIRST_STAGED_PIPELINE", "1") == "1", "staged requis"

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.worker_job import _build_cache_map

    driver = get_neo4j_client().driver

    # ---------- 1. Capture des doc_ids ----------
    with driver.session() as s:
        current = [r["d"] for r in s.run(
            "MATCH (c:Claim {tenant_id:'default'}) WHERE c.doc_id IS NOT NULL "
            "RETURN DISTINCT c.doc_id AS d"
        )]
    log(f"docs aéro actuels (default) : {len(current)}")

    cache_map = _build_cache_map("/data/extraction_cache")
    new_docs = []
    for prefix in NEW_DOC_PREFIXES:
        matches = [d for d in cache_map if d.startswith(prefix)]
        if matches:
            new_docs.extend(matches)
        else:
            log(f"⚠️ nouveau doc INTROUVABLE dans le cache : {prefix}*")
    all_docs = sorted(set(current) | set(new_docs))
    # Vérifier que chaque doc a un cache (sinon il sera skippé par le worker job)
    missing = [d for d in all_docs if d not in cache_map]
    if missing:
        log(f"⚠️ {len(missing)} docs SANS cache (seront skippés) : {missing}")
    all_docs = [d for d in all_docs if d in cache_map]
    # Petits d'abord (taille du fichier cache comme proxy) → maximise les docs
    # terminés si la nuit ne suffit pas ; les géants (AC 25-17/25-17A) en dernier.
    all_docs.sort(key=lambda d: os.path.getsize(cache_map[d]))
    log(f"plan d'ingestion ({len(all_docs)} docs, petits d'abord) :")
    for d in all_docs:
        log(f"  - {d} ({os.path.getsize(cache_map[d]) // 1024} Ko cache)")

    # ---------- 2. Purge tenants default + staged_val ----------
    for tenant in ("staged_val", "default"):
        total = 0
        with driver.session() as s:
            while True:
                n = s.run(
                    "MATCH (n {tenant_id: $t}) WITH n LIMIT 5000 "
                    "DETACH DELETE n RETURN count(*) AS n",
                    t=tenant,
                ).single()["n"]
                total += n
                if n == 0:
                    break
        log(f"purge tenant {tenant} : {total} nœuds")
    with driver.session() as s:
        sap = s.run("MATCH (c:Claim {tenant_id:'sap_ref'}) RETURN count(c) AS n").single()["n"]
    log(f"contrôle sap_ref intact : {sap} claims")

    # ---------- 3. Burst in-process + ingestion staged ----------
    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis, activate_burst_providers, is_burst_mode_active,
        )
        st = get_burst_state_from_redis()
        if st and st.get("active"):
            activate_burst_providers(st["vllm_url"], st.get("embeddings_url"), st.get("vllm_model"))
            log(f"burst activé in-process : {is_burst_mode_active()} ({st['vllm_url']})")
        else:
            log("⚠️ burst NON actif dans Redis — l'extraction partirait sur DeepInfra. ABANDON.")
            return 2
    except Exception as e:
        log(f"⚠️ activation burst échec : {e} — ABANDON")
        return 2

    from knowbase.claimfirst.worker_job import claimfirst_process_job

    t0 = time.time()
    res = claimfirst_process_job(
        doc_ids=all_docs, tenant_id="default", cache_dir="/data/extraction_cache"
    )
    log(f"ingestion terminée en {(time.time() - t0) / 60:.0f} min : "
        f"processed={res.get('processed')} failed={res.get('failed')} "
        f"skipped={res.get('skipped')} claims={res.get('total_claims')}")
    if res.get("errors"):
        log("erreurs : " + json.dumps(res["errors"], ensure_ascii=False)[:1500])

    if (res.get("processed") or 0) < max(1, int(len(all_docs) * 0.8)):
        log("⚠️ moins de 80% des docs ingérés — post-import SAUTÉ (à relancer après reprise).")
        return 3

    # ---------- 4. Post-import complet ----------
    from knowbase.api.routers.post_import import STEPS, run_pipeline_job

    step_ids = [s.id for s in sorted(STEPS, key=lambda x: x.order)]
    log(f"post-import : {len(step_ids)} étapes → {step_ids}")
    t1 = time.time()
    try:
        out = run_pipeline_job(step_ids, "default")
        log(f"post-import terminé en {(time.time() - t1) / 60:.0f} min")
        log("résumé post-import : " + json.dumps(out, ensure_ascii=False, default=str)[:1500])
    except Exception as e:
        log(f"⚠️ post-import a levé : {e} — vérifier l'état des étapes au matin.")
        return 4

    # ---------- 5. Comptes finaux ----------
    with driver.session() as s:
        for q, lbl in [
            ("MATCH (c:Claim {tenant_id:'default'}) RETURN count(c) AS n", "claims"),
            ("MATCH (:Claim {tenant_id:'default'})-[r:CONTRADICTS]->() RETURN count(r) AS n", "CONTRADICTS"),
            ("MATCH (:Document {tenant_id:'default'})-[r:SUPERSEDES_DOC]->() RETURN count(r) AS n", "SUPERSEDES_DOC"),
            ("MATCH (c:Claim {tenant_id:'default'}) WHERE c.embedding IS NOT NULL RETURN count(c) AS n", "claims avec embedding"),
        ]:
            log(f"final {lbl} : {s.run(q).single()['n']}")
    log("✅ NUIT TERMINÉE")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
