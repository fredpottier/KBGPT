#!/usr/bin/env python
"""
p1_stageA_funnel_probe.py — Funnel d'extraction staged sur 1 doc (mesure pure, no persist).

Mesure le tonnage à chaque étage :
    unités indexées → Stage A (gardées / jetées / guard-override) → Stage B (claims produits)
→ dit si le volume vient d'un Stage A trop laxiste (sélectivité) ou d'un Stage B trop génératif
  (consolidation), et le facteur de multiplication claims/unité-gardée.

    docker exec knowbase-app python scripts/p1_stageA_funnel_probe.py <doc_id>
"""
from __future__ import annotations

import os
import sys
import time


def run(doc_id, tenant_id="default"):
    os.environ["CLAIMFIRST_STAGED_PIPELINE"] = "1"
    os.environ.setdefault("CLAIMFIRST_GROUNDING_GATE", "0")  # funnel = volume, grounding inutile ici

    from knowbase.ingestion.burst.provider_switch import (
        get_burst_state_from_redis, activate_burst_providers, is_burst_mode_active,
    )
    st = get_burst_state_from_redis() or {}
    if st.get("vllm_url"):
        activate_burst_providers(st.get("vllm_url"), st.get("embeddings_url"), st.get("vllm_model"))

    from knowbase.claimfirst.worker_job import _get_llm_client, _get_neo4j_driver, _build_cache_map
    from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache

    orch = ClaimFirstOrchestrator(
        llm_client=_get_llm_client(), neo4j_driver=_get_neo4j_driver(),
        tenant_id=tenant_id, persist_enabled=False,
    )
    ex = orch.claim_extractor

    F = {"units_in": 0, "kept": 0, "dropped": 0, "guard": 0, "judge_failed": 0,
         "a_calls": 0, "claims_out": 0, "b_calls": 0, "drop_cat": {}}
    GUARD_SAMPLES = []  # textes des unités gardées par guard-override (juge=DROP)

    # wrap Stage A
    origA = ex._selection_gate.aclassify

    async def wrapA(units):
        F["units_in"] += len(units)
        F["a_calls"] += 1
        res = await origA(units)
        F["kept"] += res.n_kept
        F["dropped"] += res.n_dropped
        F["guard"] += res.guard_overrides
        F["guard_suppr"] = F.get("guard_suppr", 0) + getattr(res, "guard_suppressed", 0)
        if res.judge_failed:
            F["judge_failed"] += 1
        for v in res.dropped:
            F["drop_cat"][v.category] = F["drop_cat"].get(v.category, 0) + 1
        for v in res.verdicts:
            if v.guard_override and len(GUARD_SAMPLES) < 25:
                GUARD_SAMPLES.append((v.category, v.text[:150]))
        return res
    ex._selection_gate.aclassify = wrapA

    # wrap Stage B
    origB = ex._decomposition_stage.adecompose

    async def wrapB(kept, passage_text):
        F["b_calls"] += 1
        res = await origB(kept, passage_text)
        try:
            F["claims_out"] += len(res.claims)
        except Exception:
            pass
        return res
    ex._decomposition_stage.adecompose = wrapB

    cache_path = _build_cache_map("/data/extraction_cache").get(doc_id)
    if not cache_path:
        raise SystemExit(f"pas de cache pour {doc_id}")
    cr = load_pass0_from_cache(cache_path, tenant_id)
    passages = orch._create_passages(cr.pass0_result, tenant_id)

    t0 = time.perf_counter()
    claims, _ = ex.extract(
        passages=passages, tenant_id=tenant_id, doc_id=doc_id,
        doc_title=cr.doc_title or doc_id, doc_type="technical",
    )
    wall = time.perf_counter() - t0

    drop_rate = 100 * F["dropped"] / max(F["units_in"], 1)
    yld = F["claims_out"] / max(F["kept"], 1)
    print(f"\n===== FUNNEL {doc_id} (burst={is_burst_mode_active()}, {wall:.0f}s) =====")
    print(f"  passages                  = {len(passages)}")
    print(f"  unités vues (Stage A in)  = {F['units_in']}")
    print(f"  Stage A — GARDÉES         = {F['kept']}  ({100-drop_rate:.1f}%)")
    print(f"  Stage A — JETÉES          = {F['dropped']}  ({drop_rate:.1f}%)   [guard-override gardées: {F['guard']} | guard SUPPRIMÉ (déchet+id): {F.get('guard_suppr',0)}]")
    print(f"  Stage A — batches judge_failed (tout gardé) = {F['judge_failed']}/{F['a_calls']}")
    print(f"  Stage B — claims produits = {F['claims_out']}   (yield {yld:.2f} claim / unité gardée)")
    print(f"  claims finaux (post-gates internes extracteur) = {len(claims)}")
    if F["drop_cat"]:
        print(f"  top catégories de DROP Stage A :")
        for cat, n in sorted(F["drop_cat"].items(), key=lambda x: -x[1])[:8]:
            print(f"      {n:5d}  {cat}")
    if GUARD_SAMPLES:
        print(f"\n  --- ÉCHANTILLON guard-override (juge=DROP, gardé car identifiant) ---")
        for cat, txt in GUARD_SAMPLES:
            print(f"      [{cat}] {txt}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: p1_stageA_funnel_probe.py <doc_id>")
    run(sys.argv[1])
