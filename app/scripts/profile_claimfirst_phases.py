#!/usr/bin/env python
"""
profile_claimfirst_phases.py — Profileur NON-INVASIF des phases du worker ClaimFirst.

Poll l'état Redis `osmose:claimfirst:state` à intervalle régulier, détecte les transitions
de phase (EXTRACTING, CROSS_DOC_CHAINS, CANONICALIZE_ENTITIES, CROSS_DOC_CLUSTERING,
QS_CROSS_DOC_COMPARISON, KG_HYGIENE_L1, DONE) et calcule la DURÉE de chaque phase.
But : savoir où passe le temps (extraction vs post-processing) — répond au point #2.

Lancer en arrière-plan EN PARALLÈLE de l'ingestion :
    docker compose exec app python scripts/profile_claimfirst_phases.py
"""

from __future__ import annotations

import time


def main():
    from knowbase.common.clients.redis_client import get_redis_client
    r = get_redis_client().client

    print("[PROFILER] démarrage — poll osmose:claimfirst:state toutes les 5s")
    timeline = []  # (phase, label_courant, t)
    last_key = None
    started = time.time()
    idle = 0

    while True:
        time.sleep(5)
        d = r.hgetall("osmose:claimfirst:state") or {}
        d = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
             for k, v in d.items()}
        status = d.get("status", "")
        phase = d.get("phase", "")
        pstatus = d.get("phase_status", "")
        filename = (d.get("current_filename", "") or "")[:40]
        claims = d.get("total_claims", "?")
        key = (phase, pstatus, filename)

        if key != last_key:
            now = time.time()
            if timeline:
                prev_phase, prev_label, prev_t = timeline[-1]
                print(f"[PROFILER]   ^ {prev_phase}/{prev_label} a duré {now - prev_t:.0f}s")
            print(f"[PROFILER] +{now-started:.0f}s | phase={phase}/{pstatus} | doc='{filename}' | claims={claims}")
            timeline.append((phase, pstatus, now))
            last_key = key

        if status in ("COMPLETED", "DONE", "FAILED") and phase in ("DONE", ""):
            idle += 1
            if idle >= 3:
                break
        else:
            idle = 0

    # Résumé des durées par phase (sur les transitions)
    print("\n[PROFILER] === DURÉES PAR PHASE ===")
    for i in range(len(timeline) - 1):
        ph, lab, t = timeline[i]
        nxt_t = timeline[i + 1][2]
        print(f"  {ph}/{lab}: {nxt_t - t:.0f}s")
    print(f"  TOTAL observé: {timeline[-1][2]-timeline[0][2]:.0f}s" if len(timeline) > 1 else "")


if __name__ == "__main__":
    main()
