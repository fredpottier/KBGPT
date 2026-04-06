"""
OSMOSIS Cockpit — Moteur ETA.

Calcule les estimations de temps restant pour les pipelines en cours,
en utilisant l'historique des runs passés stocké dans SQLite.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from cockpit.config import ETA_DB_PATH
from cockpit.models import PipelineStatus

logger = logging.getLogger(__name__)


class ETAEngine:
    def __init__(self):
        self._db_path = ETA_DB_PATH
        self._ensure_db()

    def _ensure_db(self):
        """Crée la base SQLite si elle n'existe pas."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pipeline_type TEXT NOT NULL,
                    run_id TEXT,
                    stage_name TEXT NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    duration_s REAL,
                    items_processed INTEGER DEFAULT 0,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rh_pipeline_stage
                ON run_history(pipeline_type, stage_name)
            """)

    def record_stage_completion(
        self,
        pipeline_type: str,
        run_id: str,
        stage_name: str,
        duration_s: float,
        items_processed: int = 0,
    ):
        """Enregistre la durée d'une étape terminée."""
        now = time.time()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT INTO run_history
                       (pipeline_type, run_id, stage_name, started_at, finished_at,
                        duration_s, items_processed)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (pipeline_type, run_id, stage_name,
                     now - duration_s, now, duration_s, items_processed),
                )
        except Exception as e:
            logger.warning(f"[COCKPIT:ETA] Record failed: {e}")

    def get_median_duration(self, pipeline_type: str, stage_name: str) -> Optional[float]:
        """Retourne la durée médiane historique d'une étape."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """SELECT duration_s FROM run_history
                       WHERE pipeline_type = ? AND stage_name = ?
                       ORDER BY duration_s""",
                    (pipeline_type, stage_name),
                ).fetchall()
                if not rows:
                    return None
                durations = [r[0] for r in rows]
                mid = len(durations) // 2
                if len(durations) % 2 == 0:
                    return (durations[mid - 1] + durations[mid]) / 2
                return durations[mid]
        except Exception:
            return None

    def get_history_count(self, pipeline_type: str, stage_name: str) -> int:
        """Nombre de runs historiques pour une étape."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    """SELECT COUNT(*) FROM run_history
                       WHERE pipeline_type = ? AND stage_name = ?""",
                    (pipeline_type, stage_name),
                ).fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def compute_eta(self, pipeline: PipelineStatus) -> PipelineStatus:
        """Enrichit un PipelineStatus avec les estimations ETA."""
        if not pipeline or pipeline.current_stage_index < 0:
            return pipeline

        current_idx = pipeline.current_stage_index
        current_stage = pipeline.stages[current_idx]

        # ETA de l'étape en cours (si itérative)
        stage_eta_s = None
        confidence = "unknown"

        if current_stage.progress is not None and current_stage.progress > 0:
            # Estimation basée sur la progression
            elapsed = current_stage.duration_s or 0
            rate = elapsed / current_stage.progress if current_stage.progress > 0 else 0
            stage_eta_s = rate * (1.0 - current_stage.progress)

            # Confiance basée sur le nombre d'items traités
            items_done = int(current_stage.progress * 100)  # approximation
            if items_done > 10:
                confidence = "high"
            elif items_done > 3:
                confidence = "medium"
            else:
                confidence = "low"

        # ETA des étapes restantes (historique)
        remaining_eta_s = 0.0
        all_have_history = True

        for i in range(current_idx + 1, len(pipeline.stages)):
            stage = pipeline.stages[i]
            if stage.status in ("done", "failed", "skipped"):
                continue
            median = self.get_median_duration(pipeline.name, stage.name)
            if median is not None:
                remaining_eta_s += median
            else:
                all_have_history = False
                # Estimation grossière : durée médiane globale par étape
                global_median = self._get_global_stage_median(pipeline.name)
                if global_median:
                    remaining_eta_s += global_median

        # ETA total
        total_eta_s = (stage_eta_s or 0) + remaining_eta_s
        if total_eta_s > 0:
            pipeline.eta_remaining_s = int(total_eta_s)
            from datetime import datetime, timezone, timedelta
            finish = datetime.now(timezone.utc) + timedelta(seconds=total_eta_s)
            pipeline.eta_finish = finish.isoformat()

        # Confiance globale
        history_count = self.get_history_count(pipeline.name, current_stage.name)
        if confidence == "high" and all_have_history and history_count >= 3:
            pipeline.eta_confidence = "high"
        elif confidence in ("high", "medium") or history_count >= 1:
            pipeline.eta_confidence = "medium"
        elif stage_eta_s is not None:
            pipeline.eta_confidence = "low"
        else:
            pipeline.eta_confidence = "unknown"

        return pipeline

    def _get_global_stage_median(self, pipeline_type: str) -> Optional[float]:
        """Durée médiane globale par étape pour un type de pipeline."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """SELECT duration_s FROM run_history
                       WHERE pipeline_type = ?
                       ORDER BY duration_s""",
                    (pipeline_type,),
                ).fetchall()
                if not rows:
                    return None
                durations = [r[0] for r in rows]
                mid = len(durations) // 2
                return durations[mid]
        except Exception:
            return None
