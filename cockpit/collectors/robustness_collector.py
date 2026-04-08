"""
OSMOSIS Cockpit — Collecteur Robustesse via API.

Lit le dernier rapport robustesse depuis l'API OSMOSIS.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from cockpit.config import OSMOSIS_API_URL
from cockpit.models import RobustnessReport

logger = logging.getLogger(__name__)


class RobustnessCollector:
    """Collecte le dernier rapport robustesse via l'API OSMOSIS."""

    def __init__(self):
        self._api_base = OSMOSIS_API_URL.rstrip("/")

    def collect(self) -> Optional[RobustnessReport]:
        """Appelle GET /api/benchmarks/robustness et retourne le rapport le plus recent."""
        try:
            resp = requests.get(f"{self._api_base}/api/benchmarks/robustness", timeout=5)
            if resp.status_code != 200:
                return None

            data = resp.json()
            reports = data.get("reports", [])
            if not reports:
                return None

            latest = reports[0]
            scores = latest.get("scores", {})
            timestamp = latest.get("timestamp", "")

            return RobustnessReport(
                global_score=scores.get("global_score", 0.0),
                causal_why_score=scores.get("causal_why_score", 0.0),
                conditional_score=scores.get("conditional_score", 0.0),
                false_premise_score=scores.get("false_premise_score", 0.0),
                hypothetical_score=scores.get("hypothetical_score", 0.0),
                multi_hop_score=scores.get("multi_hop_score", 0.0),
                negation_score=scores.get("negation_score", 0.0),
                set_list_score=scores.get("set_list_score", 0.0),
                synthesis_large_score=scores.get("synthesis_large_score", 0.0),
                temporal_evolution_score=scores.get("temporal_evolution_score", 0.0),
                unanswerable_score=scores.get("unanswerable_score", 0.0),
                total_evaluated=scores.get("total_evaluated", 0),
                timestamp=timestamp,
            )

        except Exception as e:
            logger.warning(f"[COCKPIT:ROBUSTNESS] API collect failed: {e}")
            return None
