"""
OSMOSIS Cockpit — Agrégateur principal.

Les collecteurs lents (Docker, Knowledge, Burst) tournent dans des tâches
background indépendantes. La boucle principale n'attend jamais un collecteur
lent — elle utilise le dernier résultat caché.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from cockpit.config import (
    COLLECT_INTERVAL, DOCKER_COLLECT_INTERVAL,
    KNOWLEDGE_COLLECT_INTERVAL, BURST_COLLECT_INTERVAL,
    LLM_COLLECT_INTERVAL, RAGAS_COLLECT_INTERVAL,
)
from cockpit.models import CockpitState, PipelineStatus
from cockpit.collectors.docker_collector import DockerCollector
from cockpit.collectors.pipeline_collector import PipelineCollector
from cockpit.collectors.burst_collector import BurstCollector
from cockpit.collectors.knowledge_collector import KnowledgeCollector
from cockpit.collectors.llm_budget_collector import LLMBudgetCollector
from cockpit.collectors.ragas_collector import RagasCollector
from cockpit.collectors.t2t5_collector import T2T5Collector
from cockpit.engine.eta import ETAEngine
from cockpit.engine.events import SmartEventEngine

logger = logging.getLogger(__name__)


class Aggregator:
    """
    Orchestre la collecte et assemble le CockpitState.

    Architecture non-bloquante :
    - Pipeline (Redis) : synchrone, rapide (~1ms), à chaque cycle
    - Docker stats : background task, résultat caché, ne bloque jamais la boucle
    - Knowledge/Burst : background tasks, résultats cachés
    - LLM : synchrone rapide (HTTP local)
    """

    def __init__(self):
        self.docker_collector = DockerCollector()
        self.pipeline_collector = PipelineCollector()
        self.burst_collector = BurstCollector()
        self.knowledge_collector = KnowledgeCollector()
        self.llm_collector = LLMBudgetCollector()
        self.ragas_collector = RagasCollector()
        self.t2t5_collector = T2T5Collector()
        self.eta_engine = ETAEngine()
        self.event_engine = SmartEventEngine()

        self._state = CockpitState()
        self._prev_pipeline_stages: dict[str, str] = {}

        # Background task tracking
        self._docker_task: Optional[asyncio.Task] = None
        self._knowledge_task: Optional[asyncio.Task] = None
        self._burst_task: Optional[asyncio.Task] = None
        self._last_docker_ts: float = 0
        self._last_knowledge_ts: float = 0
        self._last_burst_ts: float = 0
        self._last_llm_ts: float = 0
        self._last_ragas_ts: float = 0

    @property
    def state(self) -> CockpitState:
        return self._state

    def reset_llm_session(self):
        self.llm_collector.reset_session()

    # ── Background collectors ────────────────────────────────────

    async def _bg_docker(self):
        """Collecte Docker en background — ne bloque pas la boucle."""
        try:
            result = await asyncio.to_thread(self.docker_collector.collect)
            self._state.container_groups = result
            self._last_docker_ts = time.time()
        except Exception as e:
            logger.warning(f"[COCKPIT:AGG] Docker collect failed: {e}")

    async def _bg_knowledge(self):
        """Collecte Knowledge en background."""
        try:
            result = await asyncio.to_thread(self.knowledge_collector.collect)
            self._state.knowledge = result
            self._last_knowledge_ts = time.time()
        except Exception as e:
            logger.warning(f"[COCKPIT:AGG] Knowledge collect failed: {e}")

    async def _bg_burst(self):
        """Collecte Burst en background."""
        try:
            result = await asyncio.to_thread(self.burst_collector.collect)
            self._state.burst = result
            self._last_burst_ts = time.time()
        except Exception as e:
            logger.warning(f"[COCKPIT:AGG] Burst collect failed: {e}")

    def _maybe_launch(self, task_attr: str, coro, interval: float) -> None:
        """Lance une tâche background si l'intervalle est écoulé et aucune n'est en cours."""
        existing = getattr(self, task_attr)
        if existing and not existing.done():
            return  # Déjà en cours, on attend
        last_ts_attr = task_attr.replace("_task", "").replace("_", "_last_") + "_ts"
        # Utiliser le mapping direct
        ts_map = {
            "_docker_task": self._last_docker_ts,
            "_knowledge_task": self._last_knowledge_ts,
            "_burst_task": self._last_burst_ts,
        }
        last_ts = ts_map.get(task_attr, 0)
        if time.time() - last_ts >= interval:
            setattr(self, task_attr, asyncio.create_task(coro()))

    # ── Main collect cycle ───────────────────────────────────────

    async def collect_once(self) -> CockpitState:
        """Cycle de collecte rapide — jamais bloquant."""
        # Pipelines (Redis) — synchrone, ~1ms
        pipelines = self.pipeline_collector.collect()

        # Lancer les collecteurs lents en background (non-bloquant)
        self._maybe_launch("_docker_task", self._bg_docker, DOCKER_COLLECT_INTERVAL)
        self._maybe_launch("_knowledge_task", self._bg_knowledge, KNOWLEDGE_COLLECT_INTERVAL)
        self._maybe_launch("_burst_task", self._bg_burst, BURST_COLLECT_INTERVAL)

        # LLM — synchrone rapide (HTTP local)
        now = time.time()
        if now - self._last_llm_ts >= LLM_COLLECT_INTERVAL:
            try:
                self._state.llm_session = self.llm_collector.collect_session()
                self._state.llm_balances = self.llm_collector.collect_balances()
                self._last_llm_ts = now
            except Exception as e:
                logger.warning(f"[COCKPIT:AGG] LLM collect failed: {e}")

        # RAGAS + T2/T5 — lecture fichier, très léger
        if now - self._last_ragas_ts >= RAGAS_COLLECT_INTERVAL:
            try:
                self._state.ragas = self.ragas_collector.collect()
                self._state.t2t5 = self.t2t5_collector.collect()
                self._last_ragas_ts = now
            except Exception as e:
                logger.warning(f"[COCKPIT:AGG] Quality collect failed: {e}")

        # Pipelines + ETA
        for p in pipelines:
            self._track_stage_completions(p)
            self.eta_engine.compute_eta(p)
        self._state.pipelines = pipelines

        # Smart Events
        self._state.events = self.event_engine.evaluate(self._state)

        # Timestamp
        self._state.timestamp = datetime.now(timezone.utc).isoformat()

        return self._state

    def _track_stage_completions(self, pipeline: PipelineStatus):
        for stage in pipeline.stages:
            prev_status = self._prev_pipeline_stages.get(stage.name)
            if prev_status != "done" and stage.status == "done" and stage.duration_s:
                self.eta_engine.record_stage_completion(
                    pipeline_type=pipeline.name,
                    run_id=pipeline.run_id,
                    stage_name=stage.name,
                    duration_s=stage.duration_s,
                )
            self._prev_pipeline_stages[stage.name] = stage.status

    async def run_loop(self, callback=None):
        """Boucle principale — émet l'état toutes les COLLECT_INTERVAL secondes."""
        logger.info(f"[COCKPIT:AGG] Starting (interval={COLLECT_INTERVAL}s)")
        while True:
            try:
                state = await self.collect_once()
                if callback:
                    await callback(state)
            except Exception as e:
                logger.error(f"[COCKPIT:AGG] Cycle failed: {e}")
            await asyncio.sleep(COLLECT_INTERVAL)
