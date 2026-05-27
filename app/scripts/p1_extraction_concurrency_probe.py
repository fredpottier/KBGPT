#!/usr/bin/env python
"""
p1_extraction_concurrency_probe.py — Isole le goulot d'extraction staged (P1.4-bis).

Mesure, sur l'extraction SEULE (pas de persist, pas de post-traitement) d'UN doc :
  - wall time
  - nombre de claims
  - PIC de concurrence LLM réelle (combien d'appels en vol simultanément)
  - temps LLM cumulé (Stage A + Stage B)
  - temps grounding cumulé + nb appels
  → diagnostique pourquoi gather(32) ne donne pas 32 en vol.

Compare grounding ON vs OFF pour isoler le coût/sérialisation du grounding NLI.

Usage :
    docker exec knowbase-app python scripts/p1_extraction_concurrency_probe.py <doc_id> [on|off|both]
"""
from __future__ import annotations

import os
import sys
import time


def _activate_burst():
    from knowbase.ingestion.burst.provider_switch import (
        get_burst_state_from_redis, activate_burst_providers, is_burst_mode_active,
    )
    st = get_burst_state_from_redis() or {}
    if st.get("vllm_url"):
        activate_burst_providers(st.get("vllm_url"), st.get("embeddings_url"), st.get("vllm_model"))
    return is_burst_mode_active(), st.get("vllm_url")


def _load_passages(doc_id, tenant_id, orch):
    from knowbase.claimfirst.worker_job import _build_cache_map
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache
    cache_map = _build_cache_map("/data/extraction_cache")
    cache_path = cache_map.get(doc_id)
    if not cache_path:
        raise SystemExit(f"pas de cache pour {doc_id}")
    cr = load_pass0_from_cache(cache_path, tenant_id)
    if not cr.success:
        raise SystemExit(f"échec load cache {doc_id}")
    passages = orch._create_passages(cr.pass0_result, tenant_id)
    title = cr.doc_title or doc_id
    return passages, title


def run_one(doc_id, grounding_on, tenant_id="default"):
    os.environ["CLAIMFIRST_STAGED_PIPELINE"] = "1"
    os.environ["CLAIMFIRST_GROUNDING_GATE"] = "1" if grounding_on else "0"

    active, vllm = _activate_burst()
    from knowbase.claimfirst.worker_job import _get_llm_client, _get_neo4j_driver
    from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator

    orch = ClaimFirstOrchestrator(
        llm_client=_get_llm_client(),
        neo4j_driver=_get_neo4j_driver(),
        tenant_id=tenant_id,
        persist_enabled=False,
    )
    ex = orch.claim_extractor
    passages, title = _load_passages(doc_id, tenant_id, orch)

    # --- instrumentation concurrence LLM (wrap les gates) ---
    stt = {"active": 0, "peak": 0, "n": 0, "tsum": 0.0}

    def wrap_async(orig):
        async def w(system, user):
            stt["active"] += 1
            stt["peak"] = max(stt["peak"], stt["active"])
            stt["n"] += 1
            t = time.perf_counter()
            try:
                return await orig(system, user)
            finally:
                stt["tsum"] += time.perf_counter() - t
                stt["active"] -= 1
        return w

    if ex._selection_gate is not None:
        ex._selection_gate.llm_call = wrap_async(ex._selection_gate.llm_call)
    if ex._decomposition_stage is not None:
        ex._decomposition_stage.llm_call = wrap_async(ex._decomposition_stage.llm_call)

    # --- instrumentation grounding ---
    g = {"t": 0.0, "n": 0}
    if ex._grounding_gate is not None and ex._grounding_gate.enabled:
        origg = ex._grounding_gate.check_batch

        def wg(items):
            t = time.perf_counter()
            try:
                return origg(items)
            finally:
                g["t"] += time.perf_counter() - t
                g["n"] += 1
        ex._grounding_gate.check_batch = wg

    print(f"\n===== {doc_id} | grounding={'ON' if grounding_on else 'OFF'} =====")
    print(f"burst_active={active} vllm={vllm} max_concurrent={ex.max_concurrent} "
          f"batch_size={ex.batch_size} passages={len(passages)}")

    t0 = time.perf_counter()
    claims, _ = ex.extract(
        passages=passages, tenant_id=tenant_id, doc_id=doc_id,
        doc_title=title, doc_type="technical",
    )
    wall = time.perf_counter() - t0

    avg_par = (stt["tsum"] / wall) if wall > 0 else 0
    print(f"--- RÉSULTAT ---")
    print(f"  claims          = {len(claims)}")
    print(f"  wall            = {wall:.0f}s")
    print(f"  appels LLM      = {stt['n']}  (temps LLM cumulé {stt['tsum']:.0f}s)")
    print(f"  PIC concurrence = {stt['peak']}  / max_concurrent {ex.max_concurrent}")
    print(f"  parallélisme moyen LLM = {avg_par:.1f}x  (tsum/wall)")
    print(f"  latence moy/appel = {stt['tsum']/max(stt['n'],1):.1f}s")
    if grounding_on:
        print(f"  grounding       = {g['t']:.0f}s sur {g['n']} appels "
              f"({100*g['t']/max(wall,1):.0f}% du wall)")
    return {"claims": len(claims), "wall": wall, "peak": stt["peak"],
            "llm_calls": stt["n"], "llm_t": stt["tsum"], "ground_t": g["t"]}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: p1_extraction_concurrency_probe.py <doc_id> [on|off|both]")
    doc_id = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "both"
    if mode in ("off", "both"):
        run_one(doc_id, grounding_on=False)
    if mode in ("on", "both"):
        run_one(doc_id, grounding_on=True)


if __name__ == "__main__":
    main()
