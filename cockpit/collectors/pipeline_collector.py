"""
Collecteur Pipeline — lit l'état des pipelines depuis Redis.

Traduit chaque format Redis (hash ou JSON) vers le modèle PipelineStatus
en utilisant les définitions YAML.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import redis
import yaml

from cockpit.config import REDIS_URL, PIPELINE_DEFS_PATH
from cockpit.models import PipelineStatus, StageStatus

logger = logging.getLogger(__name__)


class PipelineCollector:
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._defs: dict = {}
        self._load_definitions()

    def _load_definitions(self):
        """Charge les définitions de pipelines depuis YAML (rechargé à chaque collect)."""
        try:
            mtime = os.path.getmtime(PIPELINE_DEFS_PATH)
            if mtime != getattr(self, '_defs_mtime', None):
                with open(PIPELINE_DEFS_PATH) as f:
                    self._defs = yaml.safe_load(f).get("pipelines", {})
                self._defs_mtime = mtime
                logger.info(f"[COCKPIT:PIPELINE] Definitions (re)loaded: {list(self._defs.keys())}")
        except Exception as e:
            logger.error(f"[COCKPIT:PIPELINE] Failed to load defs: {e}")

    def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    def collect(self) -> list[PipelineStatus]:
        """Retourne tous les pipelines actifs."""
        self._load_definitions()  # Hot-reload si YAML modifié
        rc = self._get_redis()
        active = []

        for pipeline_name, defn in self._defs.items():
            try:
                state = self._read_state(rc, defn)
                if state is None:
                    continue

                if self._is_active(state, defn):
                    active.append(self._build_pipeline_status(pipeline_name, state, defn))
            except Exception as e:
                logger.debug(f"[COCKPIT:PIPELINE] Error reading {pipeline_name}: {e}")

        return active

    def _read_state(self, rc: redis.Redis, defn: dict) -> Optional[dict]:
        """Lit l'état depuis Redis selon le type (hash ou json)."""
        key = defn["redis_key"]
        redis_type = defn.get("redis_type", "json")

        if redis_type == "hash":
            data = rc.hgetall(key)
            return data if data else None
        else:
            raw = rc.get(key)
            if raw:
                return json.loads(raw)
        return None

    def _is_active(self, state: dict, defn: dict) -> bool:
        """Détermine si le pipeline est actif."""
        status_field = defn.get("status_field", "status")
        current = state.get(status_field)
        active_when = defn.get("active_when", [])

        # Gérer les booléens (post-import: running=true)
        if isinstance(current, str) and current.lower() in ("true", "false"):
            current = current.lower() == "true"
        if isinstance(current, bool):
            return current in active_when

        return current in active_when

    def _build_pipeline_status(
        self, name: str, state: dict, defn: dict
    ) -> PipelineStatus:
        """Construit un PipelineStatus à partir de l'état Redis et de la définition."""
        display_name = defn.get("display_name", name.upper())
        stages_def = defn.get("stages", {})

        # Run ID
        run_id_field = defn.get("run_id_field")
        run_id = state.get(run_id_field, "") if run_id_field else ""

        # Started at
        started_field = defn.get("started_field", "started_at")
        started_at = state.get(started_field, "")

        # Elapsed
        elapsed_s = 0
        if started_at:
            try:
                started_ts = float(started_at)
                elapsed_s = int(time.time() - started_ts)
            except (ValueError, TypeError):
                # ISO format (ex: burst started_at)
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(str(started_at))
                    elapsed_s = int((datetime.now(timezone.utc) - dt).total_seconds())
                except Exception:
                    pass

        # Build stages
        if isinstance(stages_def, dict) and stages_def.get("dynamic"):
            stages, current_idx = self._build_dynamic_stages(state, stages_def, defn)
        else:
            stages, current_idx = self._build_static_stages(state, stages_def, defn)

        return PipelineStatus(
            name=display_name,
            run_id=str(run_id),
            started_at=str(started_at),
            elapsed_s=elapsed_s,
            stages=stages,
            current_stage_index=current_idx,
        )

    def _build_static_stages(
        self, state: dict, stages_def: list, defn: dict
    ) -> tuple[list[StageStatus], int]:
        """Construit les stages pour un pipeline à étapes fixes."""
        # Le champ qui indique la phase courante dépend du pipeline :
        # - ClaimFirst : "phase" (avec "phase_status" pour started/done/failed)
        # - Burst : "status" (le status_field EST la phase)
        current_phase = state.get("phase", "")
        phase_status = state.get("phase_status", "")

        # Si pas de champ "phase", utiliser le status_field comme phase
        if not current_phase:
            status_field = defn.get("status_field", "status")
            current_phase = state.get(status_field, "")
        stages = []
        current_idx = -1
        found_current = False

        for i, sdef in enumerate(stages_def):
            phase_match = sdef.get("phase_match", "")
            matches = phase_match if isinstance(phase_match, list) else [phase_match]

            if current_phase in matches:
                found_current = True
                current_idx = i

                # Progress pour stages itératives
                progress = None
                detail = None
                if sdef.get("iterable"):
                    pf = sdef.get("progress_fields", {})
                    done = self._safe_int(state.get(pf.get("done", ""), 0))
                    total = self._safe_int(state.get(pf.get("total", ""), 0))
                    if total > 0:
                        progress = round(done / total, 3)
                        detail = f"{done}/{total}"

                # Enrichir le detail avec current_question si present
                # (utilise par benchmark-ragas pour afficher la question en cours)
                current_q = state.get("current_question", "")
                if current_q:
                    detail = f"{detail} — {current_q}" if detail else current_q

                # Durée de la phase en cours
                duration = None
                phase_elapsed = state.get("phase_elapsed_s")
                if phase_elapsed:
                    try:
                        duration = float(phase_elapsed)
                    except (ValueError, TypeError):
                        pass

                status = "running"
                if phase_status == "done":
                    status = "done"
                elif phase_status == "failed":
                    status = "failed"

                stages.append(StageStatus(
                    name=sdef["name"],
                    short_name=sdef.get("short", sdef["name"][:5]),
                    status=status,
                    duration_s=duration,
                    progress=progress,
                    detail=detail,
                ))
            elif not found_current:
                # Avant la phase courante = terminé
                stages.append(StageStatus(
                    name=sdef["name"],
                    short_name=sdef.get("short", sdef["name"][:5]),
                    status="done",
                ))
            else:
                # Après la phase courante = en attente
                stages.append(StageStatus(
                    name=sdef["name"],
                    short_name=sdef.get("short", sdef["name"][:5]),
                    status="pending",
                ))

        # Cas particulier : la phase courante n'a matche AUCUN stage
        # (typiquement phase="init" ou "starting" pas declaree dans pipeline_defs).
        # Sans ce garde-fou, tous les stages sont marques "done" car ils tombent
        # dans la branche `not found_current` de la boucle. Forcer "pending"
        # pour refleter la realite : rien n'a encore commence.
        if current_idx == -1:
            stages = [
                StageStatus(
                    name=s.name,
                    short_name=s.short_name,
                    status="pending",
                )
                for s in stages
            ]

        return stages, current_idx

    def _build_dynamic_stages(
        self, state: dict, stages_def: dict, defn: dict
    ) -> tuple[list[StageStatus], int]:
        """Construit les stages pour un pipeline dynamique (post-import)."""
        completed = state.get(stages_def.get("completed_field", "completed_steps"), [])
        if isinstance(completed, str):
            try:
                completed = json.loads(completed)
            except (json.JSONDecodeError, TypeError):
                completed = []

        current = state.get(stages_def.get("current_field", "current_step_name"), "")
        progress_pct = state.get(stages_def.get("progress_field", "step_progress"), 0)
        detail = state.get(stages_def.get("detail_field", "step_detail"), "")
        total = self._safe_int(state.get(stages_def.get("total_field", "total_steps"), 0))

        # Reconstruire la liste des étapes depuis results
        results = state.get("results", [])
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except (json.JSONDecodeError, TypeError):
                results = []

        known_steps = defn.get("known_steps", {})
        stages = []
        current_idx = -1

        # Stages complétées
        for r in results:
            step_id = r.get("step_id", "")
            short = known_steps.get(step_id, step_id[:5])
            status = "done" if r.get("status") == "success" else "failed"
            stages.append(StageStatus(
                name=r.get("step_id", "?"),
                short_name=short,
                status=status,
                duration_s=r.get("duration_s"),
            ))

        # Stage en cours
        if current:
            current_idx = len(stages)
            short = known_steps.get(current, current[:5])
            try:
                prog = float(progress_pct) / 100.0
            except (ValueError, TypeError):
                prog = None
            stages.append(StageStatus(
                name=current,
                short_name=short,
                status="running",
                progress=prog,
                detail=str(detail) if detail else None,
            ))

        # Stages restantes (si on connait le total)
        remaining = total - len(stages)
        for j in range(max(0, remaining)):
            stages.append(StageStatus(
                name=f"step_{len(stages)+1}",
                short_name=f"S{len(stages)+1}",
                status="pending",
            ))

        return stages, current_idx

    @staticmethod
    def _safe_int(val, default: int = 0) -> int:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default
