"""relance_postimport_aero.py — Relance les étapes 7→18 du post-import aero en PARALLÈLE.

Contexte (08/06) : le post-import de l'import aero tournait en mode SÉQUENTIEL
(Ollama) car _ensure_vllm_for_full_local ne reconnaissait pas le burst EC2 (#461,
corrigé). Les étapes 1→6 (canonicalize → chains_cross_doc) sont déjà faites et
persistées. On relance UNIQUEMENT 7→18 avec le fix → mode parallèle, bien plus
rapide. Les étapes sont idempotentes (MERGE) donc reprendre detect_contradictions
depuis le début ne pose pas de problème (elle n'avait rien persisté : CONTRADICTS=0).

Usage :
    docker exec -e CLAIMFIRST_STAGED_PIPELINE=1 -e PYTHONIOENCODING=utf-8 \
        knowbase-app python //app/scripts/relance_postimport_aero.py
"""

from __future__ import annotations

import asyncio
import json
import time

TENANT = "aero"

# Étapes 7→18 (1→6 déjà faites). Ordre = registre post-import.
STEPS_7_18 = [
    "detect_contradictions",
    "domain_pack_reprocess",
    "claim_embeddings",
    "claim_chunk_bridge",
    "archive_isolated",
    "garbage_collection",
    "c4_relations",
    "c6_pivots",
    "explicit_lineage",
    "lineage_resolution",
    "adjudicate_contradictions",
    "build_perspectives",
]


def log(msg: str) -> None:
    print(f"[RELANCE-PI {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    # 1. Activer le burst in-process + warmup (routage parallèle vers vLLM distant)
    from knowbase.ingestion.burst.provider_switch import (
        get_burst_state_from_redis, activate_burst_providers,
    )
    st = get_burst_state_from_redis()
    if not (st and st.get("active")):
        log("⚠️ burst NON actif dans Redis — ABANDON.")
        return 2
    activate_burst_providers(st["vllm_url"], st.get("embeddings_url"), st.get("vllm_model"))
    log(f"burst activé : {st['vllm_url']}")

    from knowbase.common.llm_router import get_llm_router, TaskType
    router = get_llm_router()
    for attempt in range(8):
        try:
            r = asyncio.run(router.acomplete(
                task_type=TaskType.LONG_TEXT_SUMMARY,
                messages=[{"role": "user", "content": "Reply: WARMUP_OK"}],
                max_tokens=10, temperature=0))
            if r and "WARMUP_OK" in r:
                log(f"warmup burst OK (essai {attempt + 1})")
                break
        except Exception as e:
            log(f"warmup essai {attempt + 1} échec : {e}")
        time.sleep(15)
    else:
        log("⚠️ warmup échoué — ABANDON.")
        return 2

    # 2. Relancer les étapes 7→18 (mode parallèle grâce au fix #461)
    from knowbase.api.routers.post_import import run_pipeline_job
    log(f"relance post-import {TENANT} étapes 7→18 : {STEPS_7_18}")
    t0 = time.time()
    out = run_pipeline_job(STEPS_7_18, TENANT)
    log(f"post-import 7→18 terminé en {(time.time() - t0) / 60:.0f} min")
    log("résumé : " + json.dumps(out, ensure_ascii=False, default=str)[:1500])

    # 3. Comptes finaux + non-régression
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    with get_neo4j_client().driver.session() as s:
        for q, lbl in [
            (f"MATCH (c:Claim {{tenant_id:'{TENANT}'}}) RETURN count(c)", "aero claims"),
            (f"MATCH (:Claim {{tenant_id:'{TENANT}'}})-[r:CONTRADICTS]->() RETURN count(r)", "aero CONTRADICTS"),
            (f"MATCH (:Document {{tenant_id:'{TENANT}'}})-[r:SUPERSEDES_DOC]->() RETURN count(r)", "aero SUPERSEDES_DOC"),
            (f"MATCH (:Claim {{tenant_id:'{TENANT}'}})-[r:REFINES]->() RETURN count(r)", "aero REFINES"),
            (f"MATCH (p:Perspective {{tenant_id:'{TENANT}'}}) RETURN count(p)", "aero perspectives"),
            ("MATCH (c:Claim {tenant_id:'default'}) RETURN count(c)", "default claims (inchangé)"),
            ("MATCH (c:Claim {tenant_id:'sap_ref'}) RETURN count(c)", "sap_ref claims (inchangé)"),
        ]:
            log(f"final {lbl} : {s.run(q).single()[0]}")
    log("✅ RELANCE POST-IMPORT AERO TERMINÉE")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
