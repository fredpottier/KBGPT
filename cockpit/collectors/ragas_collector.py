"""
OSMOSIS Cockpit — Collecteur RAGAS via API.

Lit le dernier rapport RAGAS depuis l'API OSMOSIS (qui voit les fichiers dans le container)
plutot que depuis le filesystem local (bind-mount Windows desynchronise).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from cockpit.config import OSMOSIS_API_URL
from cockpit.models import RagasReport

logger = logging.getLogger(__name__)


class RagasCollector:
    """Collecte le dernier rapport RAGAS via l'API OSMOSIS."""

    def __init__(self):
        self._api_base = OSMOSIS_API_URL.rstrip("/")

    def collect(self) -> Optional[RagasReport]:
        """Appelle GET /api/benchmarks/ragas et retourne le rapport le plus recent."""
        try:
            resp = requests.get(f"{self._api_base}/api/benchmarks/ragas", timeout=5)
            if resp.status_code != 200:
                return None

            data = resp.json()
            reports = data.get("reports", [])
            if not reports:
                return None

            # Le plus recent (deja trie par l'API)
            latest = reports[0]
            systems = latest.get("systems", {})
            osm = systems.get("osmosis", {})
            if not osm:
                return None

            scores = osm.get("scores", {})
            faithfulness = scores.get("faithfulness", 0.0)
            context_relevance = scores.get("context_relevance", 0.0)
            sample_count = osm.get("sample_count", 0)
            timestamp = latest.get("timestamp", "")

            if faithfulness >= 0.7 and context_relevance >= 0.7:
                diagnostic = "Systeme fonctionnel"
            elif context_relevance >= 0.7 and faithfulness < 0.7:
                diagnostic = "Probleme SYNTHESE"
            elif context_relevance < 0.7 and faithfulness >= 0.7:
                diagnostic = "Probleme RETRIEVAL"
            else:
                diagnostic = "Probleme FONDAMENTAL"

            return RagasReport(
                faithfulness=round(faithfulness, 4),
                context_relevance=round(context_relevance, 4),
                sample_count=sample_count,
                label=osm.get("label", "OSMOSIS"),
                timestamp=timestamp,
                diagnostic=diagnostic,
                worst_samples=[],
            )

        except Exception as e:
            logger.warning(f"[COCKPIT:RAGAS] API collect failed: {e}")
            return None
