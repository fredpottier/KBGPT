"""
OSMOSIS Cockpit — Collecteur T2/T5 via API.

Lit le dernier rapport T2/T5 depuis l'API OSMOSIS (qui voit les fichiers dans le container)
plutot que depuis le filesystem local (bind-mount Windows desynchronise).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from cockpit.config import OSMOSIS_API_URL
from cockpit.models import T2T5Report

logger = logging.getLogger(__name__)


class T2T5Collector:
    """Collecte le dernier rapport T2/T5 via l'API OSMOSIS."""

    def __init__(self):
        self._api_base = OSMOSIS_API_URL.rstrip("/")

    def collect(self) -> Optional[T2T5Report]:
        """Appelle GET /api/benchmarks/t2t5 et retourne le rapport le plus recent."""
        try:
            resp = requests.get(f"{self._api_base}/api/benchmarks/t2t5", timeout=5)
            if resp.status_code != 200:
                return None

            data = resp.json()
            reports = data.get("reports", [])
            if not reports:
                return None

            latest = reports[0]
            scores = latest.get("scores", {})
            timestamp = latest.get("timestamp", "")

            return T2T5Report(
                tension_mentioned=scores.get("tension_mentioned", 0.0),
                both_sides_surfaced=scores.get("both_sides_surfaced", 0.0),
                both_sources_cited=scores.get("both_sources_cited", 0.0),
                proactive_detection=scores.get("proactive_detection", 0.0),
                chain_coverage=scores.get("chain_coverage", 0.0),
                multi_doc_cited=scores.get("multi_doc_cited", 0.0),
                t2_count=scores.get("t2_count", 0),
                t5_count=scores.get("t5_count", 0),
                total_evaluated=scores.get("total_evaluated", 0),
                timestamp=timestamp,
            )

        except Exception as e:
            logger.warning(f"[COCKPIT:T2T5] API collect failed: {e}")
            return None
