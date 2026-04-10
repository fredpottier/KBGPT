"""
OSMOSIS Cockpit — Moteur Smart Events v2.

Logique TABLEAU DE BORD, pas log chronologique :
- Chaque condition = 1 seul event affiché (mis à jour en place)
- Quand la condition disparaît, l'event disparaît
- Pas d'empilement, pas de doublons
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from cockpit.config import (
    EVENT_STALL_THRESHOLD_S, EVENT_BURST_IDLE_S,
    LLM_CRITICAL_THRESHOLD, LLM_LOW_THRESHOLD,
)
from cockpit.models import CockpitState, SmartEvent

logger = logging.getLogger(__name__)


class SmartEventEngine:
    def __init__(self):
        # Tracking state pour détection de changements
        self._last_pipeline_progress: Optional[float] = None
        self._last_pipeline_progress_ts: float = 0
        self._last_pipeline_stage_idx: int = -1
        self._burst_idle_since: Optional[float] = None

    def evaluate(self, state: CockpitState) -> list[SmartEvent]:
        """
        Évalue toutes les conditions et retourne les events ACTIFS.

        Chaque condition produit au plus 1 event. Si la condition n'est plus
        vraie, l'event disparaît au cycle suivant.
        """
        events: list[SmartEvent] = []

        # ── Containers down / unhealthy ──
        for evt in self._check_containers(state):
            events.append(evt)

        # ── Pipelines bloqués ──
        for p in state.pipelines:
            evt = self._check_pipeline_stalled(state, p)
            if evt:
                events.append(evt)

        # ── Burst idle ──
        evt = self._check_burst_idle(state)
        if evt:
            events.append(evt)

        # ── LLM crédits ──
        for evt in self._check_llm_budget(state):
            events.append(evt)

        return events

    def _check_containers(self, state: CockpitState) -> list[SmartEvent]:
        """1 event par container problématique (down ou unhealthy).

        Les domain packs arretes sont ignores : ils sont optionnels
        et un pack desactive ne doit pas generer d'alerte.
        """
        events = []
        for group in state.container_groups:
            # Les domain packs down sont normaux (desactivation volontaire)
            is_domain_pack_group = group.name == "domain packs"

            for c in group.containers:
                if c.status == "down":
                    if is_domain_pack_group:
                        continue  # pack desactive = pas d'alerte
                    events.append(SmartEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        severity="critical",
                        category="container",
                        message=f"{c.name} DOWN",
                    ))
                elif c.health == "unhealthy":
                    events.append(SmartEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        severity="warning",
                        category="container",
                        message=f"{c.name} unhealthy",
                    ))
        return events

    def _check_pipeline_stalled(self, state: CockpitState, pipeline) -> Optional[SmartEvent]:
        """1 seul event par pipeline si sans progression."""
        if pipeline.current_stage_index < 0:
            return None

        current = pipeline.stages[pipeline.current_stage_index]
        key = pipeline.name  # tracker par pipeline

        if not hasattr(self, '_pipeline_stall_track'):
            self._pipeline_stall_track = {}

        prev = self._pipeline_stall_track.get(key, {})
        now = time.time()

        if (current.progress != prev.get('progress')
                or pipeline.current_stage_index != prev.get('stage_idx')):
            self._pipeline_stall_track[key] = {
                'progress': current.progress,
                'stage_idx': pipeline.current_stage_index,
                'ts': now,
            }
            return None

        stall_duration = now - prev.get('ts', now)
        if stall_duration > EVENT_STALL_THRESHOLD_S:
            minutes = int(stall_duration / 60)
            return SmartEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                severity="warning",
                category="pipeline",
                message=f"{pipeline.name} bloque sur {current.name} depuis {minutes}min",
            )

        return None

    def _check_burst_idle(self, state: CockpitState) -> Optional[SmartEvent]:
        """
        1 seul event si EC2 Burst est idle depuis plus d'1 heure.
        Se reset quand un pipeline burst est actif.
        """
        is_burst_active = state.burst.active and state.burst.status in ("ready", "booting")
        has_burst_pipeline = any(
            "burst" in (p.name or "").lower() for p in state.pipelines
        )

        if is_burst_active and not has_burst_pipeline:
            # Burst up mais pas utilisé
            if self._burst_idle_since is None:
                self._burst_idle_since = time.time()

            idle_s = time.time() - self._burst_idle_since

            if idle_s > EVENT_BURST_IDLE_S:
                hours = idle_s / 3600
                if hours >= 1:
                    duration_str = f"{hours:.1f}h"
                else:
                    duration_str = f"{int(idle_s / 60)}min"
                return SmartEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    severity="warning",
                    category="burst",
                    message=f"EC2 idle depuis {duration_str}",
                )
        else:
            # Burst utilisé ou éteint → reset du compteur
            self._burst_idle_since = None

        return None

    def _check_llm_budget(self, state: CockpitState) -> list[SmartEvent]:
        """1 event par provider si crédit bas."""
        events = []

        if state.llm_balances.openai_balance is not None:
            if state.llm_balances.openai_status == "critical":
                events.append(SmartEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    severity="critical",
                    category="budget",
                    message=f"OpenAI ${state.llm_balances.openai_balance:.2f}",
                ))
            elif state.llm_balances.openai_status == "low":
                events.append(SmartEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    severity="warning",
                    category="budget",
                    message=f"OpenAI credit bas ${state.llm_balances.openai_balance:.2f}",
                ))

        # NOTE: Anthropic n'expose pas de endpoint pour verifier le solde.
        # Les events Claude credit sont supprimes car ils generaient de
        # fausses alertes (balance toujours None → jamais declenches, ou
        # valeur fictive du collector → fausse alerte).

        return events
