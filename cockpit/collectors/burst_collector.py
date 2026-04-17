"""
Collecteur EC2 Burst — source de vérité = AWS EC2 API.

JAMAIS Redis pour l'état EC2 (désync connue lors des recalls Spot).
Redis utilisé UNIQUEMENT pour le contexte job (batch_id, docs done/total).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import redis

from cockpit.config import (
    AWS_REGION, AWS_BURST_REGIONS, AWS_EC2_TAG_KEY, AWS_EC2_TAG_VALUE,
    AWS_SCAN_CACHE_TTL, REDIS_URL,
)
from cockpit.models import BurstStatus

logger = logging.getLogger(__name__)

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


class BurstCollector:
    def __init__(self):
        self._ec2_clients: dict = {}
        self._cache: Optional[BurstStatus] = None
        self._cache_ts: float = 0
        self._redis: Optional[redis.Redis] = None
        # Pour calcul débit tokens/s (delta entre 2 collectes)
        self._prev_prompt_tokens: float = 0
        self._prev_gen_tokens: float = 0
        self._prev_tokens_ts: float = 0

    def _get_ec2(self, region: str = AWS_REGION):
        if not BOTO3_AVAILABLE:
            return None
        if region not in self._ec2_clients:
            self._ec2_clients[region] = boto3.client("ec2", region_name=region)
        return self._ec2_clients[region]

    def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    def collect(self) -> BurstStatus:
        """Collecte l'état EC2 Burst — AWS API comme unique source de vérité."""
        now = time.time()
        if self._cache and (now - self._cache_ts) < AWS_SCAN_CACHE_TTL:
            return self._cache

        if not BOTO3_AVAILABLE:
            return BurstStatus(active=False, status="off")

        # 1. Interroger AWS EC2 — seule source de vérité (multi-région)
        instance = self._discover_from_aws_multi_region()

        if not instance:
            self._cache = BurstStatus(active=False, status="off")
            self._cache_ts = now
            return self._cache

        ip = instance["ip"]
        aws_state = instance["state"]  # running|pending|stopping|shutting-down

        # 2. Health check services (vLLM + TEI)
        vllm_ok = self._check_health(f"http://{ip}:8000/health")
        tei_ok = self._check_health(f"http://{ip}:8001/health")

        # 3. Déduire le statut cockpit
        if aws_state == "pending":
            status = "starting"
        elif aws_state in ("stopping", "shutting-down"):
            status = "stopping"
        elif vllm_ok and tei_ok:
            status = "ready"
        elif aws_state == "running":
            status = "booting"
        else:
            status = "off"

        # 4. Uptime depuis LaunchTime AWS
        launch_time = instance.get("launch_time")
        uptime_s = None
        if launch_time:
            uptime_s = int((datetime.now(timezone.utc) - launch_time).total_seconds())

        # 5. Context job depuis Redis (optionnel, non-bloquant)
        job_info = self._read_redis_job_context()

        # 6. Métriques de charge vLLM/TEI
        vllm_metrics = self._fetch_vllm_metrics(ip) if vllm_ok else {}
        tei_metrics = self._fetch_tei_metrics(ip) if tei_ok else {}

        result = BurstStatus(
            active=True,
            status=status,
            instance_ip=ip,
            instance_id=instance.get("instance_id"),
            instance_type=instance.get("instance_type"),
            instance_state=aws_state,
            instance_region=instance.get("region"),
            uptime_s=uptime_s,
            vllm_healthy=vllm_ok,
            tei_healthy=tei_ok,
            job_name=job_info.get("batch_id"),
            docs_done=job_info.get("documents_done"),
            docs_total=job_info.get("total_documents"),
            vllm_requests_running=vllm_metrics.get("running", 0),
            vllm_requests_waiting=vllm_metrics.get("waiting", 0),
            vllm_gpu_cache_pct=vllm_metrics.get("gpu_cache_pct", 0),
            vllm_tokens_per_sec=vllm_metrics.get("tokens_per_sec", 0),
            tei_queue_size=tei_metrics.get("queue_size", 0),
        )

        self._cache = result
        self._cache_ts = now
        return result

    def _discover_from_aws_multi_region(self) -> Optional[dict]:
        """Scanne EC2 dans toutes les régions burst configurées."""
        for region in AWS_BURST_REGIONS:
            ec2 = self._get_ec2(region)
            if ec2 is None:
                continue
            result = self._discover_from_aws(ec2, region)
            if result:
                return result
        return None

    def _discover_from_aws(self, ec2, region: str) -> Optional[dict]:
        """Scanne EC2 pour trouver l'instance Burst dans une région."""
        try:
            response = ec2.describe_instances(Filters=[
                {"Name": "instance-state-name", "Values": ["running", "pending", "stopping"]},
                {"Name": f"tag:{AWS_EC2_TAG_KEY}", "Values": [AWS_EC2_TAG_VALUE]},
            ])

            for reservation in response.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    ip = inst.get("PublicIpAddress")
                    if ip:
                        return {
                            "ip": ip,
                            "instance_id": inst.get("InstanceId", ""),
                            "instance_type": inst.get("InstanceType", ""),
                            "state": inst["State"]["Name"],
                            "launch_time": inst.get("LaunchTime"),
                            "region": region,
                        }
        except Exception as e:
            logger.warning(f"[COCKPIT:BURST] AWS scan {region} failed: {e}")

        return None

    def _check_health(self, url: str) -> bool:
        """Health check HTTP rapide."""
        try:
            import httpx
            resp = httpx.get(url, timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    def _fetch_vllm_metrics(self, ip: str) -> dict:
        """Parse les métriques Prometheus de vLLM.

        Note: vLLM >= 0.6 préfixe les métriques avec 'vllm:' (ex: vllm:num_requests_running).
        On matche sur le suffixe pour être compatible avec et sans préfixe.
        """
        try:
            import httpx
            resp = httpx.get(f"http://{ip}:8000/metrics", timeout=3.0)
            if resp.status_code != 200:
                return {}
            result = {}
            prompt_tokens = 0.0
            gen_tokens = 0.0
            for line in resp.text.split("\n"):
                if line.startswith("#"):
                    continue
                if "num_requests_running{" in line:
                    result["running"] = int(float(line.split()[-1]))
                elif "num_requests_waiting{" in line:
                    result["waiting"] = int(float(line.split()[-1]))
                elif "gpu_cache_usage_perc{" in line:
                    result["gpu_cache_pct"] = round(float(line.split()[-1]) * 100, 1)
                elif "prompt_tokens_total{" in line:
                    prompt_tokens = float(line.split()[-1])
                elif "generation_tokens_total{" in line:
                    gen_tokens = float(line.split()[-1])

            # Calcul débit tokens/s (delta entre 2 collectes)
            now = time.time()
            dt = now - self._prev_tokens_ts if self._prev_tokens_ts > 0 else 0
            if dt > 1:
                delta_prompt = prompt_tokens - self._prev_prompt_tokens
                delta_gen = gen_tokens - self._prev_gen_tokens
                result["tokens_per_sec"] = round((delta_prompt + delta_gen) / dt, 1)
            else:
                result["tokens_per_sec"] = 0
            self._prev_prompt_tokens = prompt_tokens
            self._prev_gen_tokens = gen_tokens
            self._prev_tokens_ts = now

            return result
        except Exception:
            return {}

    def _fetch_tei_metrics(self, ip: str) -> dict:
        """Parse les métriques TEI."""
        try:
            import httpx
            resp = httpx.get(f"http://{ip}:8001/metrics", timeout=3.0)
            if resp.status_code != 200:
                return {}
            result = {}
            for line in resp.text.split("\n"):
                if line.startswith("#"):
                    continue
                if "te_queue_size" in line:
                    result["queue_size"] = int(float(line.split()[-1]))
            return result
        except Exception:
            return {}

    def _read_redis_job_context(self) -> dict:
        """Lit le contexte du job depuis Redis (non-bloquant)."""
        try:
            rc = self._get_redis()
            # Essayer d'abord le state live (émis par le burst orchestrator instrumenté)
            raw = rc.get("osmose:burst:state:live")
            if raw:
                return json.loads(raw)
            # Fallback sur l'ancien format
            raw = rc.get("osmose:burst:state")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return {}
