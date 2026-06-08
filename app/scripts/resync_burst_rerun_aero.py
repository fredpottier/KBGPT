"""resync_burst_rerun_aero.py — Récupération après spot interruption du burst.

Contexte (08/06 ~12:00) : l'instance spot g6 (3.125.33.111) a été interrompue
pendant le post-import aero. SpotFleet a respawné une nouvelle instance
(IP différente). Redis pointait encore sur l'ancienne IP morte → les étapes
post-import dépendantes du burst (claim_embeddings, adjudicate_contradictions,
build_perspectives, …) ont échoué dans le process live.

Ce script :
  1. Découvre la vérité AWS (nouvelle IP de l'instance running).
  2. Vérifie que vLLM (8000) + TEI (8001) RÉPONDENT sur la nouvelle IP.
  3. Met à jour l'état burst dans Redis + ré-active les providers in-process
     (vLLM + EmbeddingManager re-pinnés sur la NOUVELLE IP).
  4. Warmup vLLM.
  5. Relance UNIQUEMENT les étapes passées en argv (idempotentes, MERGE).

Usage :
    docker exec -e CLAIMFIRST_STAGED_PIPELINE=1 -e PYTHONIOENCODING=utf-8 \
        knowbase-app python //app/scripts/resync_burst_rerun_aero.py \
        claim_embeddings claim_chunk_bridge adjudicate_contradictions build_perspectives
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request

TENANT = "aero"


def log(msg: str) -> None:
    print(f"[RESYNC-RERUN {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _http_ok(url: str, timeout: int = 6) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def main() -> int:
    steps = sys.argv[1:]
    if not steps:
        log("⚠️ aucune étape passée en argv — ABANDON.")
        return 2
    log(f"étapes à relancer : {steps}")

    # 1. Vérité AWS — nouvelle IP
    from knowbase.ingestion.burst.aws_truth_service import discover_aws_truth
    truth = discover_aws_truth()
    primary = truth.aws.primary_instance
    if not primary or not primary.get("public_ip"):
        log("⚠️ aucune instance burst running côté AWS — ABANDON.")
        return 2
    new_ip = primary["public_ip"]
    vllm_url = f"http://{new_ip}:8000"
    emb_url = f"http://{new_ip}:8001"
    log(f"nouvelle instance AWS : {new_ip} ({primary.get('instance_type')}, {primary.get('instance_id')})")

    # 2. Vérifier que les 2 services répondent
    if not _http_ok(f"{vllm_url}/v1/models"):
        log(f"⚠️ vLLM PAS prêt sur {vllm_url} — ABANDON (réessayer plus tard).")
        return 3
    if not _http_ok(f"{emb_url}/health"):
        log(f"⚠️ TEI PAS prêt sur {emb_url} — ABANDON (réessayer plus tard).")
        return 3
    log(f"✅ vLLM + TEI répondent sur {new_ip}")

    # 3. Mettre à jour Redis + ré-activer les providers (re-pin sur la nouvelle IP)
    from knowbase.ingestion.burst.provider_switch import (
        set_burst_state_in_redis, activate_burst_providers,
    )
    vllm_model = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    set_burst_state_in_redis(vllm_url, vllm_model, emb_url)
    activate_burst_providers(vllm_url, emb_url, vllm_model)
    log(f"burst ré-activé (Redis + in-process) → {vllm_url} / {emb_url}")

    # 4. Warmup vLLM
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
        return 3

    # 5. Relancer les étapes demandées
    from knowbase.api.routers.post_import import run_pipeline_job
    log(f"relance post-import {TENANT} : {steps}")
    t0 = time.time()
    out = run_pipeline_job(steps, TENANT)
    log(f"relance terminée en {(time.time() - t0) / 60:.0f} min")
    log("résumé : " + json.dumps(out, ensure_ascii=False, default=str)[:1500])

    # 6. Comptes finaux + non-régression
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    with get_neo4j_client().driver.session() as s:
        for q, lbl in [
            (f"MATCH (c:Claim {{tenant_id:'{TENANT}'}}) RETURN count(c)", "aero claims"),
            (f"MATCH (c:Claim {{tenant_id:'{TENANT}'}}) WHERE c.embedding_indexed = true RETURN count(c)", "aero claims embeddings_indexed"),
            (f"MATCH (:Claim {{tenant_id:'{TENANT}'}})-[r:CONTRADICTS]->() RETURN count(r)", "aero CONTRADICTS"),
            (f"MATCH (p:Perspective {{tenant_id:'{TENANT}'}}) RETURN count(p)", "aero perspectives"),
            ("MATCH (c:Claim {tenant_id:'default'}) RETURN count(c)", "default claims (inchangé)"),
            ("MATCH (c:Claim {tenant_id:'sap_ref'}) RETURN count(c)", "sap_ref claims (inchangé)"),
        ]:
            try:
                log(f"final {lbl} : {s.run(q).single()[0]}")
            except Exception as e:
                log(f"final {lbl} : (erreur requête : {e})")
    log("✅ RESYNC + RERUN AERO TERMINÉ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
