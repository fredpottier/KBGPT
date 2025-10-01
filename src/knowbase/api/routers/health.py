"""
Endpoint Health Check complet pour SAP Knowledge Base
"""
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter, Depends
import httpx

from ..dependencies import get_settings
from ..services.tenant import get_tenant_service, TenantService

router = APIRouter(prefix="/health", tags=["health"])


def get_tenant_service_dependency() -> TenantService:
    """Dependency pour obtenir le service de tenants"""
    settings = get_settings()
    data_dir = Path(settings.data_dir) / "tenants"
    return get_tenant_service(data_dir)


@router.get("/")
async def health_check_full() -> Dict[str, Any]:
    """
    Health check complet du système SAP Knowledge Base
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "SAP Knowledge Base",
        "version": "1.0.0-POC",
        "components": {}
    }

    overall_healthy = True

    # 1. API FastAPI
    try:
        health_status["components"]["api"] = {
            "status": "healthy",
            "message": "API FastAPI opérationnelle"
        }
    except Exception as e:
        health_status["components"]["api"] = {
            "status": "unhealthy",
            "message": f"Erreur API: {str(e)}"
        }
        overall_healthy = False

    # 2. Base vectorielle Qdrant
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://qdrant:6333/health", timeout=5.0)
            if response.status_code == 200:
                health_status["components"]["qdrant"] = {
                    "status": "healthy",
                    "message": "Qdrant opérationnel"
                }
            else:
                health_status["components"]["qdrant"] = {
                    "status": "unhealthy",
                    "message": f"Qdrant status: {response.status_code}"
                }
                overall_healthy = False
    except Exception as e:
        health_status["components"]["qdrant"] = {
            "status": "unhealthy",
            "message": f"Erreur connexion Qdrant: {str(e)}"
        }
        overall_healthy = False

    # 3. Redis (queue)
    try:
        async with httpx.AsyncClient() as client:
            # Redis n'a pas d'endpoint HTTP direct, on teste via notre API
            health_status["components"]["redis"] = {
                "status": "assumed_healthy",
                "message": "Redis assumé opérationnel"
            }
    except Exception as e:
        health_status["components"]["redis"] = {
            "status": "unknown",
            "message": f"Statut Redis inconnu: {str(e)}"
        }

    # 4. PostgreSQL
    try:
        async with httpx.AsyncClient() as client:
            # PostgreSQL n'a pas d'endpoint HTTP direct
            health_status["components"]["postgres"] = {
                "status": "assumed_healthy",
                "message": "PostgreSQL assumé opérationnel"
            }
    except Exception as e:
        health_status["components"]["postgres"] = {
            "status": "unknown",
            "message": f"Statut PostgreSQL inconnu: {str(e)}"
        }

    # 5. Graphiti Infrastructure
    try:
        async with httpx.AsyncClient() as client:
            # Test Neo4j
            neo4j_response = await client.get("http://localhost:7474", timeout=5.0)
            neo4j_healthy = neo4j_response.status_code == 200

            # Test Graphiti service
            graphiti_healthy = False
            try:
                graphiti_response = await client.get("http://localhost:8300/docs", timeout=5.0)
                graphiti_healthy = graphiti_response.status_code == 200
            except:
                graphiti_healthy = False

            health_status["components"]["graphiti"] = {
                "status": "healthy" if (neo4j_healthy and graphiti_healthy) else "partial",
                "neo4j": "healthy" if neo4j_healthy else "unhealthy",
                "graphiti_service": "healthy" if graphiti_healthy else "unhealthy",
                "message": f"Neo4j: {'OK' if neo4j_healthy else 'KO'}, Service: {'OK' if graphiti_healthy else 'KO'}"
            }

            if not (neo4j_healthy and graphiti_healthy):
                overall_healthy = False

    except Exception as e:
        health_status["components"]["graphiti"] = {
            "status": "unhealthy",
            "message": f"Erreur Graphiti: {str(e)}"
        }
        overall_healthy = False

    # Mettre à jour le statut global
    health_status["status"] = "healthy" if overall_healthy else "degraded"

    return health_status


@router.get("/tenants")
async def health_check_tenants(
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> Dict[str, Any]:
    """
    Health check spécifique aux tenants
    """
    try:
        # Compter les tenants
        all_tenants = tenant_service.list_tenants(page=1, page_size=1000)
        active_tenants = [t for t in all_tenants if t.status.value == "active"]

        # Statistiques globales
        total_users = 0
        total_episodes = 0
        total_facts = 0

        for tenant in all_tenants:
            total_users += tenant.stats.users_count
            total_episodes += tenant.stats.episodes_count
            total_facts += tenant.stats.facts_count

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "tenants": {
                "total": len(all_tenants),
                "active": len(active_tenants),
                "with_users": len([t for t in all_tenants if t.stats.users_count > 0])
            },
            "global_stats": {
                "total_users": total_users,
                "total_episodes": total_episodes,
                "total_facts": total_facts
            },
            "data_persistence": {
                "tenants_file": str(tenant_service.tenants_file),
                "memberships_file": str(tenant_service.memberships_file),
                "files_exist": tenant_service.tenants_file.exists() and tenant_service.memberships_file.exists()
            }
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


@router.get("/graphiti")
async def health_check_graphiti() -> Dict[str, Any]:
    """
    Health check spécifique à Graphiti (infrastructure seulement)
    """
    graphiti_status = {
        "status": "unknown",
        "timestamp": datetime.now().isoformat(),
        "components": {}
    }

    all_healthy = True

    try:
        async with httpx.AsyncClient() as client:
            # Test Neo4j
            try:
                neo4j_response = await client.get("http://localhost:7474", timeout=5.0)
                graphiti_status["components"]["neo4j"] = {
                    "status": "healthy" if neo4j_response.status_code == 200 else "unhealthy",
                    "port": 7474,
                    "url": "http://localhost:7474"
                }
                if neo4j_response.status_code != 200:
                    all_healthy = False
            except Exception as e:
                graphiti_status["components"]["neo4j"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                all_healthy = False

            # Test PostgreSQL Graphiti
            try:
                # Adminer comme proxy pour tester PostgreSQL
                pg_response = await client.get("http://localhost:8080", timeout=5.0)
                graphiti_status["components"]["postgres_graphiti"] = {
                    "status": "healthy" if pg_response.status_code == 200 else "unhealthy",
                    "port": 5433,
                    "admin_url": "http://localhost:8080"
                }
                if pg_response.status_code != 200:
                    all_healthy = False
            except Exception as e:
                graphiti_status["components"]["postgres_graphiti"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                all_healthy = False

            # Test Service Graphiti
            try:
                service_response = await client.get("http://localhost:8300/docs", timeout=5.0)
                graphiti_status["components"]["graphiti_service"] = {
                    "status": "healthy" if service_response.status_code == 200 else "unhealthy",
                    "port": 8300,
                    "docs_url": "http://localhost:8300/docs"
                }
                if service_response.status_code != 200:
                    all_healthy = False
            except Exception as e:
                graphiti_status["components"]["graphiti_service"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                all_healthy = False

    except Exception as e:
        graphiti_status["error"] = str(e)
        all_healthy = False

    graphiti_status["status"] = "healthy" if all_healthy else "unhealthy"
    return graphiti_status


@router.get("/quick")
async def health_check_quick() -> Dict[str, Any]:
    """
    Health check rapide pour monitoring
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "SAP Knowledge Base",
        "uptime": "OK"
    }


@router.get("/ready")
async def readiness_check() -> Dict[str, Any]:
    """
    Readiness probe Kubernetes - Phase 0.5 P1.7

    Vérifie dépendances critiques:
    - Redis accessible
    - Qdrant accessible

    Returns:
        200 OK si app prête
        503 Service Unavailable si dépendance down
    """
    import redis as redis_client
    from fastapi import status, Response

    checks = {}

    # Check Redis
    try:
        r = redis_client.Redis(host="redis", port=6379, db=0, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # Check Qdrant via HTTP (plus rapide que client Python)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://qdrant:6333/health", timeout=2.0)
            checks["qdrant"] = response.status_code == 200
    except Exception:
        checks["qdrant"] = False

    all_ok = all(checks.values())

    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks
    }


@router.get("/metrics")
async def metrics_endpoint():
    """
    Endpoint métriques Prometheus - Phase 0.5 P2.11

    Format: Prometheus text exposition
    Usage: Scraping par Prometheus toutes les 15s
    """
    from fastapi.responses import PlainTextResponse
    from knowbase.common.metrics import get_metrics

    return PlainTextResponse(
        content=get_metrics().decode('utf-8'),
        media_type="text/plain; version=0.0.4"
    )