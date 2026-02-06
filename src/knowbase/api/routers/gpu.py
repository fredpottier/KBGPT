"""
Router FastAPI pour la gestion GPU (Infrastructure EC2 Spot).

Endpoints légers pour le health check et le restart des services vLLM/TEI,
indépendamment du pipeline Burst.

Endpoints:
- GET  /api/gpu/health           - Health check vLLM + TEI (polling 5s)
- POST /api/gpu/restart-service  - Restart vLLM ou TEI via health-server EC2
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal

from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

import httpx
import time

settings = get_settings()
logger = setup_logging(settings.logs_dir, "gpu_router.log")

router = APIRouter(prefix="/api/gpu", tags=["gpu"])


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
# Endpoints
# ============================================================================

@router.get(
    "/health",
    response_model=GpuHealthResponse,
    summary="Health check vLLM + TEI",
    description="""
    Vérifie la santé des services vLLM et TEI sur l'instance EC2 GPU.

    - Timeout rapide (5s) pour un polling fréquent
    - Mesure la latence de chaque service
    - Retourne le statut individuel par service
    """
)
async def get_gpu_health(
    tenant_id: str = Depends(get_tenant_id),
) -> GpuHealthResponse:
    """Health check léger des services GPU."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state or not orchestrator.state.instance_ip:
            return GpuHealthResponse()

        state = orchestrator.state
        instance_ip = state.instance_ip
        vllm_url = state.vllm_url
        embeddings_url = state.embeddings_url

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

        return GpuHealthResponse(
            instance_ip=instance_ip,
            services=services,
            all_healthy=all_healthy,
        )

    except ImportError:
        return GpuHealthResponse()
    except Exception as e:
        logger.error(f"Erreur get_gpu_health: {e}")
        return GpuHealthResponse()


@router.post(
    "/restart-service",
    response_model=RestartServiceResponse,
    summary="Restart vLLM ou TEI",
    description="""
    Redémarre un service sur l'instance EC2 GPU via le health-server (port 8080).

    Si le health-server ne supporte pas `/restart`, retourne la commande SSH manuelle.
    Effectue un health check après le restart pour confirmer.
    """
)
async def restart_service(
    request: RestartServiceRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> RestartServiceResponse:
    """Redémarre un service GPU via le health-server EC2."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state or not orchestrator.state.instance_ip:
            raise HTTPException(
                status_code=400,
                detail="Aucune instance EC2 active."
            )

        instance_ip = orchestrator.state.instance_ip
        health_server_url = f"http://{instance_ip}:8080"

        logger.info(f"[GPU] Restart {request.service} on {instance_ip}")

        # Tenter le restart via health-server
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    f"{health_server_url}/restart/{request.service}"
                )
                if resp.status_code == 200:
                    logger.info(f"[GPU] Restart {request.service} initiated via health-server")

                    # Attendre un peu puis vérifier la santé
                    import asyncio
                    await asyncio.sleep(3)

                    # Health check post-restart
                    health_after = await _check_single_service(
                        client, request.service, orchestrator.state
                    )

                    return RestartServiceResponse(
                        success=True,
                        service=request.service,
                        message=f"Service {request.service} redémarré avec succès.",
                        health_after=health_after,
                    )
                else:
                    # Health-server a répondu mais avec erreur
                    return RestartServiceResponse(
                        success=False,
                        service=request.service,
                        message=f"Health-server a retourné {resp.status_code}. "
                                f"Commande SSH manuelle: ssh ec2-user@{instance_ip} 'sudo systemctl restart {request.service}'",
                    )

            except (httpx.ConnectError, httpx.ConnectTimeout):
                # Health-server non disponible - fallback commande SSH
                return RestartServiceResponse(
                    success=False,
                    service=request.service,
                    message=f"Health-server non accessible sur {instance_ip}:8080. "
                            f"Commande SSH manuelle: ssh ec2-user@{instance_ip} 'sudo systemctl restart {request.service}'",
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur restart_service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
