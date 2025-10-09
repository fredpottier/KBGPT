"""
Router FastAPI pour les fonctions d'administration.

Phase 7 - Admin Management
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Dict

from knowbase.api.services.purge_service import PurgeService
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

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


__all__ = ["router"]
