"""
Router FastAPI pour les fonctions d'administration.

Phase 7 - Admin Management
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from knowbase.api.services.purge_service import PurgeService
from knowbase.api.services.audit_service import get_audit_service
from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.db import get_db
from knowbase.db.models import AuditLog
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from sqlalchemy.orm import Session

settings = get_settings()
logger = setup_logging(settings.logs_dir, "admin_router.log")

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_admin_key(x_admin_key: str = Header(...)):
    """
    Vérifie la clé admin pour sécuriser les endpoints sensibles.

    Args:
        x_admin_key: Header X-Admin-Key

    Raises:
        HTTPException: Si clé invalide
    """
    ADMIN_KEY = "admin-dev-key-change-in-production"  # TODO: Déplacer vers .env
    if x_admin_key != ADMIN_KEY:
        logger.warning(f"⚠️ Tentative accès admin avec clé invalide: {x_admin_key[:10]}...")
        raise HTTPException(status_code=401, detail="Invalid admin key")


@router.post("/purge-data", dependencies=[Depends(verify_admin_key)])
async def purge_all_data() -> Dict:
    """
    Purge toutes les données d'ingestion (Qdrant, Neo4j, Redis).

    ATTENTION: Action destructive irréversible !

    Nettoie:
    - Collection Qdrant (tous les points vectoriels)
    - Neo4j (tous les nodes/relations)
    - Redis (queues RQ, jobs terminés)

    Préserve:
    - DocumentType (SQLite)
    - EntityTypeRegistry (SQLite)

    Returns:
        Dict avec résultats de purge par composant

    Requires:
        Header X-Admin-Key pour authentification
    """
    logger.warning("🚨 Requête PURGE SYSTÈME reçue")

    try:
        purge_service = PurgeService()
        results = await purge_service.purge_all_data()

        # Vérifier si toutes les purges ont réussi
        all_success = all(r.get("success", False) for r in results.values())

        return {
            "success": all_success,
            "message": "Purge système terminée" if all_success else "Purge partielle (voir détails)",
            "results": results
        }

    except Exception as e:
        logger.error(f"❌ Erreur lors de la purge système: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur purge: {str(e)}")


@router.get("/health", dependencies=[Depends(verify_admin_key)])
async def admin_health() -> Dict:
    """
    Vérifie l'état de santé des composants système.

    Returns:
        Dict avec statut de chaque composant

    Requires:
        Header X-Admin-Key pour authentification
    """
    health_status = {
        "qdrant": {"status": "unknown", "message": ""},
        "neo4j": {"status": "unknown", "message": ""},
        "redis": {"status": "unknown", "message": ""},
    }

    # Check Qdrant
    try:
        from knowbase.common.clients import get_qdrant_client
        qdrant_client = get_qdrant_client()
        collection_info = qdrant_client.get_collection(settings.qdrant_collection)
        health_status["qdrant"] = {
            "status": "healthy",
            "message": f"{collection_info.points_count} points",
        }
    except Exception as e:
        health_status["qdrant"] = {"status": "unhealthy", "message": str(e)}

    # Check Neo4j
    try:
        import os
        from neo4j import GraphDatabase
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # Compter SEULEMENT les nodes métier (exclure ontologies)
            result = session.run("""
                MATCH (n)
                WHERE NOT n:OntologyEntity AND NOT n:OntologyAlias
                RETURN count(n) as count
            """)
            count = result.single()["count"]
            health_status["neo4j"] = {
                "status": "healthy",
                "message": f"{count} nodes",
            }
        driver.close()
    except Exception as e:
        health_status["neo4j"] = {"status": "unhealthy", "message": str(e)}

    # Check Redis
    try:
        import redis
        redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=0,  # DB par défaut pour RQ
        )
        redis_client.ping()
        keys_count = len(redis_client.keys("rq:*"))
        health_status["redis"] = {
            "status": "healthy",
            "message": f"{keys_count} RQ keys",
        }
    except Exception as e:
        health_status["redis"] = {"status": "unhealthy", "message": str(e)}

    all_healthy = all(c["status"] == "healthy" for c in health_status.values())

    return {
        "success": all_healthy,
        "overall_status": "healthy" if all_healthy else "degraded",
        "components": health_status,
    }


class AuditLogResponse(BaseModel):
    """Response model pour un audit log."""
    id: str
    user_email: str
    action: str
    resource_type: str
    resource_id: Optional[str]
    tenant_id: str
    details: Optional[str]
    timestamp: str

    class Config:
        from_attributes = True


class AuditLogsListResponse(BaseModel):
    """Response model pour liste audit logs."""
    logs: List[AuditLogResponse]
    total: int
    filters: Dict


@router.get(
    "/audit-logs",
    response_model=AuditLogsListResponse,
    summary="Liste logs d'audit (Admin only)",
    description="""
    Récupère les logs d'audit pour traçabilité des actions critiques.

    **Phase 0 - Security Hardening - Audit Trail**

    **Filtres disponibles**:
    - `user_id`: Filtrer par utilisateur spécifique
    - `action`: Filtrer par type d'action (CREATE, UPDATE, DELETE, APPROVE, REJECT)
    - `resource_type`: Filtrer par type de ressource (entity, fact, entity_type, etc.)
    - `limit` / `offset`: Pagination

    **Permissions**: Admin only (require_admin)

    **Use Cases**:
    - Audit trail complet des actions admin
    - Traçabilité qui a fait quoi et quand
    - Sécurité et compliance
    """,
    responses={
        200: {
            "description": "Liste des audit logs",
            "content": {
                "application/json": {
                    "example": {
                        "logs": [
                            {
                                "id": "log-123",
                                "user_email": "admin@example.com",
                                "action": "DELETE",
                                "resource_type": "entity",
                                "resource_id": "ent-456",
                                "tenant_id": "tenant-1",
                                "details": "Entity deleted with cascade",
                                "timestamp": "2025-10-09T10:30:00Z"
                            }
                        ],
                        "total": 1,
                        "filters": {"action": "DELETE"}
                    }
                }
            }
        },
        403: {
            "description": "Accès refusé (admin uniquement)"
        }
    }
)
async def list_audit_logs(
    current_user: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_db),
    user_id: Optional[str] = Query(None, description="Filtrer par user_id"),
    action: Optional[str] = Query(None, description="Filtrer par action"),
    resource_type: Optional[str] = Query(None, description="Filtrer par resource_type"),
    limit: int = Query(100, ge=1, le=1000, description="Limite résultats"),
    offset: int = Query(0, ge=0, description="Offset pagination")
):
    """
    Liste les audit logs avec filtres.

    Args:
        current_user: Admin user (authenticated via require_admin)
        tenant_id: Tenant ID (from JWT)
        db: Database session
        user_id: Filtrer par utilisateur
        action: Filtrer par action
        resource_type: Filtrer par type ressource
        limit: Limite résultats
        offset: Offset pagination

    Returns:
        Liste logs d'audit avec total et filtres appliqués
    """
    logger.info(
        f"📋 GET /admin/audit-logs - admin={current_user.get('email')}, "
        f"filters: user_id={user_id}, action={action}, resource_type={resource_type}"
    )

    audit_service = get_audit_service(db)

    logs = audit_service.get_audit_logs(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        limit=limit,
        offset=offset
    )

    # Compter total (sans limit/offset)
    from knowbase.db.models import AuditLog
    query = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    total = query.count()

    return AuditLogsListResponse(
        logs=[
            AuditLogResponse(
                id=log.id,
                user_email=log.user_email,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                tenant_id=log.tenant_id,
                details=log.details,
                timestamp=log.timestamp.isoformat()
            )
            for log in logs
        ],
        total=total,
        filters={
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type
        }
    )


__all__ = ["router"]
