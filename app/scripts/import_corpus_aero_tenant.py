"""import_corpus_aero_tenant.py — Ré-ingestion du corpus aéro dans le tenant NEUF `aero`.

Décision Fred (07/06/2026) : on importe le corpus dans un tenant neuf `aero`
SANS détruire `default` → comparaison côte à côte des deux extractions
(ancien contexte + ancien pipeline VS contexte corrigé + #450 + #457).
`default` reste la baseline vivante et requêtable.

Ce que l'import prend en compte (vs le KG `default` actuel) :
  - pipeline STAGED par défaut (anti-sur-extraction)
  - gardes #450 (selection_gate : lifecycle / requirement / PURPOSE)
  - grounding gate NLI
  - domain context CORRIGÉ (sièges/crashworthiness, installé sur `aero`)
  - #457 datation des cartouches US (M/D/YY)
  - post-import complet (lignée #443, adjudication #446, etc.)

PRÉREQUIS :
  1. burst EC2 g6 actif (extraction LLM) — sinon ABANDON (pas de DeepInfra).
  2. domain context installé sur `aero` (set_domain_context_aero_seats.py --tenant aero).
  3. extraction_cache préservé (full_text Docling des 24 docs).

NE TOUCHE PAS : default, sap_ref, extraction_cache, Qdrant chunks.

Usage :
    docker exec -e CLAIMFIRST_STAGED_PIPELINE=1 -e CLAIMFIRST_GROUNDING_GATE=1 \
        knowbase-app python //app/scripts/import_corpus_aero_tenant.py
"""

from __future__ import annotations

import json
import os
import time

TARGET_TENANT = "aero"
SOURCE_TENANT = "default"  # source des doc_ids (mêmes fichiers, mêmes caches)


def log(msg: str) -> None:
    print(f"[IMPORT-AERO {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    assert os.getenv("CLAIMFIRST_STAGED_PIPELINE", "1") == "1", "staged requis"

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.claimfirst.worker_job import _build_cache_map

    driver = get_neo4j_client().driver

    # ---------- 0. Sécurité : aero doit être vide ----------
    with driver.session() as s:
        existing = s.run(
            "MATCH (c:Claim {tenant_id:$t}) RETURN count(c) AS n", t=TARGET_TENANT
        ).single()["n"]
    if existing:
        log(f"⚠️ le tenant '{TARGET_TENANT}' contient déjà {existing} claims — ABANDON "
            f"(purger d'abord ce tenant si ré-import voulu).")
        return 1

    # ---------- 1. doc_ids depuis default + résolution cache ----------
    with driver.session() as s:
        doc_ids = sorted(r["d"] for r in s.run(
            "MATCH (c:Claim {tenant_id:$t}) WHERE c.doc_id IS NOT NULL "
            "RETURN DISTINCT c.doc_id AS d", t=SOURCE_TENANT))
    log(f"docs source ({SOURCE_TENANT}) : {len(doc_ids)}")

    cache_map = _build_cache_map("/data/extraction_cache")
    missing = [d for d in doc_ids if d not in cache_map]
    if missing:
        log(f"⚠️ {len(missing)} docs SANS cache (seront skippés) : {missing}")
    doc_ids = [d for d in doc_ids if d in cache_map]
    # Petits d'abord (proxy taille cache) → un maximum de docs finis si interruption.
    doc_ids.sort(key=lambda d: os.path.getsize(cache_map[d]))
    log(f"plan d'ingestion vers '{TARGET_TENANT}' ({len(doc_ids)} docs, petits d'abord) :")
    for d in doc_ids:
        log(f"  - {d} ({os.path.getsize(cache_map[d]) // 1024} Ko cache)")

    # ---------- 2. Contrôles d'intégrité (rien ne doit être purgé) ----------
    with driver.session() as s:
        for t in (SOURCE_TENANT, "sap_ref"):
            n = s.run("MATCH (c:Claim {tenant_id:$t}) RETURN count(c) AS n", t=t).single()["n"]
            log(f"contrôle {t} intact (avant) : {n} claims")

    # ---------- 3. Burst in-process OBLIGATOIRE ----------
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

    # ---------- 3bis. Warmup burst (évite le fallback deepinfra au démarrage) ----------
    # Le routage async vers vLLM n'est effectif qu'une fois le client async
    # initialisé via la gate Redis. À froid, le 1er appel peut retomber en mode
    # normal (deepinfra) → extraction silencieusement sur le mauvais provider.
    # On force le routage et on ABANDONNE si le burst n'est pas joignable.
    import asyncio
    from knowbase.common.llm_router import get_llm_router, TaskType
    router = get_llm_router()
    warm_ok = False
    for attempt in range(8):
        try:
            resp = asyncio.run(router.acomplete(
                task_type=TaskType.LONG_TEXT_SUMMARY,
                messages=[{"role": "user", "content": "Reply with exactly: WARMUP_OK"}],
                max_tokens=10, temperature=0))
            if resp and "WARMUP_OK" in resp:
                warm_ok = True
                log(f"warmup burst OK (essai {attempt + 1}) : routage vLLM confirmé")
                break
            log(f"warmup essai {attempt + 1} : réponse inattendue {resp!r}")
        except Exception as e:
            log(f"warmup essai {attempt + 1} échec : {e}")
        time.sleep(15)
    if not warm_ok:
        log("⚠️ warmup burst échoué (8 essais) — l'extraction tomberait sur deepinfra. ABANDON.")
        return 2

    # ---------- 4. Ingestion staged vers aero ----------
    from knowbase.claimfirst.worker_job import claimfirst_process_job

    t0 = time.time()
    res = claimfirst_process_job(
        doc_ids=doc_ids, tenant_id=TARGET_TENANT, cache_dir="/data/extraction_cache"
    )
    log(f"ingestion terminée en {(time.time() - t0) / 60:.0f} min : "
        f"processed={res.get('processed')} failed={res.get('failed')} "
        f"skipped={res.get('skipped')} claims={res.get('total_claims')}")
    if res.get("errors"):
        log("erreurs : " + json.dumps(res["errors"], ensure_ascii=False)[:1500])

    if (res.get("processed") or 0) < max(1, int(len(doc_ids) * 0.8)):
        log("⚠️ moins de 80% des docs ingérés — post-import SAUTÉ (relancer après reprise).")
        return 3

    # ---------- 5. Post-import complet sur aero ----------
    from knowbase.api.routers.post_import import STEPS, run_pipeline_job

    step_ids = [s.id for s in sorted(STEPS, key=lambda x: x.order)]
    log(f"post-import : {len(step_ids)} étapes → {step_ids}")
    t1 = time.time()
    try:
        out = run_pipeline_job(step_ids, TARGET_TENANT)
        log(f"post-import terminé en {(time.time() - t1) / 60:.0f} min")
        log("résumé : " + json.dumps(out, ensure_ascii=False, default=str)[:1500])
    except Exception as e:
        log(f"⚠️ post-import a levé : {e} — vérifier l'état des étapes.")
        return 4

    # ---------- 6. Comptes finaux + contrôle non-régression ----------
    with driver.session() as s:
        for q, lbl in [
            (f"MATCH (c:Claim {{tenant_id:'{TARGET_TENANT}'}}) RETURN count(c) AS n", "aero claims"),
            (f"MATCH (:Claim {{tenant_id:'{TARGET_TENANT}'}})-[r:CONTRADICTS]->() RETURN count(r) AS n", "aero CONTRADICTS"),
            (f"MATCH (:Document {{tenant_id:'{TARGET_TENANT}'}})-[r:SUPERSEDES_DOC]->() RETURN count(r) AS n", "aero SUPERSEDES_DOC"),
            (f"MATCH (c:Claim {{tenant_id:'{TARGET_TENANT}'}}) WHERE c.embedding IS NOT NULL RETURN count(c) AS n", "aero claims embeddés"),
            (f"MATCH (c:Claim {{tenant_id:'{SOURCE_TENANT}'}}) RETURN count(c) AS n", "default claims (doit être inchangé)"),
            ("MATCH (c:Claim {tenant_id:'sap_ref'}) RETURN count(c) AS n", "sap_ref claims (doit être inchangé)"),
        ]:
            log(f"final {lbl} : {s.run(q).single()['n']}")
    log("✅ IMPORT AERO TERMINÉ — comparer : kg_snapshot.py --tenant aero puis --compare")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
