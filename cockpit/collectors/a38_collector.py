"""
OSMOSIS Cockpit — Collecteur gold-set (bench a38 runtime_v6) via API.

Remplace les collecteurs V3 (RAGAS/T2T5/Robustesse) pour le widget « Qualité Osmosis ».
Lit le dernier run a38 via GET /api/benchmarks/a38 (bras osmosis prioritaire).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from cockpit.config import OSMOSIS_API_URL
from cockpit.models import A38Report

logger = logging.getLogger(__name__)


class A38Collector:
    """Collecte le dernier run gold-set (a38) via l'API OSMOSIS."""

    def __init__(self):
        self._api_base = OSMOSIS_API_URL.rstrip("/")

    @staticmethod
    def _run_tenant(run: dict) -> Optional[str]:
        """Extrait le tenant/corpus d'un run gold-set.

        Les runs récents portent `tenant` (ou `corpus`) ; les anciens runs
        non tagués retournent None (bucket « global »). Le bench runner doit
        écrire `tenant` dans le résumé JSON pour alimenter le par-tenant.
        """
        return run.get("tenant") or run.get("corpus") or None

    @staticmethod
    def _to_report(run: dict, tenant: Optional[str]) -> A38Report:
        eir = run.get("exact_id_recall_mean") or 0.0
        abst = run.get("abstention_correct_rate") or 0.0
        c1 = run.get("C1_mean") or 0.0
        if eir >= 0.75 and abst >= 0.80:
            diagnostic = "Systeme fiable"
        elif eir >= 0.50:
            diagnostic = "A surveiller"
        else:
            diagnostic = "Probleme RETRIEVAL"
        return A38Report(
            tenant=tenant,
            exact_id_recall=round(eir, 4),
            abstention_correct=round(abst, 4),
            c1_mean=round(c1, 4),
            n_total=run.get("n_total") or 0,
            n_with_ids=run.get("n_with_expected_ids") or 0,
            latency_p50=round(run.get("latency_p50_s") or 0.0, 1),
            latency_p95=round(run.get("latency_p95_s") or 0.0, 1),
            arm=run.get("arm", "osmosis"),
            timestamp=run.get("timestamp", ""),
            diagnostic=diagnostic,
        )

    def collect(self) -> Optional[A38Report]:
        """Run osmosis le plus récent (compat — widget mono). Cf collect_full()."""
        recent, _ = self.collect_full()
        return recent

    def collect_full(self) -> tuple[Optional[A38Report], list[A38Report]]:
        """Retourne (run le plus récent, [A38Report par tenant]).

        Par tenant : le run osmosis le plus récent de chaque tenant taggué.
        Les runs non tagués sont regroupés sous le bucket tenant=None.
        """
        try:
            resp = requests.get(f"{self._api_base}/api/benchmarks/a38", timeout=5)
            if resp.status_code != 200:
                return None, []
            runs = (resp.json() or {}).get("runs", [])
            if not runs:
                return None, []

            # Run le plus récent (osmosis prioritaire) — compat widget mono
            osm = next((r for r in runs if r.get("arm") == "osmosis"), runs[0])
            recent = self._to_report(osm, self._run_tenant(osm))

            # Par tenant : 1er run osmosis rencontré par tenant (runs déjà triés récent→ancien)
            by_tenant: dict[Optional[str], A38Report] = {}
            for r in runs:
                if r.get("arm") != "osmosis":
                    continue
                tid = self._run_tenant(r)
                if tid not in by_tenant:
                    by_tenant[tid] = self._to_report(r, tid)
            # Tenants tagués d'abord, bucket global (None) en dernier
            ordered = sorted(by_tenant.values(),
                             key=lambda rep: (rep.tenant is None, rep.tenant or ""))
            return recent, ordered

        except Exception as e:
            logger.warning(f"[COCKPIT:A38] API collect failed: {e}")
            return None, []
