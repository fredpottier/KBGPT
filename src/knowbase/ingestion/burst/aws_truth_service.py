"""Burst EC2 reliability service — AWS-as-source-of-truth + divergence recovery.

CH-BURST.REL (19/05/2026) — Sprint dédié à la résilience du cycle de vie EC2 Burst.

Problème résolu : la page /admin/gpu et le worker d'ingestion s'appuyaient sur 3
états locaux (singleton in-memory, Redis 2 clés, fichier .burst_state.json) qui
pouvaient diverger silencieusement d'AWS dans 4 cas :

  1. Restart container knowbase-app → singleton perdu, AWS intact → "Destruction
     Stack" inerte (fixé partiellement par 94c7529).
  2. Spot interruption + respawn AWS auto → state local pointe sur ancienne IP,
     nouvelle instance vit avec IP différente → imports attendent indéfiniment.
  3. Clé Redis :live qui persistait 1h post-teardown (fixé par 4ecdc3d).
  4. Stack CloudFormation orpheline qui survit à un crash backend ou un click
     "Arrêter EC2" buggé.

Ce module fournit :
  - `discover_aws_truth()` : scan AWS + compare avec local, calcule divergence type
  - `auto_resync_to_aws()` : update silencieux quand AWS a une instance UP avec IP
    différente du local (cas respawn)
  - `force_cleanup()` : action utilisateur explicite (clean_local / clean_aws_orphans)
  - `publish_burst_resync_event()` : Redis pub/sub pour pousser au worker

Le worker s'abonne au channel `osmose:burst:resync` (cf burst_resync_subscriber.py)
et flushe son cache d'URL vLLM dès qu'un événement arrive, ce qui permet au
prochain call LLM de basculer sur la nouvelle IP sans attendre la fin du timeout
en cours.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


REDIS_RESYNC_CHANNEL = "osmose:burst:resync"


class DivergenceType(str, Enum):
    """Diagnostic de divergence entre AWS (source de vérité) et l'état local."""

    COHERENT = "coherent"
    ZOMBIE_LOCAL = "zombie_local"  # Local plein, AWS vide → cleanup local
    ORPHAN_AWS = "orphan_aws"  # AWS plein, local vide → cleanup AWS ou resync
    IP_MISMATCH = "ip_mismatch"  # Les deux pleins, mais IPs différentes (respawn)
    BOTH = "both"  # Cas pathologique : divergences multiples


@dataclass
class AwsView:
    """État réel observé sur AWS."""

    instances_running: list[dict[str, Any]] = field(default_factory=list)
    stacks_active: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_instance(self) -> bool:
        return any(
            i.get("state") in ("running", "pending") for i in self.instances_running
        )

    @property
    def has_stack(self) -> bool:
        return bool(self.stacks_active)

    @property
    def primary_instance(self) -> Optional[dict[str, Any]]:
        """Première instance running (cas standard : 1 SpotFleet → 1 instance)."""
        for inst in self.instances_running:
            if inst.get("state") in ("running", "pending"):
                return inst
        return None


@dataclass
class LocalView:
    """État local consolidé (singleton + Redis + fichier)."""

    singleton_instance_ip: Optional[str] = None
    singleton_instance_id: Optional[str] = None
    singleton_stack_name: Optional[str] = None
    redis_state_present: bool = False
    redis_state_vllm_url: Optional[str] = None
    redis_live_present: bool = False
    redis_live_instance_ip: Optional[str] = None
    file_present: bool = False

    @property
    def has_any_state(self) -> bool:
        """True si une quelconque source locale prétend avoir un état actif."""
        return (
            self.singleton_instance_ip is not None
            or self.singleton_stack_name is not None
            or self.redis_state_present
            or self.redis_live_present
            or self.file_present
        )

    @property
    def best_known_ip(self) -> Optional[str]:
        """IP la plus probable selon les sources locales (ordre : singleton > redis_live > redis_state)."""
        if self.singleton_instance_ip:
            return self.singleton_instance_ip
        if self.redis_live_instance_ip:
            return self.redis_live_instance_ip
        if self.redis_state_vllm_url:
            m = re.search(r"http://([^:/]+)", self.redis_state_vllm_url)
            if m:
                return m.group(1)
        return None


@dataclass
class AwsTruth:
    """Résultat consolidé de discover_aws_truth()."""

    aws: AwsView
    local: LocalView
    divergence_type: DivergenceType
    divergence_details: str
    can_start: bool
    can_force_cleanup: bool
    can_auto_resync: bool
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aws": {
                "instances_running": self.aws.instances_running,
                "stacks_active": self.aws.stacks_active,
                "has_instance": self.aws.has_instance,
                "has_stack": self.aws.has_stack,
            },
            "local": {
                "singleton_instance_ip": self.local.singleton_instance_ip,
                "singleton_instance_id": self.local.singleton_instance_id,
                "singleton_stack_name": self.local.singleton_stack_name,
                "redis_state_present": self.local.redis_state_present,
                "redis_state_vllm_url": self.local.redis_state_vllm_url,
                "redis_live_present": self.local.redis_live_present,
                "redis_live_instance_ip": self.local.redis_live_instance_ip,
                "file_present": self.local.file_present,
                "has_any_state": self.local.has_any_state,
                "best_known_ip": self.local.best_known_ip,
            },
            "divergence_type": self.divergence_type.value,
            "divergence_details": self.divergence_details,
            "can_start": self.can_start,
            "can_force_cleanup": self.can_force_cleanup,
            "can_auto_resync": self.can_auto_resync,
            "computed_at": self.computed_at,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────────────────────────


def _scan_aws() -> AwsView:
    """Scan AWS : instances Project=KnowWhere + stacks knowwhere-burst-*."""
    view = AwsView()
    try:
        import boto3

        region = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
        ec2 = boto3.client("ec2", region_name=region)

        # Instances avec tag Project=KnowWhere
        resp = ec2.describe_instances(
            Filters=[
                {
                    "Name": "instance-state-name",
                    "Values": [
                        "running",
                        "pending",
                        "shutting-down",
                        "stopping",
                    ],
                },
                {"Name": "tag:Project", "Values": ["KnowWhere"]},
            ]
        )
        for reservation in resp.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                view.instances_running.append(
                    {
                        "instance_id": inst.get("InstanceId"),
                        "state": inst.get("State", {}).get("Name"),
                        "public_ip": inst.get("PublicIpAddress"),
                        "instance_type": inst.get("InstanceType"),
                        "availability_zone": inst.get("Placement", {}).get(
                            "AvailabilityZone"
                        ),
                        "launch_time": (
                            inst.get("LaunchTime").isoformat()
                            if inst.get("LaunchTime")
                            else None
                        ),
                    }
                )
    except Exception as e:
        logger.warning(f"[AWS_TRUTH] EC2 scan failed: {e}")

    try:
        import boto3

        region = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
        cf = boto3.client("cloudformation", region_name=region)
        resp = cf.describe_stacks()
        for stack in resp.get("Stacks", []):
            name = stack.get("StackName", "")
            status = stack.get("StackStatus", "")
            if name.startswith("knowwhere-burst-") and status not in (
                "DELETE_COMPLETE",
                "DELETE_IN_PROGRESS",
            ):
                view.stacks_active.append(
                    {
                        "stack_name": name,
                        "status": status,
                        "created": (
                            stack.get("CreationTime").isoformat()
                            if stack.get("CreationTime")
                            else None
                        ),
                    }
                )
    except Exception as e:
        logger.warning(f"[AWS_TRUTH] CloudFormation scan failed: {e}")

    return view


def _scan_local() -> LocalView:
    """Consolide les sources locales : singleton, Redis 2 clés, fichier."""
    view = LocalView()

    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()
        if orchestrator.state:
            view.singleton_instance_ip = orchestrator.state.instance_ip
            view.singleton_instance_id = orchestrator.state.instance_id
            view.singleton_stack_name = orchestrator.state.stack_name
    except Exception as e:
        logger.debug(f"[AWS_TRUTH] Singleton read failed: {e}")

    try:
        from knowbase.ingestion.burst.provider_switch import (
            REDIS_BURST_LIVE_KEY,
            REDIS_BURST_STATE_KEY,
            _get_redis_client,
        )

        redis = _get_redis_client()
        if redis:
            state_raw = redis.client.get(REDIS_BURST_STATE_KEY)
            if state_raw:
                view.redis_state_present = True
                try:
                    state_data = json.loads(state_raw)
                    view.redis_state_vllm_url = state_data.get("vllm_url")
                except (json.JSONDecodeError, AttributeError):
                    pass

            live_raw = redis.client.get(REDIS_BURST_LIVE_KEY)
            if live_raw:
                view.redis_live_present = True
                try:
                    live_data = json.loads(live_raw)
                    view.redis_live_instance_ip = live_data.get("instance_ip") or None
                except (json.JSONDecodeError, AttributeError):
                    pass
    except Exception as e:
        logger.debug(f"[AWS_TRUTH] Redis read failed: {e}")

    try:
        from knowbase.ingestion.burst.provider_switch import BURST_STATE_FILE

        if os.path.exists(BURST_STATE_FILE):
            view.file_present = True
    except Exception as e:
        logger.debug(f"[AWS_TRUTH] File check failed: {e}")

    return view


def _compute_divergence(aws: AwsView, local: LocalView) -> tuple[DivergenceType, str]:
    """Calcule le type de divergence entre AWS et local + détails humains."""
    aws_has = aws.has_instance or aws.has_stack
    local_has = local.has_any_state

    if not aws_has and not local_has:
        return DivergenceType.COHERENT, "AWS et local cohérents (aucun burst actif)"

    if not aws_has and local_has:
        return (
            DivergenceType.ZOMBIE_LOCAL,
            "Aucune ressource AWS détectée mais l'état local prétend qu'une "
            "instance est active. Cause probable : restart du container backend "
            "ou clé Redis :live périmée (TTL 1h).",
        )

    if aws_has and not local_has:
        return (
            DivergenceType.ORPHAN_AWS,
            f"Instance ou stack AWS détectée ({len(aws.instances_running)} instance(s), "
            f"{len(aws.stacks_active)} stack(s)) mais aucun état local. Cause probable : "
            "container backend redémarré pendant que l'infra AWS tournait.",
        )

    # Les deux ont des données : comparer chaque source locale vs AWS IP
    aws_ip = aws.primary_instance.get("public_ip") if aws.primary_instance else None
    if not aws_ip:
        return DivergenceType.COHERENT, "AWS et local cohérents (instance active)"

    # Inventaire des IPs annoncées par les différentes sources locales
    local_sources: list[tuple[str, str]] = []  # (source_name, ip)
    if local.singleton_instance_ip:
        local_sources.append(("singleton", local.singleton_instance_ip))
    if local.redis_live_instance_ip:
        local_sources.append(("redis:live", local.redis_live_instance_ip))
    if local.redis_state_vllm_url:
        m = re.search(r"http://([^:/]+)", local.redis_state_vllm_url)
        if m:
            local_sources.append(("redis:state", m.group(1)))

    # Une source diverge de AWS → IP_MISMATCH (couvre spot respawn ET :live périmé)
    mismatched = [(name, ip) for name, ip in local_sources if ip != aws_ip]
    if mismatched:
        sources_str = ", ".join(f"{name}={ip}" for name, ip in mismatched)
        return (
            DivergenceType.IP_MISMATCH,
            f"AWS pointe sur {aws_ip} mais source(s) locale(s) divergent(s) : "
            f"{sources_str}. Cause probable : spot interruption + respawn (SpotFleet "
            "a recréé une instance) ou clé Redis :live périmée non rafraîchie.",
        )

    return DivergenceType.COHERENT, "AWS et local cohérents (instance active)"


def discover_aws_truth() -> AwsTruth:
    """Scan AWS + consolide local + calcule divergence. Action read-only."""
    aws = _scan_aws()
    local = _scan_local()
    div_type, div_details = _compute_divergence(aws, local)

    # can_start = peut-on lancer une nouvelle instance sans collision ?
    can_start = not (aws.has_instance or aws.has_stack)
    # can_force_cleanup = y a-t-il quelque chose à nettoyer ?
    can_force_cleanup = div_type != DivergenceType.COHERENT
    # can_auto_resync = peut-on resync silencieusement ?
    can_auto_resync = div_type == DivergenceType.IP_MISMATCH

    return AwsTruth(
        aws=aws,
        local=local,
        divergence_type=div_type,
        divergence_details=div_details,
        can_start=can_start,
        can_force_cleanup=can_force_cleanup,
        can_auto_resync=can_auto_resync,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auto-resync (IP_MISMATCH case)
# ─────────────────────────────────────────────────────────────────────────────


def auto_resync_to_aws(truth: Optional[AwsTruth] = None) -> dict[str, Any]:
    """Resync silencieux : met à jour singleton + Redis avec l'IP AWS réelle.

    Appelé automatiquement quand le diagnostic est IP_MISMATCH. Publie ensuite
    un événement Redis pub/sub pour notifier le worker en cours d'ingestion.

    Returns:
        Dict with keys: resynced, old_ip, new_ip, action_log
    """
    if truth is None:
        truth = discover_aws_truth()

    result: dict[str, Any] = {
        "resynced": False,
        "old_ip": truth.local.best_known_ip,
        "new_ip": None,
        "action_log": [],
    }

    if truth.divergence_type != DivergenceType.IP_MISMATCH:
        result["action_log"].append(
            f"No resync needed (divergence type={truth.divergence_type.value})"
        )
        return result

    primary = truth.aws.primary_instance
    if not primary or not primary.get("public_ip"):
        result["action_log"].append("AWS primary instance has no public_ip")
        return result

    new_ip = primary["public_ip"]
    new_instance_id = primary.get("instance_id")
    new_vllm_url = f"http://{new_ip}:8000"
    new_embeddings_url = f"http://{new_ip}:8001"
    result["new_ip"] = new_ip

    # 1. Update singleton
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()
        if orchestrator.state:
            orchestrator.state.instance_ip = new_ip
            orchestrator.state.instance_id = new_instance_id
            orchestrator.state.instance_type = primary.get("instance_type")
            orchestrator.state.vllm_url = new_vllm_url
            orchestrator.state.embeddings_url = new_embeddings_url
            orchestrator.state.interruption_count += 1
            result["action_log"].append(
                f"Singleton updated: instance_id={new_instance_id}, ip={new_ip}"
            )
    except Exception as e:
        result["action_log"].append(f"Singleton update failed: {e}")

    # 2. Update Redis state (key osmose:burst:state)
    try:
        from knowbase.ingestion.burst.provider_switch import set_burst_state_in_redis

        ok = set_burst_state_in_redis(
            vllm_url=new_vllm_url,
            vllm_model=os.getenv(
                "V5_VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ"
            ),
            embeddings_url=new_embeddings_url,
        )
        if ok:
            result["action_log"].append(f"Redis state updated: vllm_url={new_vllm_url}")
    except Exception as e:
        result["action_log"].append(f"Redis state update failed: {e}")

    # 3. Purge la clé :live (stale heartbeat) — le prochain heartbeat la reconstruira
    # avec la bonne IP. Sans ça, le cockpit continue d'afficher l'ancienne IP.
    try:
        from knowbase.ingestion.burst.provider_switch import (
            REDIS_BURST_LIVE_KEY,
            _get_redis_client,
        )

        redis = _get_redis_client()
        if redis and redis.client.delete(REDIS_BURST_LIVE_KEY):
            result["action_log"].append(
                f"Redis {REDIS_BURST_LIVE_KEY} purgé (sera reconstruit au prochain heartbeat)"
            )
    except Exception as e:
        result["action_log"].append(f"Redis :live purge failed: {e}")

    # 4. Publish pub/sub event for worker (immediate refresh)
    try:
        published = publish_burst_resync_event(
            new_vllm_url=new_vllm_url,
            new_instance_id=new_instance_id,
            reason="ip_mismatch_resync",
        )
        if published:
            result["action_log"].append(
                f"Pub/sub event published on '{REDIS_RESYNC_CHANNEL}' "
                f"(workers will refresh next LLM call)"
            )
    except Exception as e:
        result["action_log"].append(f"Pub/sub publish failed: {e}")

    result["resynced"] = True
    logger.info(
        f"[AWS_TRUTH] Auto-resync done: {truth.local.best_known_ip} → {new_ip} "
        f"(instance_id={new_instance_id})"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Force cleanup
# ─────────────────────────────────────────────────────────────────────────────


def force_cleanup(
    clean_local: bool = True,
    clean_aws_orphans: bool = False,
    truth: Optional[AwsTruth] = None,
) -> dict[str, Any]:
    """Nettoyage explicite déclenché par l'utilisateur.

    Args:
        clean_local: reset singleton + purge Redis 2 clés + delete fichier
        clean_aws_orphans: delete les stacks AWS knowwhere-burst-* détectées
        truth: optionnel, sinon discover_aws_truth() est appelé

    Returns:
        Dict with action_log + final state after cleanup
    """
    if truth is None:
        truth = discover_aws_truth()

    result: dict[str, Any] = {
        "clean_local_done": False,
        "stacks_deleted": [],
        "stacks_failed": [],
        "action_log": [],
    }

    if clean_local:
        try:
            from knowbase.ingestion.burst import get_burst_orchestrator
            from knowbase.ingestion.burst.provider_switch import (
                clear_burst_state_in_redis,
                deactivate_burst_providers,
            )

            # Reset singleton
            orchestrator = get_burst_orchestrator()
            if orchestrator.state:
                orchestrator.state = None
                result["action_log"].append("Singleton.state reset to None")

            # Purge Redis state + state:live + file (déjà groupés dans la fonction)
            deactivate_burst_providers()
            clear_burst_state_in_redis()
            result["action_log"].append(
                "Redis state + state:live + file purgés via clear_burst_state_in_redis()"
            )
            result["clean_local_done"] = True
        except Exception as e:
            result["action_log"].append(f"Clean local failed: {e}")

    if clean_aws_orphans:
        try:
            import boto3

            region = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
            cf = boto3.client("cloudformation", region_name=region)

            for stack in truth.aws.stacks_active:
                name = stack.get("stack_name")
                if not name:
                    continue
                try:
                    cf.delete_stack(StackName=name)
                    result["stacks_deleted"].append(name)
                    result["action_log"].append(
                        f"delete_stack initiated: {name} (was {stack.get('status')})"
                    )
                    logger.info(f"[AWS_TRUTH] Orphan stack deletion initiated: {name}")
                except Exception as e:
                    result["stacks_failed"].append({"name": name, "error": str(e)})
                    result["action_log"].append(f"delete_stack FAILED for {name}: {e}")
                    logger.error(
                        f"[AWS_TRUTH] Failed to delete orphan stack {name}: {e}"
                    )
        except Exception as e:
            result["action_log"].append(f"CF client init failed: {e}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Pub/sub
# ─────────────────────────────────────────────────────────────────────────────


def publish_burst_resync_event(
    new_vllm_url: str,
    new_instance_id: Optional[str] = None,
    reason: str = "manual",
) -> bool:
    """Publie un événement Redis pub/sub pour notifier les workers d'un changement
    d'URL vLLM. Les workers abonnés au channel REDIS_RESYNC_CHANNEL flushent
    immédiatement leur cache et re-lisent le state Redis au prochain call LLM.

    Returns:
        True si publié, False sinon (Redis indisponible).
    """
    try:
        import redis as _redis

        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = os.getenv("REDIS_PASSWORD") or None
        rc = _redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
        )

        payload = json.dumps(
            {
                "vllm_url": new_vllm_url,
                "instance_id": new_instance_id,
                "reason": reason,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        receivers = rc.publish(REDIS_RESYNC_CHANNEL, payload)
        rc.close()
        logger.info(
            f"[AWS_TRUTH] Pub/sub event published on '{REDIS_RESYNC_CHANNEL}' "
            f"to {receivers} subscriber(s) (reason={reason})"
        )
        return True
    except Exception as e:
        logger.warning(f"[AWS_TRUTH] Pub/sub publish failed: {e}")
        return False
