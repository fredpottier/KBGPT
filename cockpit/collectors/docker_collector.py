"""
Collecteur Docker — état des conteneurs avec activité CPU.

Utilise le Docker SDK Python pour lire l'état et les stats de chaque conteneur.
Groupe les conteneurs par catégorie (infra / app / monitoring).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import docker
from docker.errors import DockerException

from cockpit.config import DOCKER_GROUPS, DOMAIN_PACK_PREFIX
from cockpit.models import ContainerStatus, ContainerGroupStatus

logger = logging.getLogger(__name__)


class DockerCollector:
    def __init__(self):
        self._client: Optional[docker.DockerClient] = None
        self._last_cpu: dict[str, dict] = {}  # cache pour calcul delta CPU

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as e:
                logger.error(f"[COCKPIT:DOCKER] Cannot connect to Docker: {e}")
                raise
        return self._client

    def _calc_cpu_percent(self, stats: dict) -> float:
        """Calcule le % CPU à partir des stats Docker (delta-based)."""
        try:
            cpu = stats["cpu_stats"]
            precpu = stats["precpu_stats"]

            cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
            system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)

            if system_delta > 0 and cpu_delta >= 0:
                # cpu_delta / system_delta donne le ratio sur tous les coeurs
                # On veut un % sur 100 (pas 1600% pour 16 coeurs)
                return round((cpu_delta / system_delta) * 100, 1)
        except (KeyError, TypeError, ZeroDivisionError):
            pass
        return 0.0

    def _calc_mem_percent(self, stats: dict) -> float:
        """Calcule le % mémoire."""
        try:
            mem = stats["memory_stats"]
            usage = mem["usage"] - mem.get("stats", {}).get("cache", 0)
            limit = mem["limit"]
            if limit > 0:
                return round((usage / limit) * 100, 1)
        except (KeyError, TypeError, ZeroDivisionError):
            pass
        return 0.0

    def _calc_uptime(self, container) -> Optional[int]:
        """Calcule l'uptime en secondes."""
        try:
            started = container.attrs["State"].get("StartedAt", "")
            if started and "0001-01-01" not in started:
                from datetime import datetime, timezone
                # Docker timestamps : "2026-03-28T10:15:30.123456789Z"
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                return int((datetime.now(timezone.utc) - started_dt).total_seconds())
        except Exception:
            pass
        return None

    def _map_status(self, container) -> tuple[str, Optional[str]]:
        """Retourne (status, health) depuis les attrs du conteneur."""
        state = container.attrs.get("State", {})
        running = state.get("Running", False)
        health_obj = state.get("Health", {})
        health = health_obj.get("Status") if health_obj else None

        if not running:
            return "down", None
        if health == "unhealthy":
            return "up", "unhealthy"
        if health == "healthy":
            return "up", "healthy"
        return "up", None

    def collect(self) -> list[ContainerGroupStatus]:
        """Collecte l'état de tous les conteneurs groupés."""
        try:
            client = self._get_client()
        except DockerException:
            return []

        try:
            containers = client.containers.list(all=True)
        except DockerException as e:
            logger.error(f"[COCKPIT:DOCKER] list failed: {e}")
            return []

        # Index par nom de service compose ET par nom de container
        by_service: dict[str, docker.models.containers.Container] = {}
        domain_packs: list[docker.models.containers.Container] = []

        for c in containers:
            svc = c.labels.get("com.docker.compose.service", "")
            if svc:
                by_service[svc] = c
            # Détecter les domain packs par nom de container
            if c.name and c.name.startswith(DOMAIN_PACK_PREFIX):
                domain_packs.append(c)

        groups = []
        for group_name, service_names in DOCKER_GROUPS.items():
            statuses = []
            for svc_name in service_names:
                c = by_service.get(svc_name)
                if c is None:
                    statuses.append(ContainerStatus(
                        name=svc_name, status="down", activity="idle",
                    ))
                    continue
                statuses.append(self._build_container_status(c, svc_name))
            groups.append(ContainerGroupStatus(name=group_name, containers=statuses))

        # Domain Packs (groupe dynamique)
        if domain_packs:
            pack_statuses = []
            for c in domain_packs:
                # Nom lisible : "osmose-pack-enterprise_sap" → "enterprise_sap"
                display_name = c.name.replace(DOMAIN_PACK_PREFIX, "")
                pack_statuses.append(self._build_container_status(c, display_name))
            groups.append(ContainerGroupStatus(name="domain packs", containers=pack_statuses))

        return groups

    def _build_container_status(self, c, display_name: str) -> ContainerStatus:
        """Construit un ContainerStatus depuis un container Docker."""
        status, health = self._map_status(c)

        cpu_pct = 0.0
        mem_pct = 0.0
        if status == "up":
            try:
                stats = c.stats(stream=False)
                cpu_pct = self._calc_cpu_percent(stats)
                mem_pct = self._calc_mem_percent(stats)
            except Exception:
                pass

        if cpu_pct > 50:
            activity = "busy"
        elif cpu_pct > 2:
            activity = "active"
        else:
            activity = "idle"

        return ContainerStatus(
            name=display_name,
            status=status,
            health=health,
            uptime_s=self._calc_uptime(c),
            cpu_percent=cpu_pct,
            mem_percent=mem_pct,
            activity=activity,
        )
