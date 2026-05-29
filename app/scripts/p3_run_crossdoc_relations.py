"""P3.4 — Lance les steps post-processing cross-doc c4_relations + c6_pivots.

Construit les relations manquantes du KG ré-ingéré :
  - c4_relations : CONTRADICTS / QUALIFIES / REFINES (mining cosine≥0.85 + adjudication NLI)
  - c6_pivots    : COMPLEMENTS / EVOLUTION_OF / SPECIALIZES (pivots entités partagées)

Adjudication via llm_router → route vers le vLLM burst (Qwen2.5-14B) car burst actif.
Supersession ON (défaut RelationPersisterC4) : invalide les claims perdants à conf≥0.85.

Usage : docker exec -e ... knowbase-app python scripts/p3_run_crossdoc_relations.py
"""
from __future__ import annotations

import json
import time

from knowbase.api.routers.post_import import _run_c4_relations, _run_c6_pivots

TENANT = "default"


def _progress(label):
    def cb(pct, detail=""):
        print(f"  [{label}] {pct:>3.0f}% {detail}", flush=True)
    return cb


def main() -> None:
    print(f"=== P3.4 cross-doc relations — start {time.strftime('%H:%M:%S')} ===", flush=True)

    print("\n--- STEP c4_relations (CONTRADICTS/QUALIFIES/REFINES) ---", flush=True)
    t0 = time.perf_counter()
    res_c4 = _run_c4_relations(TENANT, progress=_progress("c4"))
    print(f"c4 done in {time.perf_counter()-t0:.0f}s", flush=True)
    print("c4 result:", json.dumps(res_c4, ensure_ascii=False, default=str)[:800], flush=True)

    print("\n--- STEP c6_pivots (COMPLEMENTS/EVOLUTION_OF/SPECIALIZES) ---", flush=True)
    t0 = time.perf_counter()
    res_c6 = _run_c6_pivots(TENANT, progress=_progress("c6"))
    print(f"c6 done in {time.perf_counter()-t0:.0f}s", flush=True)
    print("c6 result:", json.dumps(res_c6, ensure_ascii=False, default=str)[:800], flush=True)

    print(f"\n=== P3.4 done {time.strftime('%H:%M:%S')} ===", flush=True)


if __name__ == "__main__":
    main()
