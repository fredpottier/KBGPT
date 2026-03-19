"""
Router FastAPI pour la gestion GPU (Infrastructure EC2 Spot).

Source de vérité : AWS EC2 (via boto3).
À chaque health check, on scanne AWS pour trouver l'instance réelle,
puis on synchronise Redis et on vérifie les services vLLM/TEI.

Endpoints:
- GET  /api/gpu/health           - Health check vLLM + TEI (scan AWS + sync Redis)
- POST /api/gpu/restart-service  - Restart vLLM ou TEI via health-server EC2
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any

from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

import httpx
import time

settings = get_settings()
logger = setup_logging(settings.logs_dir, "gpu_router.log")

router = APIRouter(prefix="/api/gpu", tags=["gpu"])

# Cache pour éviter de spammer AWS à chaque polling (TTL 15s)
_aws_scan_cache: Dict[str, Any] = {}
_aws_scan_cache_time: float = 0
_AWS_SCAN_TTL = 15.0  # secondes


# ============================================================================
# Schemas Pydantic
# ============================================================================

class ServiceHealth(BaseModel):
    """Statut de santé d'un service GPU."""
    name: str
    status: str  # healthy, unhealthy, unreachable
    latency_ms: Optional[float] = None
    url: Optional[str] = None
    error: Optional[str] = None


class GpuHealthResponse(BaseModel):
    """Réponse du health check GPU."""
    instance_ip: Optional[str] = None
    services: list[ServiceHealth] = []
    all_healthy: bool = False
    source: str = "none"  # aws, redis_cache, none


class RestartServiceRequest(BaseModel):
    """Requête de restart d'un service."""
    service: Literal["vllm", "tei"] = Field(
        ..., description="Service à redémarrer: 'vllm' ou 'tei'"
    )


class RestartServiceResponse(BaseModel):
    """Réponse du restart de service."""
    success: bool
    service: str
    message: str
    health_after: Optional[ServiceHealth] = None


# ============================================================================
# AWS EC2 Discovery (source de vérité)
# ============================================================================

def _discover_instance_from_aws() -> Optional[Dict[str, str]]:
    """
    Scanne AWS EC2 via boto3 pour trouver l'instance Burst running.

    Cherche les instances avec tag Project=KnowWhere en état running.
    Retourne {ip, instance_id, instance_type} ou None.

    Cache de 15 secondes pour éviter de spammer l'API AWS.
    """
    global _aws_scan_cache, _aws_scan_cache_time

    now = time.time()
    if _aws_scan_cache and (now - _aws_scan_cache_time) < _AWS_SCAN_TTL:
        return _aws_scan_cache.get("result")

    try:
        import boto3

        ec2 = boto3.client("ec2", region_name="eu-central-1")
        response = ec2.describe_instances(
            Filters=[
                {"Name": "instance-state-name", "Values": ["running"]},
                {"Name": "tag:Project", "Values": ["KnowWhere"]},
            ]
        )

        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                ip = instance.get("PublicIpAddress")
                if ip:
                    found = {
                        "ip": ip,
                        "instance_id": instance.get("InstanceId", ""),
                        "instance_type": instance.get("InstanceType", ""),
                    }
                    logger.info(f"[GPU:AWS] Found running instance: {found['ip']} ({found['instance_type']})")
                    _aws_scan_cache = {"result": found}
                    _aws_scan_cache_time = now
                    return found

        # Aucune instance running
        logger.debug("[GPU:AWS] No running KnowWhere instance found")
        _aws_scan_cache = {"result": None}
        _aws_scan_cache_time = now
        return None

    except Exception as e:
        logger.warning(f"[GPU:AWS] Discovery failed: {e}")
        _aws_scan_cache = {"result": None}
        _aws_scan_cache_time = now
        return None


def _sync_redis_with_aws(instance_ip: str) -> None:
    """
    Met à jour Redis avec l'IP réelle de l'instance AWS.

    Si Redis contient une IP différente (stale), on la corrige.
    Si Redis est vide, on crée l'état.
    """
    vllm_url = f"http://{instance_ip}:8000"
    embeddings_url = f"http://{instance_ip}:8001"

    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis,
            set_burst_state_in_redis,
        )

        current = get_burst_state_from_redis()
        current_vllm = current.get("vllm_url", "") if current else ""

        if current_vllm != vllm_url:
            # Redis désynchronisé — corriger
            logger.info(
                f"[GPU:SYNC] Redis IP mismatch: Redis={current_vllm}, AWS={vllm_url}. Fixing."
            )
            set_burst_state_in_redis(
                vllm_url=vllm_url,
                vllm_model="Qwen/Qwen2.5-14B-Instruct-AWQ",
                embeddings_url=embeddings_url,
            )
    except Exception as e:
        logger.warning(f"[GPU:SYNC] Redis sync failed: {e}")


def _clear_redis_if_no_instance() -> None:
    """Purge Redis si aucune instance AWS n'est running."""
    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis,
            clear_burst_state_in_redis,
        )

        current = get_burst_state_from_redis()
        if current and current.get("active"):
            logger.info("[GPU:SYNC] No AWS instance running — purging stale Redis state")
            clear_burst_state_in_redis()
    except Exception as e:
        logger.warning(f"[GPU:SYNC] Redis cleanup failed: {e}")


# ============================================================================
# Endpoints
# ============================================================================

@router.get(
    "/health",
    response_model=GpuHealthResponse,
    summary="Health check vLLM + TEI",
    description="""
    Vérifie la santé des services vLLM et TEI sur l'instance EC2 GPU.

    Source de vérité : AWS EC2 (scan des instances running).
    Synchronise Redis automatiquement si l'IP a changé.
    Fallback Redis si AWS CLI non disponible dans le container.
    """
)
async def get_gpu_health(
    tenant_id: str = Depends(get_tenant_id),
) -> GpuHealthResponse:
    """Health check avec discovery AWS comme source de vérité."""

    instance_ip = None
    vllm_url = None
    embeddings_url = None
    source = "none"

    # 1. Source de vérité : AWS EC2
    aws_instance = _discover_instance_from_aws()
    if aws_instance:
        instance_ip = aws_instance["ip"]
        vllm_url = f"http://{instance_ip}:8000"
        embeddings_url = f"http://{instance_ip}:8001"
        source = "aws"

        # Synchroniser Redis avec la vraie IP
        _sync_redis_with_aws(instance_ip)
    else:
        # AWS CLI pas dispo ou aucune instance → fallback Redis
        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
            redis_state = get_burst_state_from_redis()
            if redis_state and redis_state.get("active"):
                vllm_url = redis_state.get("vllm_url")
                embeddings_url = redis_state.get("embeddings_url")
                if vllm_url:
                    import re
                    ip_match = re.search(r'http://([^:]+)', vllm_url)
                    if ip_match:
                        instance_ip = ip_match.group(1)
                        source = "redis_cache"
        except Exception:
            pass

    if not instance_ip:
        # Aucune instance nulle part — nettoyer Redis au cas où
        _clear_redis_if_no_instance()
        return GpuHealthResponse(source="none")

    # 2. Health check des services
    services: list[ServiceHealth] = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Check vLLM
        if vllm_url:
            try:
                start = time.monotonic()
                resp = await client.get(f"{vllm_url}/health")
                latency = (time.monotonic() - start) * 1000
                services.append(ServiceHealth(
                    name="vllm",
                    status="healthy" if resp.status_code == 200 else "unhealthy",
                    latency_ms=round(latency, 1),
                    url=vllm_url,
                ))
            except Exception as e:
                services.append(ServiceHealth(
                    name="vllm",
                    status="unreachable",
                    url=vllm_url,
                    error=str(e),
                ))

        # Check TEI (embeddings)
        if embeddings_url:
            try:
                start = time.monotonic()
                resp = await client.get(f"{embeddings_url}/health")
                latency = (time.monotonic() - start) * 1000
                services.append(ServiceHealth(
                    name="tei",
                    status="healthy" if resp.status_code == 200 else "unhealthy",
                    latency_ms=round(latency, 1),
                    url=embeddings_url,
                ))
            except Exception as e:
                services.append(ServiceHealth(
                    name="tei",
                    status="unreachable",
                    url=embeddings_url,
                    error=str(e),
                ))

    all_healthy = len(services) > 0 and all(s.status == "healthy" for s in services)

    # 3. Si les services sont unreachable et source=redis_cache, c'est un état stale
    if source == "redis_cache" and not all_healthy:
        all_unreachable = all(s.status == "unreachable" for s in services)
        if all_unreachable:
            logger.info("[GPU:HEALTH] Redis state stale (services unreachable) — purging")
            _clear_redis_if_no_instance()
            return GpuHealthResponse(source="none")

    # 4. Si healthy, s'assurer que Redis est à jour pour le worker
    if all_healthy and source == "aws":
        _sync_redis_with_aws(instance_ip)

    return GpuHealthResponse(
        instance_ip=instance_ip,
        services=services,
        all_healthy=all_healthy,
        source=source,
    )


@router.post(
    "/restart-service",
    response_model=RestartServiceResponse,
    summary="Restart vLLM ou TEI",
    description="""
    Redémarre un service sur l'instance EC2 GPU via le health-server (port 8080).
    """
)
async def restart_service(
    request: RestartServiceRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> RestartServiceResponse:
    """Redémarre un service GPU via le health-server EC2."""

    # Trouver l'IP réelle via AWS
    aws_instance = _discover_instance_from_aws()
    if not aws_instance:
        # Fallback orchestrateur
        try:
            from knowbase.ingestion.burst import get_burst_orchestrator
            orchestrator = get_burst_orchestrator()
            if orchestrator.state and orchestrator.state.instance_ip:
                instance_ip = orchestrator.state.instance_ip
            else:
                raise HTTPException(status_code=400, detail="Aucune instance EC2 active.")
        except ImportError:
            raise HTTPException(status_code=400, detail="Aucune instance EC2 active.")
    else:
        instance_ip = aws_instance["ip"]

    health_server_url = f"http://{instance_ip}:8080"
    vllm_url = f"http://{instance_ip}:8000"
    embeddings_url = f"http://{instance_ip}:8001"

    logger.info(f"[GPU] Restart {request.service} on {instance_ip}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{health_server_url}/restart/{request.service}")
            if resp.status_code == 200:
                logger.info(f"[GPU] Restart {request.service} initiated via health-server")

                import asyncio
                await asyncio.sleep(3)

                # Build a simple state-like object for _check_single_service
                class _State:
                    pass
                state = _State()
                state.vllm_url = vllm_url
                state.embeddings_url = embeddings_url

                health_after = await _check_single_service(client, request.service, state)

                return RestartServiceResponse(
                    success=True,
                    service=request.service,
                    message=f"Service {request.service} redémarré avec succès.",
                    health_after=health_after,
                )
            else:
                return RestartServiceResponse(
                    success=False,
                    service=request.service,
                    message=f"Health-server a retourné {resp.status_code}. "
                            f"Commande SSH manuelle: ssh ec2-user@{instance_ip} 'sudo systemctl restart {request.service}'",
                )

        except (httpx.ConnectError, httpx.ConnectTimeout):
            return RestartServiceResponse(
                success=False,
                service=request.service,
                message=f"Health-server non accessible sur {instance_ip}:8080. "
                        f"Commande SSH manuelle: ssh ec2-user@{instance_ip} 'sudo systemctl restart {request.service}'",
            )


async def _check_single_service(client: httpx.AsyncClient, service: str, state) -> ServiceHealth:
    """Health check d'un seul service après restart."""
    if service == "vllm" and state.vllm_url:
        url = state.vllm_url
        check_url = f"{url}/health"
    elif service == "tei" and state.embeddings_url:
        url = state.embeddings_url
        check_url = f"{url}/health"
    else:
        return ServiceHealth(name=service, status="unreachable")

    try:
        start = time.monotonic()
        resp = await client.get(check_url)
        latency = (time.monotonic() - start) * 1000
        return ServiceHealth(
            name=service,
            status="healthy" if resp.status_code == 200 else "unhealthy",
            latency_ms=round(latency, 1),
            url=url,
        )
    except Exception as e:
        return ServiceHealth(
            name=service,
            status="unreachable",
            url=url,
            error=str(e),
        )


__all__ = ["router"]
