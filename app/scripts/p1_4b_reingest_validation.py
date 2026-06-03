#!/usr/bin/env python
"""
p1_4b_reingest_validation.py — Ré-ingestion de VALIDATION du pipeline staged (P1.4-bis)
sur quelques docs, via le vrai worker job (orchestrateur réel + persist Neo4j).

KG purgé au préalable (tenant default = 0). Burst g6 (Qwen2.5-14B-AWQ) actif.
Lancer avec CLAIMFIRST_STAGED_PIPELINE=1 (et CLAIMFIRST_GROUNDING_GATE=1 par défaut) :

    docker compose exec -e CLAIMFIRST_STAGED_PIPELINE=1 app python scripts/p1_4b_reingest_validation.py

Compare au run P1.3.5 (sur-extraction) sur les MÊMES docs :
    training_aa ≈ 62 | 012 Installation ≈ 479 | 017 Operations ≈ 1055  (claims P1.3.5)
"""

from __future__ import annotations

import json
import os
import sys
import time

# Sous-ensemble du run P1.3.5 (hors Feature Scope 025=6934, trop long) pour comparaison directe
DOC_IDS = [
    "training_aa_sap_erp_cloud_private_operations_june_2025_75643d51",  # P1.3.5 ≈ 62
    "012_SAP_S4HANA_2021_Installation_Guide_c441dbaf",                  # P1.3.5 ≈ 479
    "017_SAP_S4HANA_2023_Operations_Guide_b11842e3",                   # P1.3.5 ≈ 1055
]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default",
                    help="Tenant cible (ex. staged_val pour une validation isolée — NE PAS polluer default)")
    ap.add_argument("doc_ids", nargs="*", help='doc_ids à traiter, ou "ALL" pour tout le cache')
    args = ap.parse_args()

    staged = os.getenv("CLAIMFIRST_STAGED_PIPELINE", "0") == "1"
    grounding = os.getenv("CLAIMFIRST_GROUNDING_GATE", "1") == "1"
    tenant_id = args.tenant
    # doc_ids : "ALL" → tout le cache (corpus complet) ; sinon argv ; sinon défaut (3 docs)
    if len(args.doc_ids) == 1 and args.doc_ids[0].upper() == "ALL":
        from knowbase.claimfirst.worker_job import _build_cache_map
        doc_ids = sorted(_build_cache_map("/data/extraction_cache").keys())
    else:
        doc_ids = args.doc_ids if args.doc_ids else DOC_IDS
    print(f"[REINGEST] staged={staged} grounding={grounding} tenant={tenant_id} docs={len(doc_ids)}")
    for d in doc_ids:
        print(f"  - {d}")

    # Activer le burst DANS ce process (flag interne router/embeddings) AVANT l'init de
    # l'extracteur, sinon is_burst_mode_active()=False → concurrence bridée à 5 (bug observé).
    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis, activate_burst_providers, is_burst_mode_active,
        )
        st = get_burst_state_from_redis()
        if st and st.get("active"):
            activate_burst_providers(st["vllm_url"], st.get("embeddings_url"), st.get("vllm_model"))
            print(f"[REINGEST] burst activé dans le process : is_burst_mode_active={is_burst_mode_active()}")
        else:
            print("[REINGEST] AUCUN état burst actif dans Redis — extraction risque d'aller sur DeepInfra")
    except Exception as e:
        print(f"[REINGEST] activation burst échec: {e}")

    from knowbase.claimfirst.worker_job import claimfirst_process_job

    t0 = time.time()
    res = claimfirst_process_job(
        doc_ids=doc_ids, tenant_id=tenant_id, cache_dir="/data/extraction_cache"
    )
    dt = time.time() - t0
    print(f"\n[REINGEST] terminé en {dt:.0f}s")
    print(json.dumps(res, indent=2, default=str)[:2000])


if __name__ == "__main__":
    main()
