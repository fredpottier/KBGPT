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

    def collect(self) -> Optional[A38Report]:
        """GET /api/benchmarks/a38 → run le plus récent (bras osmosis)."""
        try:
            resp = requests.get(f"{self._api_base}/api/benchmarks/a38", timeout=5)
            if resp.status_code != 200:
                return None

            runs = (resp.json() or {}).get("runs", [])
            if not runs:
                return None

            # Bras osmosis prioritaire (sinon le plus récent, déjà trié par l'API)
            osm = next((r for r in runs if r.get("arm") == "osmosis"), runs[0])

            eir = osm.get("exact_id_recall_mean") or 0.0
            abst = osm.get("abstention_correct_rate") or 0.0
            c1 = osm.get("C1_mean") or 0.0

            # Diagnostic piloté par les 2 mesures déterministes (pas le juge bruité)
            if eir >= 0.75 and abst >= 0.80:
                diagnostic = "Systeme fiable"
            elif eir >= 0.50:
                diagnostic = "A surveiller"
            else:
                diagnostic = "Probleme RETRIEVAL"

            return A38Report(
                exact_id_recall=round(eir, 4),
                abstention_correct=round(abst, 4),
                c1_mean=round(c1, 4),
                n_total=osm.get("n_total") or 0,
                n_with_ids=osm.get("n_with_expected_ids") or 0,
                latency_p50=round(osm.get("latency_p50_s") or 0.0, 1),
                latency_p95=round(osm.get("latency_p95_s") or 0.0, 1),
                arm=osm.get("arm", "osmosis"),
                timestamp=osm.get("timestamp", ""),
                diagnostic=diagnostic,
            )

        except Exception as e:
            logger.warning(f"[COCKPIT:A38] API collect failed: {e}")
            return None
