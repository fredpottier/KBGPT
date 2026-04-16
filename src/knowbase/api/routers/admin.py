"""
Router FastAPI pour les fonctions d'administration.

Phase 7 - Admin Management
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from knowbase.api.services.purge_service import PurgeService
from knowbase.api.services.audit_service import get_audit_service
from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.db import get_db
from knowbase.db.models import AuditLog, SystemSetting
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from sqlalchemy.orm import Session

settings = get_settings()
logger = setup_logging(settings.logs_dir, "admin_router.log")

router = APIRouter(prefix="/admin", tags=["admin"])


class PurgeDataRequest(BaseModel):
    """Requête pour purger les données."""
    purge_schema: bool = Field(
        default=False,
        description="Si True, purge aussi le schéma Neo4j (constraints/indexes)"
    )
    recreate_schema: bool = Field(
        default=False,
        description="Si True, recrée le schéma Neo4j après la purge (MVP V1 + Pipeline V2)"
    )


@router.post("/purge-data")
async def purge_all_data(
    request: PurgeDataRequest = None,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict:
    """
    Purge toutes les données d'ingestion (Qdrant, Neo4j, Redis).

    ATTENTION: Action destructive irréversible !

    **Sécurité**: Requiert authentification JWT avec rôle 'admin'.

    **Nettoie:**
    - Collection Qdrant (tous les points vectoriels)
    - Neo4j (tous les nodes/relations sauf OntologyEntity, OntologyAlias, DomainContextProfile)
    - Neo4j schema (constraints/indexes) si `purge_schema=True`
    - Redis (queues RQ, jobs terminés)
    - PostgreSQL (sessions, messages de conversation)
    - Fichiers (docs_in, docs_done, status)

    **Préserve:**
    - DocumentType, EntityTypeRegistry (PostgreSQL/SQLite)
    - OntologyEntity, OntologyAlias, DomainContextProfile (Neo4j)
    - Cache d'extraction (data/extraction_cache/) ⚠️ CRITIQUE

    **Args:**
    - `purge_schema`: Si True, supprime aussi les constraints/indexes Neo4j
                     (utile après changements de schéma pour éviter les "ghost" labels/relations)
    - `recreate_schema`: Si True, recrée le schéma Neo4j après purge (MVP V1 + Pipeline V2)

    Returns:
        Dict avec résultats de purge par composant
    """
    # Permettre appel sans body (compatibilité avec anciennes versions)
    purge_schema = request.purge_schema if request else False
    recreate_schema = request.recreate_schema if request else False

    schema_msg = " + SCHÉMA" if purge_schema else ""
    recreate_msg = " + RECRÉATION" if recreate_schema else ""
    logger.warning(f"🚨 Requête PURGE SYSTÈME reçue{schema_msg}{recreate_msg}")

    try:
        purge_service = PurgeService()
        results = await purge_service.purge_all_data(
            purge_schema=purge_schema,
            recreate_schema=recreate_schema
        )

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


@router.get("/health")
async def admin_health(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict:
    """
    Vérifie l'état de santé des composants système.

    **Sécurité**: Requiert authentification JWT avec rôle 'admin'.

    Returns:
        Dict avec statut de chaque composant (Qdrant, Neo4j, Redis, PostgreSQL)
    """
    health_status = {
        "qdrant": {"status": "unknown", "message": ""},
        "neo4j": {"status": "unknown", "message": ""},
        "redis": {"status": "unknown", "message": ""},
        "postgres": {"status": "unknown", "message": ""},
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

    # Check PostgreSQL
    try:
        from knowbase.db import get_db
        from knowbase.db.models import Session, SessionMessage, User
        from knowbase.db.base import is_sqlite

        db = next(get_db())
        try:
            # Compter sessions et messages
            sessions_count = db.query(Session).count()
            messages_count = db.query(SessionMessage).count()
            users_count = db.query(User).count()

            db_type = "SQLite" if is_sqlite else "PostgreSQL"
            health_status["postgres"] = {
                "status": "healthy",
                "message": f"{db_type}: {users_count} users, {sessions_count} sessions, {messages_count} messages",
            }
        finally:
            db.close()
    except Exception as e:
        health_status["postgres"] = {"status": "unhealthy", "message": str(e)}

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


@router.post("/deduplicate-entities")
async def deduplicate_entities(
    dry_run: bool = Query(False, description="Si true, simule seulement (ne modifie pas)"),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> Dict:
    """
    Dé-duplique globalement toutes les entités ayant le même nom (case-insensitive).

    Cette opération:
    1. Trouve tous les groupes d'entités avec des noms identiques
    2. Pour chaque groupe, garde l'entité avec le plus de relations (entité "maître")
    3. Réassigne toutes les relations vers l'entité maître
    4. Supprime les entités dupliquées qui n'ont plus de relations

    Args:
        dry_run: Si True, simule seulement et retourne ce qui serait fait

    Returns:
        Statistiques de dé-duplication:
        {
            "duplicate_groups": int,
            "entities_to_merge": int,
            "entities_kept": int,
            "relations_updated": int,
            "groups": [...] (si dry_run=True)
        }
    """
    try:
        logger.info(f"🔍 Dé-duplication des entités demandée (dry_run={dry_run}, tenant={tenant_id})")

        # Créer le service Knowledge Graph
        kg_service = KnowledgeGraphService(tenant_id=tenant_id)

        # Lancer la dé-duplication
        stats = kg_service.deduplicate_entities_by_name(
            tenant_id=tenant_id,
            dry_run=dry_run
        )

        logger.info(
            f"✅ Dé-duplication {'simulée' if dry_run else 'terminée'}: "
            f"{stats['duplicate_groups']} groupes, "
            f"{stats['entities_to_merge']} entités à fusionner"
        )

        return {
            "success": True,
            "dry_run": dry_run,
            "stats": stats,
            "message": (
                f"Simulation: {stats['duplicate_groups']} groupes de doublons détectés, "
                f"{stats['entities_to_merge']} entités à fusionner"
                if dry_run else
                f"Dé-duplication terminée: {stats['entities_to_merge']} entités fusionnées, "
                f"{stats['relations_updated']} relations réassignées"
            )
        }

    except Exception as e:
        logger.error(f"❌ Erreur dé-duplication: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur dé-duplication: {str(e)}")


# ============================================================================
# GPU / Embedding Model Management (Development)
# ============================================================================

class GPUStatusResponse(BaseModel):
    """Réponse statut GPU/Embedding."""
    model_loaded: bool
    model_name: Optional[str] = None
    device: Optional[str] = None
    idle_seconds: Optional[int] = None
    timeout_seconds: int
    gpu_available: bool = False
    gpu_memory_allocated_gb: Optional[float] = None
    gpu_memory_reserved_gb: Optional[float] = None


@router.get(
    "/gpu/status",
    response_model=GPUStatusResponse,
    summary="Statut modèle embedding GPU",
    description="Retourne le statut du modèle d'embedding et la mémoire GPU utilisée."
)
async def get_gpu_status():
    """
    Récupère le statut du modèle d'embedding et de la mémoire GPU.

    Returns:
        Statut du modèle et mémoire GPU
    """
    from knowbase.common.clients.embeddings import get_embedding_status

    status = get_embedding_status()

    # Ajouter info GPU si disponible
    gpu_available = False
    gpu_memory_allocated = None
    gpu_memory_reserved = None

    try:
        import torch
        if torch.cuda.is_available():
            gpu_available = True
            gpu_memory_allocated = round(torch.cuda.memory_allocated() / 1024**3, 2)
            gpu_memory_reserved = round(torch.cuda.memory_reserved() / 1024**3, 2)
    except ImportError:
        pass

    return GPUStatusResponse(
        model_loaded=status["model_loaded"],
        model_name=status["model_name"],
        device=status["device"],
        idle_seconds=status["idle_seconds"],
        timeout_seconds=status["timeout_seconds"],
        gpu_available=gpu_available,
        gpu_memory_allocated_gb=gpu_memory_allocated,
        gpu_memory_reserved_gb=gpu_memory_reserved
    )


# ============================================================================
# Visibility Profiles (Phase 2.12 - Agnostic KG Architecture)
# ============================================================================

class VisibilityProfileSummary(BaseModel):
    """Résumé d'un profil de visibilité."""
    id: str
    icon: str
    name: str
    short_description: str
    explanation: str
    is_current: bool = False


class VisibilityProfilesResponse(BaseModel):
    """Réponse liste des profils."""
    current_profile: str
    profiles: List[VisibilityProfileSummary]


class SetProfileRequest(BaseModel):
    """Requête pour changer de profil."""
    profile_id: str = Field(..., description="ID du profil (verified, balanced, exploratory, full_access)")


@router.get(
    "/visibility-profiles",
    response_model=VisibilityProfilesResponse,
    summary="Liste des profils de visibilité",
    description="""
    Récupère la liste des profils de visibilité disponibles.

    **Profils disponibles:**
    - `verified`: Uniquement les faits confirmés (2+ sources)
    - `balanced`: Équilibre qualité/quantité (défaut)
    - `exploratory`: Maximum de connexions
    - `full_access`: Accès admin complet

    Voir: doc/ongoing/KG_AGNOSTIC_ARCHITECTURE.md
    """
)
async def list_visibility_profiles(
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste tous les profils de visibilité avec le profil actuel du tenant."""
    try:
        from knowbase.api.services.visibility_service import get_visibility_service

        service = get_visibility_service(tenant_id=tenant_id)
        current_profile_id = service.get_profile_for_tenant(tenant_id)
        profiles = service.list_profiles(current_profile_id)

        return VisibilityProfilesResponse(
            current_profile=current_profile_id,
            profiles=[
                VisibilityProfileSummary(
                    id=p.id,
                    icon=p.icon,
                    name=p.name,
                    short_description=p.short_description,
                    explanation=p.explanation,
                    is_current=p.is_current
                )
                for p in profiles
            ]
        )
    except Exception as e:
        logger.error(f"Erreur liste profils visibilité: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/visibility-profiles/current",
    summary="Changer le profil de visibilité",
    description="""
    Change le profil de visibilité pour le tenant.

    **Note**: Ce changement affecte tous les utilisateurs du tenant.
    Le changement est immédiat pour les nouvelles requêtes.
    """
)
async def set_visibility_profile(
    request: SetProfileRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Change le profil de visibilité du tenant."""
    try:
        from knowbase.api.services.visibility_service import get_visibility_service

        service = get_visibility_service(tenant_id=tenant_id)

        # Vérifier que le profil existe
        if request.profile_id not in ["verified", "balanced", "exploratory", "full_access"]:
            raise HTTPException(
                status_code=400,
                detail=f"Profil invalide: {request.profile_id}. "
                       f"Valeurs acceptées: verified, balanced, exploratory, full_access"
            )

        # Changer le profil (in-memory pour l'instant)
        success = service.set_tenant_profile(tenant_id, request.profile_id)

        if not success:
            raise HTTPException(status_code=400, detail="Échec du changement de profil")

        logger.info(f"Profil visibilité changé: tenant={tenant_id}, profil={request.profile_id}")

        return {
            "success": True,
            "tenant_id": tenant_id,
            "new_profile": request.profile_id,
            "message": f"Profil changé en '{request.profile_id}'"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur changement profil visibilité: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/visibility-profiles/{profile_id}",
    summary="Détail d'un profil de visibilité",
    description="Récupère les détails complets d'un profil spécifique."
)
async def get_visibility_profile_detail(
    profile_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère les détails d'un profil de visibilité."""
    try:
        from knowbase.api.services.visibility_service import get_visibility_service

        service = get_visibility_service(tenant_id=tenant_id)
        profile = service.get_profile(profile_id)

        if not profile:
            raise HTTPException(status_code=404, detail=f"Profil non trouvé: {profile_id}")

        return {
            "id": profile.id,
            "icon": profile.icon,
            "name": profile.name,
            "short_description": profile.short_description,
            "explanation": profile.explanation,
            "settings": {
                "min_maturity": profile.settings.min_maturity,
                "min_confidence": profile.settings.min_confidence,
                "min_source_count": profile.settings.min_source_count,
                "allowed_maturities": profile.settings.allowed_maturities,
                "show_conflicts": profile.settings.show_conflicts,
                "show_context_dependent": profile.settings.show_context_dependent,
                "show_ambiguous": profile.settings.show_ambiguous,
            },
            "ui": {
                "show_maturity_badge": profile.ui.show_maturity_badge,
                "show_confidence": profile.ui.show_confidence,
                "mandatory_disclaimer": profile.ui.mandatory_disclaimer,
                "disclaimer_text": profile.ui.disclaimer_text,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur détail profil visibilité: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Pass 2 Enrichment (Hybrid Anchor Model)
# ============================================================================

class Pass2StatusResponse(BaseModel):
    """Statut Pass 2."""
    proto_concepts: int = 0
    canonical_concepts: int = 0
    raw_assertions: int = 0
    raw_claims: int = 0
    canonical_relations: int = 0
    canonical_claims: int = 0
    # Entity Resolution stats
    er_standalone_concepts: int = 0
    er_merged_concepts: int = 0
    er_pending_proposals: int = 0
    # Jobs
    pending_jobs: int = 0
    running_jobs: int = 0


class Pass2PhaseRequest(BaseModel):
    """Requête pour exécuter une phase Pass 2."""
    document_id: Optional[str] = Field(None, description="Filtrer par document")
    limit: int = Field(100, description="Nombre max d'items")


class Pass2ResultResponse(BaseModel):
    """Résultat d'une phase Pass 2."""
    success: bool
    phase: str
    items_processed: int
    items_created: int
    items_updated: int
    execution_time_ms: float
    errors: List[str] = []
    details: Dict[str, Any] = {}


@router.get(
    "/pass2/status",
    response_model=Pass2StatusResponse,
    summary="Statut Pass 2",
    description="""
    Récupère le statut du système Pass 2 (Hybrid Anchor Model).

    Affiche:
    - Nombre de ProtoConcepts / CanonicalConcepts
    - Nombre de RawAssertions / RawClaims
    - Nombre de CanonicalRelations / CanonicalClaims
    - Jobs Pass 2 en attente et en cours
    """
)
async def get_pass2_status(
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère le statut du système Pass 2."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    status = service.get_status()

    return Pass2StatusResponse(
        proto_concepts=status.proto_concepts,
        canonical_concepts=status.canonical_concepts,
        raw_assertions=status.raw_assertions,
        raw_claims=status.raw_claims,
        canonical_relations=status.canonical_relations,
        canonical_claims=status.canonical_claims,
        er_standalone_concepts=status.er_standalone_concepts,
        er_merged_concepts=status.er_merged_concepts,
        er_pending_proposals=status.er_pending_proposals,
        pending_jobs=status.pending_jobs,
        running_jobs=status.running_jobs
    )


@router.post(
    "/pass2/classify-fine",
    response_model=Pass2ResultResponse,
    summary="Exécuter CLASSIFY_FINE",
    description="""
    Exécute la phase CLASSIFY_FINE de Pass 2.

    Cette phase affine les types heuristiques des concepts avec
    une classification LLM fine-grained.
    """
)
async def run_classify_fine(
    request: Pass2PhaseRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute CLASSIFY_FINE."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = await service.run_classify_fine(
        document_id=request.document_id,
        limit=request.limit
    )

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


@router.post(
    "/pass2/enrich-relations",
    response_model=Pass2ResultResponse,
    summary="Exécuter ENRICH_RELATIONS",
    description="""
    Exécute la phase ENRICH_RELATIONS de Pass 2.

    Cette phase:
    1. Détecte les relations cross-segment via LLM
    2. Persiste les relations en RawAssertions dans Neo4j
    3. Prépare pour la consolidation
    """
)
async def run_enrich_relations(
    request: Pass2PhaseRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute ENRICH_RELATIONS avec persistence."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = await service.run_enrich_relations(
        document_id=request.document_id,
        max_relations_per_doc=request.limit or 150
    )

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


@router.post(
    "/pass2/consolidate-claims",
    response_model=Pass2ResultResponse,
    summary="Consolider les Claims",
    description="""
    Consolide les RawClaims en CanonicalClaims.

    Utilise le code existant de consolidation:
    - Groupement par (subject, claim_type, scope_key)
    - Calcul de maturité (VALIDATED, CANDIDATE, CONFLICTING, etc.)
    - Détection des conflits et supersessions
    """
)
async def run_consolidate_claims(
    request: Pass2PhaseRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Consolide Claims."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = service.run_consolidate_claims()

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


@router.post(
    "/pass2/consolidate-relations",
    response_model=Pass2ResultResponse,
    summary="Consolider les Relations",
    description="""
    Consolide les RawAssertions en CanonicalRelations.

    Utilise le code existant de consolidation:
    - Groupement par (subject, object, predicate_norm)
    - Calcul de maturité (VALIDATED, CANDIDATE, AMBIGUOUS_TYPE)
    - Création des typed edges dans Neo4j
    """
)
async def run_consolidate_relations(
    request: Pass2PhaseRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Consolide Relations."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = service.run_consolidate_relations()

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


class Pass2CorpusERRequest(BaseModel):
    """Requête pour exécuter CORPUS_ER."""
    dry_run: bool = Field(False, description="Si True, preview sans exécuter les merges")
    limit: Optional[int] = Field(None, description="Limite de concepts à analyser (pour tests)")


@router.post(
    "/pass2/corpus-er",
    response_model=Pass2ResultResponse,
    summary="Exécuter CORPUS_ER (Entity Resolution)",
    description="""
    Exécute la phase CORPUS_ER de Pass 2.

    Cette phase fusionne les CanonicalConcepts dupliqués à travers le corpus.

    **Spec**: PATCH-ER-04/05/06 (ChatGPT calibration)
    - TopK + Mutual Best pruning
    - Decision v2 (AUTO/PROPOSE/REJECT)
    - Hard budget proposals cap (1000 max)

    **Distribution cible**: ~80% AUTO / ~15% PROPOSE / ~5% REJECT
    """
)
async def run_corpus_er(
    request: Pass2CorpusERRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute Entity Resolution corpus-level."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = service.run_corpus_er(
        dry_run=request.dry_run,
        limit=request.limit
    )

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


# =============================================================================
# Pass 4b: Corpus Links (PATCH-LINK) - ADR 2026-01-07
# =============================================================================

@router.post(
    "/pass4/corpus-links",
    response_model=Pass2ResultResponse,
    summary="Exécuter CORPUS_LINKS (liens faibles cross-doc)",
    description="""
    Exécute la phase Pass 4b: Corpus Links.

    Crée des relations CO_OCCURS_IN_CORPUS entre concepts qui apparaissent
    ensemble dans ≥2 documents différents.

    **ADR 2026-01-07**: Nomenclature validée Claude + ChatGPT
    - Phase corpus-level (travaille sur le corpus entier)
    - Déterministe, SANS LLM
    - Liens faibles = indices pour navigation, pas relations sémantiques

    **Note**: Exécuter APRÈS Entity Resolution (Pass 4a) pour un graphe stable.
    """
)
async def run_corpus_links(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute création des liens faibles cross-documents."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = await service.run_corpus_links()

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


class Pass2FullRequest(BaseModel):
    """Requête pour exécuter Pass 2 complet."""
    document_id: Optional[str] = Field(None, description="Filtrer par document")
    skip_classify: bool = Field(False, description="Ignorer CLASSIFY_FINE")
    skip_enrich: bool = Field(False, description="Ignorer ENRICH_RELATIONS")
    skip_consolidate: bool = Field(False, description="Ignorer consolidation")
    skip_corpus_er: bool = Field(False, description="Ignorer CORPUS_ER (Entity Resolution)")


@router.post(
    "/pass2/run-full",
    summary="Exécuter Pass 2 complet",
    description="""
    Exécute toutes les phases de Pass 2 dans l'ordre:

    1. **CLASSIFY_FINE**: Classification LLM fine-grained
    2. **ENRICH_RELATIONS**: Détection relations cross-segment + persistence
    3. **CONSOLIDATE_CLAIMS**: RawClaims → CanonicalClaims
    4. **CONSOLIDATE_RELATIONS**: RawAssertions → CanonicalRelations
    5. **CORPUS_ER**: Entity Resolution corpus-level

    Chaque phase peut être désactivée individuellement.
    """
)
async def run_full_pass2(
    request: Pass2FullRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute Pass 2 complet."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    results = await service.run_full_pass2(
        document_id=request.document_id,
        skip_classify=request.skip_classify,
        skip_enrich=request.skip_enrich,
        skip_consolidate=request.skip_consolidate,
        skip_corpus_er=request.skip_corpus_er
    )

    return {
        "success": all(r.success for r in results.values()),
        "phases": {
            phase: {
                "success": r.success,
                "items_processed": r.items_processed,
                "items_created": r.items_created,
                "execution_time_ms": r.execution_time_ms,
                "errors": r.errors
            }
            for phase, r in results.items()
        }
    }


@router.post(
    "/gpu/unload",
    summary="Décharger modèle embedding GPU",
    description="Force le déchargement du modèle d'embedding pour libérer la mémoire GPU."
)
async def unload_gpu_model():
    """
    Force le déchargement du modèle d'embedding et libère la mémoire GPU.

    Utile en développement pour libérer la RAM GPU quand le modèle n'est plus utilisé.

    Returns:
        Confirmation du déchargement
    """
    from knowbase.common.clients.embeddings import unload_embedding_model, get_embedding_status

    # Récupérer statut avant
    status_before = get_embedding_status()

    if not status_before["model_loaded"]:
        return {
            "success": True,
            "message": "Aucun modèle chargé",
            "model_was_loaded": False
        }

    # Décharger
    unload_embedding_model()

    # Vérifier mémoire GPU après
    gpu_memory_after = None
    try:
        import torch
        if torch.cuda.is_available():
            gpu_memory_after = round(torch.cuda.memory_allocated() / 1024**3, 2)
    except ImportError:
        pass

    logger.info(f"🔌 Modèle embedding déchargé manuellement: {status_before['model_name']}")

    return {
        "success": True,
        "message": f"Modèle {status_before['model_name']} déchargé",
        "model_was_loaded": True,
        "gpu_memory_allocated_gb_after": gpu_memory_after
    }


# =============================================================================
# GOVERNANCE LAYERS (ADR 2026-01-07)
# Post-consolidation quality scoring and metrics
# =============================================================================

class GovernanceScoringResponse(BaseModel):
    """Réponse du scoring de gouvernance."""
    success: bool
    relations_scored: int
    tier_distribution: Dict[str, int]
    high_confidence_ratio: float
    avg_evidence_count: float
    processing_time_ms: float


@router.post(
    "/governance/quality/score",
    response_model=GovernanceScoringResponse,
    summary="Exécuter le scoring Quality Layer",
    description="""
    Calcule et persiste les scores de qualité sur toutes les relations du KG.

    **ADR Graph Governance Layers - Phase A**

    Ajoute les propriétés suivantes aux relations:
    - `evidence_count`: Nombre de preuves (taille de evidence_context_ids)
    - `evidence_strength`: Score normalisé 0-1 (log-scale)
    - `confidence_tier`: HIGH (≥5) / MEDIUM (2-4) / LOW (1) / WEAK (0)

    **IMPORTANT**: Ces scores sont des indicateurs de SUPPORT, pas de VERITE.
    Une relation LOW n'est pas "fausse", elle a simplement moins de preuves.

    Idempotent - peut être exécuté plusieurs fois sans effet secondaire.
    """
)
async def run_governance_scoring(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute le scoring de gouvernance qualité."""
    from knowbase.api.services.governance_quality_service import get_governance_quality_service

    service = get_governance_quality_service(tenant_id)
    stats = await service.score_all_relations()

    return GovernanceScoringResponse(
        success=True,
        relations_scored=stats.relations_scored,
        tier_distribution={
            "HIGH": stats.high_tier_count,
            "MEDIUM": stats.medium_tier_count,
            "LOW": stats.low_tier_count,
            "WEAK": stats.weak_tier_count,
        },
        high_confidence_ratio=round(
            stats.high_tier_count / stats.relations_scored * 100, 1
        ) if stats.relations_scored > 0 else 0,
        avg_evidence_count=round(stats.avg_evidence_count, 2),
        processing_time_ms=round(stats.processing_time_ms, 1)
    )


class GovernanceMetricsResponse(BaseModel):
    """Réponse des métriques de gouvernance."""
    total_relations: int
    tier_distribution: Dict[str, int]
    unscored_relations: int
    co_occurs_count: int
    high_confidence_ratio: float
    avg_evidence_count: float


@router.get(
    "/governance/quality/metrics",
    response_model=GovernanceMetricsResponse,
    summary="Obtenir les métriques de gouvernance qualité",
    description="""
    Retourne les métriques actuelles de gouvernance du Knowledge Graph.

    Inclut:
    - Distribution par tier de confiance (HIGH/MEDIUM/LOW/WEAK)
    - Nombre de relations non encore scorées
    - Ratio de relations à haute confiance
    - Moyenne du nombre de preuves par relation
    """
)
async def get_governance_metrics(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère les métriques de gouvernance."""
    from knowbase.api.services.governance_quality_service import get_governance_quality_service

    service = get_governance_quality_service(tenant_id)
    metrics = await service.get_governance_metrics()

    return GovernanceMetricsResponse(
        total_relations=metrics.total_relations,
        tier_distribution={
            "HIGH": metrics.high_tier,
            "MEDIUM": metrics.medium_tier,
            "LOW": metrics.low_tier,
            "WEAK": metrics.weak_tier,
        },
        unscored_relations=metrics.unscored_relations,
        co_occurs_count=metrics.co_occurs_count,
        high_confidence_ratio=round(metrics.high_confidence_ratio * 100, 1),
        avg_evidence_count=round(metrics.avg_evidence_count, 2)
    )


@router.get(
    "/governance/quality/relations/{tier}",
    summary="Lister les relations par tier de confiance",
    description="""
    Retourne les relations d'un tier de confiance spécifique.

    Utile pour explorer et valider les relations par niveau de support probatoire.

    **Tiers disponibles**: HIGH, MEDIUM, LOW, WEAK
    """
)
async def get_relations_by_tier(
    tier: str,
    limit: int = Query(default=50, ge=1, le=200),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère les relations d'un tier spécifique."""
    from knowbase.api.services.governance_quality_service import (
        get_governance_quality_service,
        ConfidenceTier
    )

    # Valider le tier
    tier_upper = tier.upper()
    try:
        confidence_tier = ConfidenceTier(tier_upper)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tier invalide: {tier}. Valeurs acceptées: HIGH, MEDIUM, LOW, WEAK"
        )

    service = get_governance_quality_service(tenant_id)
    relations = await service.get_relations_by_tier(confidence_tier, limit)

    return {
        "tier": tier_upper,
        "count": len(relations),
        "relations": relations
    }


# --- BUDGET LAYER ---

@router.get(
    "/governance/budget/presets",
    summary="Obtenir les presets de budget disponibles",
    description="""
    Retourne les configurations de budget prédéfinies.

    **ADR Graph Governance Layers - Phase B**

    Presets disponibles:
    - **STRICT**: HIGH only, max 50 nœuds (rapide, haute confiance)
    - **STANDARD**: MEDIUM+, max 100 nœuds (défaut recommandé)
    - **EXPLORATORY**: LOW+, max 200 nœuds (exploration large)
    - **UNLIMITED**: Pas de limite (attention à la performance!)

    **IMPORTANT**: Ces budgets contrôlent uniquement la TRAVERSÉE.
    Ils ne modifient jamais l'état persistant du graphe.
    """
)
async def get_budget_presets(
    admin: dict = Depends(require_admin),
):
    """Retourne les presets de budget disponibles."""
    from knowbase.api.services.governance_budget_service import BUDGET_PRESETS

    return {
        "presets": BUDGET_PRESETS,
        "default": "standard",
        "note": "Ces budgets sont query-time only - ils ne modifient pas le graphe"
    }


class BudgetTestRequest(BaseModel):
    """Requête pour tester une traversée budgétée."""
    concept_id: str = Field(..., description="ID du concept de départ")
    preset: str = Field(default="standard", description="Preset: strict/standard/exploratory/unlimited")
    custom_max_hops: Optional[int] = Field(None, ge=1, le=5)
    custom_min_tier: Optional[str] = Field(None, description="HIGH/MEDIUM/LOW/WEAK")
    custom_max_nodes: Optional[int] = Field(None, ge=10, le=500)


@router.post(
    "/governance/budget/test",
    summary="Tester une traversée budgétée",
    description="""
    Teste une traversée de graphe avec un budget donné.

    Utile pour:
    - Vérifier que les budgets fonctionnent correctement
    - Explorer le graphe avec différents niveaux de confiance
    - Estimer la densité du graphe autour d'un concept

    **IMPORTANT**: Cette requête est READ-ONLY.
    Elle ne modifie rien dans le graphe.
    """
)
async def test_budget_traversal(
    request: BudgetTestRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Teste une traversée budgétée."""
    from knowbase.api.services.governance_budget_service import (
        get_governance_budget_service,
        QueryBudget,
        BudgetPreset
    )
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.config.settings import get_settings

    settings = get_settings()
    service = get_governance_budget_service(tenant_id)

    # Créer le budget depuis le preset ou custom
    try:
        preset = BudgetPreset(request.preset.lower())
        budget = QueryBudget.from_preset(preset)
    except ValueError:
        budget = QueryBudget()  # Standard par défaut

    # Appliquer les overrides custom
    if request.custom_max_hops:
        budget.max_hops = request.custom_max_hops
    if request.custom_min_tier:
        budget.min_confidence_tier = request.custom_min_tier.upper()
    if request.custom_max_nodes:
        budget.max_total_nodes = request.custom_max_nodes

    # Construire et exécuter la requête
    query, params = service.build_simple_budgeted_query(
        start_concept_id=request.concept_id,
        budget=budget
    )

    # Exécuter
    neo4j = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password
    )

    results = []
    try:
        with neo4j.driver.session(database=getattr(neo4j, 'database', 'neo4j')) as session:
            result = session.run(query, params)
            results = [dict(record) for record in result]
    except Exception as e:
        logger.error(f"[Governance:Budget] Query error: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur de requête: {str(e)}")

    budget_stats = service.get_budget_stats(budget)

    return {
        "concept_id": request.concept_id,
        "budget_applied": budget.to_dict(),
        "budget_stats": budget_stats,
        "results_count": len(results),
        "budget_exceeded": len(results) >= budget.max_total_nodes,
        "results": results[:50],  # Limiter la réponse API
        "note": "Query-time only - aucune modification du graphe"
    }


# --- CONFLICT LAYER ---

@router.post(
    "/governance/conflict/detect",
    summary="Détecter les tensions sémantiques",
    description="""
    Lance la détection des tensions (contradictions) dans le Knowledge Graph.

    **ADR Graph Governance Layers - Phase C**

    Cherche les paires de concepts ayant des relations contradictoires:
    - REPLACES vs COMPLEMENTS
    - ENABLES vs BLOCKS
    - DEPENDS_ON vs INDEPENDENT_OF

    **IMPORTANT**: OSMOSE ne tranche JAMAIS les contradictions.
    Il les expose à l'utilisateur avec contexte pour décision humaine.

    Les tensions détectées sont créées comme nœuds séparés (Tension)
    et ne modifient pas les relations existantes.
    """
)
async def detect_tensions(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Détecte les tensions sémantiques."""
    from knowbase.api.services.governance_conflict_service import get_governance_conflict_service

    service = get_governance_conflict_service(tenant_id)
    stats = await service.detect_semantic_tensions()

    return {
        "success": True,
        "stats": stats.to_dict(),
        "note": "Les tensions ne sont pas des erreurs - elles exposent des incohérences à investiguer"
    }


@router.get(
    "/governance/conflict/tensions",
    summary="Lister les tensions détectées",
    description="""
    Retourne les tensions détectées avec filtres optionnels.

    **Statuts**:
    - UNRESOLVED: Détectée, non traitée
    - ACKNOWLEDGED: Vue par un humain
    - EXPLAINED: Explication fournie (note: pas "résolue"!)

    **Types (par sévérité)**:
    - HARD: Contradictions impossibles (ENABLES vs PREVENTS)
    - SUSPECT: Combinaisons inhabituelles (erreurs LLM probables)
    - BIDIRECTIONAL: Relations asymétriques dans les deux sens

    **Types (legacy)**:
    - SEMANTIC, TEMPORAL, SCOPE, SOURCE
    """
)
async def get_tensions(
    status: Optional[str] = Query(None, description="UNRESOLVED/ACKNOWLEDGED/EXPLAINED"),
    tension_type: Optional[str] = Query(None, description="HARD/SUSPECT/BIDIRECTIONAL/SEMANTIC/TEMPORAL"),
    limit: int = Query(default=50, ge=1, le=200),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère les tensions."""
    from knowbase.api.services.governance_conflict_service import (
        get_governance_conflict_service,
        TensionStatus,
        TensionType
    )

    service = get_governance_conflict_service(tenant_id)

    # Parser les filtres
    filter_status = None
    filter_type = None

    if status:
        try:
            filter_status = TensionStatus(status.upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Statut invalide: {status}. Valeurs: UNRESOLVED/ACKNOWLEDGED/EXPLAINED"
            )

    if tension_type:
        try:
            filter_type = TensionType(tension_type.upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Type invalide: {tension_type}. Valeurs: SEMANTIC/TEMPORAL/SCOPE/SOURCE"
            )

    tensions = await service.get_tensions(
        status=filter_status,
        tension_type=filter_type,
        limit=limit
    )

    return {
        "count": len(tensions),
        "tensions": [t.to_dict() for t in tensions]
    }


@router.get(
    "/governance/conflict/counts",
    summary="Obtenir les comptages de tensions",
    description="Retourne le nombre de tensions par statut."
)
async def get_tension_counts(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère les comptages de tensions."""
    from knowbase.api.services.governance_conflict_service import get_governance_conflict_service

    service = get_governance_conflict_service(tenant_id)
    counts = await service.get_tension_counts()

    return counts


class TensionUpdateRequest(BaseModel):
    """Requête pour mettre à jour une tension."""
    status: str = Field(..., description="UNRESOLVED/ACKNOWLEDGED/EXPLAINED")
    resolution_note: Optional[str] = Field(None, description="Note explicative")


@router.patch(
    "/governance/conflict/tensions/{tension_id}",
    summary="Mettre à jour le statut d'une tension",
    description="""
    Met à jour le statut d'une tension.

    **IMPORTANT**: EXPLAINED n'implique pas que la tension est "résolue" globalement.
    Cela signifie qu'un humain a fourni une explication contextuelle,
    mais les deux assertions sources restent intactes dans le graphe.

    Exemple de resolution_note:
    "Les deux informations sont correctes mais dans des contextes différents:
    - SAP S/4HANA remplace ECC pour les nouvelles implémentations
    - SAP ECC reste en maintenance pour les clients existants jusqu'en 2027"
    """
)
async def update_tension(
    tension_id: str,
    request: TensionUpdateRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Met à jour une tension."""
    from knowbase.api.services.governance_conflict_service import (
        get_governance_conflict_service,
        TensionStatus
    )

    # Valider le statut
    try:
        new_status = TensionStatus(request.status.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Statut invalide: {request.status}"
        )

    service = get_governance_conflict_service(tenant_id)
    success = await service.update_tension_status(
        tension_id=tension_id,
        new_status=new_status,
        resolution_note=request.resolution_note,
        resolved_by=admin.get("email", "admin")
    )

    if not success:
        raise HTTPException(status_code=404, detail=f"Tension {tension_id} non trouvée")

    return {
        "success": True,
        "tension_id": tension_id,
        "new_status": new_status.value,
        "note": "Les assertions sources restent intactes dans le graphe"
    }


@router.delete(
    "/governance/conflict/tensions/{tension_id}",
    summary="Supprimer une tension",
    description="Supprime une tension (si détection erronée / faux positif)."
)
async def delete_tension(
    tension_id: str,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Supprime une tension."""
    from knowbase.api.services.governance_conflict_service import get_governance_conflict_service

    service = get_governance_conflict_service(tenant_id)
    success = await service.delete_tension(tension_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Tension {tension_id} non trouvée")

    return {
        "success": True,
        "tension_id": tension_id,
        "message": "Tension supprimée"
    }


# =============================================================================
# Pass 2 Background Jobs (Production-Ready)
# =============================================================================

class Pass2JobRequest(BaseModel):
    """Requête pour créer un job Pass2."""
    document_id: Optional[str] = None
    skip_promotion: bool = False  # Pass 2.0: ProtoConcepts → CanonicalConcepts
    skip_classify: bool = False
    skip_enrich: bool = False
    skip_consolidate: bool = False
    skip_corpus_er: bool = False
    batch_size: int = Field(default=500, ge=10, le=1000, description="Taille des batches de classification")
    process_all: bool = Field(default=True, description="Si True, traite tous les concepts sans limite")


@router.post(
    "/pass2/jobs",
    summary="Créer un job Pass2 en background",
    description="""
    Crée et lance un job Pass2 en background.
    Retourne immédiatement avec un job_id pour suivre la progression.

    Le job s'exécute dans le worker et met à jour sa progression dans Redis.
    Utilisez GET /pass2/jobs/{job_id} pour suivre la progression.
    """
)
async def create_pass2_job(
    request: Pass2JobRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Crée un job Pass2 en background."""
    from knowbase.ingestion.queue.pass2_jobs import enqueue_pass2_full_job

    state = enqueue_pass2_full_job(
        tenant_id=tenant_id,
        document_id=request.document_id,
        skip_promotion=request.skip_promotion,
        skip_classify=request.skip_classify,
        skip_enrich=request.skip_enrich,
        skip_consolidate=request.skip_consolidate,
        skip_corpus_er=request.skip_corpus_er,
        batch_size=request.batch_size,
        process_all=request.process_all,
        created_by=admin.get("email", "admin")
    )

    # Retourne l'état complet du job pour le frontend
    return state.to_dict()


@router.get(
    "/pass2/jobs/{job_id}",
    summary="Obtenir le statut d'un job Pass2",
    description="Retourne l'état complet du job incluant la progression en temps réel."
)
async def get_pass2_job(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Récupère le statut d'un job Pass2."""
    from knowbase.ingestion.queue.pass2_jobs import get_pass2_job_manager

    manager = get_pass2_job_manager()
    state = manager.get_job(job_id)

    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return state.to_dict()


@router.get(
    "/pass2/jobs",
    summary="Lister les jobs Pass2",
    description="Retourne la liste des jobs Pass2 récents."
)
async def list_pass2_jobs(
    limit: int = 20,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste les jobs Pass2."""
    from knowbase.ingestion.queue.pass2_jobs import get_pass2_job_manager

    manager = get_pass2_job_manager()
    jobs = manager.list_jobs(tenant_id=tenant_id, limit=limit)

    return {
        "jobs": [job.to_dict() for job in jobs],
        "total": len(jobs)
    }


@router.delete(
    "/pass2/jobs/{job_id}",
    summary="Annuler un job Pass2",
    description="Annule un job en cours d'exécution."
)
async def cancel_pass2_job(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Annule un job Pass2."""
    from knowbase.ingestion.queue.pass2_jobs import get_pass2_job_manager

    manager = get_pass2_job_manager()
    success = manager.cancel_job(job_id)

    if not success:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in status {state.status.value}"
            )

    return {
        "success": True,
        "job_id": job_id,
        "message": "Job cancelled"
    }


# =============================================================================
# Pass 3 Background Jobs (Semantic Consolidation / Validation)
# =============================================================================

class Pass3JobRequest(BaseModel):
    """Requête pour créer un job Pass3."""
    document_id: Optional[str] = None
    max_candidates: int = Field(default=50, ge=10, le=200, description="Nombre max de candidats par document")


@router.post(
    "/pass3/jobs",
    summary="Créer un job Pass3 en background",
    description="""
    Crée et lance un job Pass3 (Semantic Consolidation) en background.
    Retourne immédiatement avec un job_id pour suivre la progression.

    Le job s'exécute dans le worker et met à jour sa progression dans Redis.
    Utilisez GET /pass3/jobs/{job_id} pour suivre la progression.
    """
)
async def create_pass3_job(
    request: Pass3JobRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Crée un job Pass3 en background."""
    from knowbase.ingestion.queue.pass3_jobs import enqueue_pass3_job

    state = enqueue_pass3_job(
        tenant_id=tenant_id,
        document_id=request.document_id,
        max_candidates=request.max_candidates,
        created_by=admin.get("email", "admin")
    )

    return state.to_dict()


@router.get(
    "/pass3/jobs/{job_id}",
    summary="Obtenir le statut d'un job Pass3",
    description="Retourne l'état complet du job incluant la progression en temps réel."
)
async def get_pass3_job(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Récupère le statut d'un job Pass3."""
    from knowbase.ingestion.queue.pass3_jobs import get_pass3_job_manager

    manager = get_pass3_job_manager()
    state = manager.get_job(job_id)

    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return state.to_dict()


@router.get(
    "/pass3/jobs",
    summary="Lister les jobs Pass3",
    description="Retourne la liste des jobs Pass3 récents."
)
async def list_pass3_jobs(
    limit: int = 20,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste les jobs Pass3."""
    from knowbase.ingestion.queue.pass3_jobs import get_pass3_job_manager

    manager = get_pass3_job_manager()
    jobs = manager.list_jobs(tenant_id=tenant_id, limit=limit)

    return {
        "jobs": [job.to_dict() for job in jobs],
        "total": len(jobs)
    }


@router.delete(
    "/pass3/jobs/{job_id}",
    summary="Annuler un job Pass3",
    description="Annule un job en cours d'exécution."
)
async def cancel_pass3_job(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Annule un job Pass3."""
    from knowbase.ingestion.queue.pass3_jobs import get_pass3_job_manager

    manager = get_pass3_job_manager()
    success = manager.cancel_job(job_id)

    if not success:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in status {state.status.value}"
            )

    return {
        "success": True,
        "job_id": job_id,
        "message": "Job cancelled"
    }


# =============================================================================
# Pass 4 Background Jobs (Corpus Consolidation: ER + Links)
# =============================================================================

class Pass4JobRequest(BaseModel):
    """Requête pour créer un job Pass4."""
    skip_er: bool = Field(default=False, description="Ignorer Entity Resolution (Pass 4a)")
    skip_links: bool = Field(default=False, description="Ignorer Corpus Links (Pass 4b)")
    dry_run: bool = Field(default=False, description="Mode simulation pour ER")


@router.post(
    "/pass4/jobs",
    summary="Créer un job Pass4 en background",
    description="""
    Crée et lance un job Pass4 (Corpus Consolidation) en background.
    Retourne immédiatement avec un job_id pour suivre la progression.

    Pass 4 comprend:
    - Pass 4a: Entity Resolution (CORPUS_ER) - fusionne les concepts dupliqués
    - Pass 4b: Corpus Links (CO_OCCURS_IN_CORPUS) - crée les liens faibles cross-doc

    Le job s'exécute dans le worker et met à jour sa progression dans Redis.
    Utilisez GET /pass4/jobs/{job_id} pour suivre la progression.
    """
)
async def create_pass4_job(
    request: Pass4JobRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Crée un job Pass4 en background."""
    from knowbase.ingestion.queue.pass4_jobs import enqueue_pass4_job

    state = enqueue_pass4_job(
        tenant_id=tenant_id,
        skip_er=request.skip_er,
        skip_links=request.skip_links,
        dry_run=request.dry_run,
        created_by=admin.get("email", "admin")
    )

    return state.to_dict()


@router.get(
    "/pass4/jobs/{job_id}",
    summary="Obtenir le statut d'un job Pass4",
    description="Retourne l'état complet du job incluant la progression en temps réel."
)
async def get_pass4_job(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Récupère le statut d'un job Pass4."""
    from knowbase.ingestion.queue.pass4_jobs import get_pass4_job_manager

    manager = get_pass4_job_manager()
    state = manager.get_job(job_id)

    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return state.to_dict()


@router.get(
    "/pass4/jobs",
    summary="Lister les jobs Pass4",
    description="Retourne la liste des jobs Pass4 récents."
)
async def list_pass4_jobs(
    limit: int = 20,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste les jobs Pass4."""
    from knowbase.ingestion.queue.pass4_jobs import get_pass4_job_manager

    manager = get_pass4_job_manager()
    jobs = manager.list_jobs(tenant_id=tenant_id, limit=limit)

    return {
        "jobs": [job.to_dict() for job in jobs],
        "total": len(jobs)
    }


@router.delete(
    "/pass4/jobs/{job_id}",
    summary="Annuler un job Pass4",
    description="Annule un job en cours d'exécution."
)
async def cancel_pass4_job(
    job_id: str,
    admin: dict = Depends(require_admin),
):
    """Annule un job Pass4."""
    from knowbase.ingestion.queue.pass4_jobs import get_pass4_job_manager

    manager = get_pass4_job_manager()
    success = manager.cancel_job(job_id)

    if not success:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in status {state.status.value}"
            )

    return {
        "success": True,
        "job_id": job_id,
        "message": "Job cancelled"
    }


# =============================================================================
# Enrichment KG (Pass 2a + Pass 2b + Pass 3)
# =============================================================================

class EnrichmentStatusResponse(BaseModel):
    """Statut étendu pour la page Enrichment."""
    # Pass 1 output
    proto_concepts: int = 0
    canonical_concepts: int = 0
    mentioned_in_count: int = 0

    # Pass 2a output (Structural Topics)
    topics_count: int = 0
    has_topic_count: int = 0
    covers_count: int = 0

    # Pass 2b output
    raw_assertions: int = 0

    # Pass 3 output (Semantic Consolidation)
    proven_relations: int = 0

    # Jobs
    pending_jobs: int = 0
    running_jobs: int = 0

    # Entity Resolution stats
    er_standalone_concepts: int = 0
    er_merged_concepts: int = 0
    er_pending_proposals: int = 0


@router.get(
    "/enrichment/status",
    response_model=EnrichmentStatusResponse,
    summary="Statut étendu Enrichment KG",
    description="""
    Récupère le statut étendu pour la page Enrichment (Pass 2 + Pass 3).

    Affiche:
    - Pass 1: ProtoConcepts, CanonicalConcepts, MENTIONED_IN
    - Pass 2a: Topics, HAS_TOPIC, COVERS
    - Pass 2b: RawAssertions
    - Pass 3: Relations prouvées (avec evidence)
    - Entity Resolution stats
    """
)
async def get_enrichment_status(
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère le statut étendu pour Enrichment."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    status = service.get_enrichment_status()

    return EnrichmentStatusResponse(
        proto_concepts=status.proto_concepts,
        canonical_concepts=status.canonical_concepts,
        mentioned_in_count=status.mentioned_in_count,
        topics_count=status.topics_count,
        has_topic_count=status.has_topic_count,
        covers_count=status.covers_count,
        raw_assertions=status.raw_assertions,
        proven_relations=status.proven_relations,
        pending_jobs=status.pending_jobs,
        running_jobs=status.running_jobs,
        er_standalone_concepts=status.er_standalone_concepts,
        er_merged_concepts=status.er_merged_concepts,
        er_pending_proposals=status.er_pending_proposals
    )


@router.post(
    "/pass2/structural-topics",
    response_model=Pass2ResultResponse,
    summary="Exécuter STRUCTURAL_TOPICS (Pass 2a)",
    description="""
    Exécute la phase STRUCTURAL_TOPICS de Pass 2.

    Cette phase:
    1. Extrait les Topics depuis les headers H1/H2 du document
    2. Crée les CanonicalConcept type='TOPIC'
    3. Crée les relations HAS_TOPIC (Document → Topic)
    4. Crée les relations COVERS (Topic → Concept) basées sur salience

    **Prérequis**: Documents importés avec Pass 1 (ProtoConcepts/CanonicalConcepts)
    """
)
async def run_structural_topics(
    request: Pass2PhaseRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute STRUCTURAL_TOPICS (Pass 2a)."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = await service.run_structural_topics(
        document_id=request.document_id
    )

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


class Pass3Request(BaseModel):
    """Requête pour exécuter Pass 3."""
    document_id: Optional[str] = Field(None, description="Filtrer par document")
    max_candidates: int = Field(50, description="Nombre max de candidats par document")


@router.post(
    "/pass3/run",
    response_model=Pass2ResultResponse,
    summary="Exécuter Pass 3 (Semantic Consolidation)",
    description="""
    Exécute Pass 3: Semantic Consolidation.

    Cette phase:
    1. Génère des candidats de relations via co-présence Topic/Section
    2. Vérifie chaque candidat avec LLM extractif (doit citer la preuve exacte)
    3. Persiste uniquement les relations avec preuves vérifiables

    **Prérequis**: Pass 2a doit avoir été exécuté (Topics/COVERS créés)

    **Garanties**:
    - TOUTE relation créée a evidence_context_ids non vide
    - TOUTE relation a une evidence_quote vérifiable
    - ABSTAIN préféré à hallucination
    """
)
async def run_pass3(
    request: Pass3Request,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Exécute Pass 3 Semantic Consolidation."""
    from knowbase.api.services.pass2_service import get_pass2_service

    service = get_pass2_service(tenant_id)
    result = await service.run_semantic_consolidation(
        document_id=request.document_id,
        max_candidates=request.max_candidates
    )

    return Pass2ResultResponse(
        success=result.success,
        phase=result.phase,
        items_processed=result.items_processed,
        items_created=result.items_created,
        items_updated=result.items_updated,
        execution_time_ms=result.execution_time_ms,
        errors=result.errors,
        details=result.details
    )


class ScheduleEnrichmentRequest(BaseModel):
    """Requête pour programmer un batch d'enrichissement."""
    run_pass2: bool = Field(True, description="Exécuter Pass 2 (Topics + Classify + Relations)")
    run_pass3: bool = Field(True, description="Exécuter Pass 3 (Semantic Consolidation)")
    scheduled_time: Optional[str] = Field(None, description="Heure de programmation (HH:MM) ou 'tonight'")


@router.post(
    "/enrichment/schedule",
    summary="Programmer un batch d'enrichissement nocturne",
    description="""
    Programme l'exécution de Pass 2 et/ou Pass 3 en batch.

    Options:
    - `run_pass2`: Exécute Topics (2a) + Classify (2b-1) + Relations (2b-2)
    - `run_pass3`: Exécute Semantic Consolidation
    - `scheduled_time`: "tonight" ou "HH:MM" (ex: "02:00")

    Si `scheduled_time` est omis, exécute immédiatement en background.
    """
)
async def schedule_enrichment(
    request: ScheduleEnrichmentRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Programme un batch d'enrichissement."""
    from knowbase.ingestion.queue.pass2_jobs import enqueue_pass2_full_job

    # Pour l'instant, on lance immédiatement
    # TODO: Implémenter la planification horaire avec celery-beat ou similar
    if request.scheduled_time and request.scheduled_time != "now":
        return {
            "success": True,
            "message": f"Enrichissement programmé pour {request.scheduled_time}",
            "scheduled_time": request.scheduled_time,
            "run_pass2": request.run_pass2,
            "run_pass3": request.run_pass3,
            "note": "Planification horaire non encore implémentée - exécution différée"
        }

    # Exécution immédiate en background
    state = enqueue_pass2_full_job(
        tenant_id=tenant_id,
        document_id=None,  # Tous les documents
        skip_classify=not request.run_pass2,
        skip_enrich=not request.run_pass2,
        skip_consolidate=not request.run_pass2,
        skip_corpus_er=True,  # ER séparé
        created_by=admin.get("email", "admin")
    )

    return {
        "success": True,
        "message": "Job d'enrichissement créé",
        "job_id": state.job_id,
        "run_pass2": request.run_pass2,
        "run_pass3": request.run_pass3,
        "scheduled_time": "now"
    }


# =============================================================================
# Structural Graph Archiving (Post-Pass 3)
# =============================================================================

class ArchivableDocumentsResponse(BaseModel):
    """Réponse liste documents archivables."""
    count: int
    documents: List[Dict]


class ArchiveDocumentRequest(BaseModel):
    """Requête pour archiver un document."""
    document_id: str = Field(..., description="ID du document à archiver")
    force: bool = Field(False, description="Forcer l'archivage même si Pass 3 incomplet (DANGEREUX)")


class ArchiveDocumentResponse(BaseModel):
    """Réponse archivage document."""
    success: bool
    document_id: str
    nodes_archived: int
    archive_path: str
    message: str


@router.get(
    "/archives/archivable",
    response_model=ArchivableDocumentsResponse,
    summary="Lister documents archivables",
    description="""
    Liste les documents éligibles à l'archivage structural.

    **Conditions d'éligibilité**:
    - Pass 1 complet (status = COMPLETE)
    - Pass 2 complet (status = COMPLETE)
    - Phase semantic_consolidation (Pass 3) exécutée

    **Nodes archivables** (72% du total):
    - DocItem: Éléments structurels atomiques
    - TypeAwareChunk: Chunks typés pour extraction
    - PageContext: Contexte de pagination

    **Nodes préservés** (28%):
    - DocumentContext/DocumentVersion: Métadonnées
    - SectionContext: Hiérarchie sections
    - ProtoConcept/CanonicalConcept: Concepts extraits
    """
)
async def list_archivable_documents(
    min_age_days: int = Query(0, description="Âge minimum depuis Pass 3 complet"),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste les documents archivables."""
    from knowbase.structural.archiver import get_archiver

    archiver = get_archiver()
    documents = archiver.get_archivable_documents(tenant_id, min_age_days)

    return ArchivableDocumentsResponse(
        count=len(documents),
        documents=documents
    )


@router.post(
    "/archives/archive",
    response_model=ArchiveDocumentResponse,
    summary="Archiver un document",
    description="""
    Archive les nodes structurels d'un document post-Pass 3.

    **Workflow**:
    1. Vérifie que Pass 3 est complet
    2. Exporte DocItem, TypeAwareChunk, PageContext vers JSON
    3. Supprime ces nodes de Neo4j (transaction atomique)
    4. Marque le document comme archivé

    **Réversible**: Utilisez /archives/restore pour réimporter.

    **Gain estimé**: ~77% réduction des nodes Neo4j
    """
)
async def archive_document(
    request: ArchiveDocumentRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Archive un document."""
    from knowbase.structural.archiver import get_archiver

    archiver = get_archiver()

    try:
        stats = archiver.archive_document(
            document_id=request.document_id,
            tenant_id=tenant_id,
            force=request.force
        )

        if not stats:
            raise HTTPException(
                status_code=400,
                detail=f"Document {request.document_id} non éligible (Pass 3 non complet ou aucun node à archiver)"
            )

        logger.info(
            f"[ARCHIVER] Document {request.document_id} archivé par {admin.get('email')}: "
            f"{stats.total_nodes_archived} nodes"
        )

        return ArchiveDocumentResponse(
            success=True,
            document_id=request.document_id,
            nodes_archived=stats.total_nodes_archived,
            archive_path=stats.archive_path,
            message=f"Archivé: {stats.doc_items_archived} DocItems, {stats.type_aware_chunks_archived} Chunks, {stats.page_contexts_archived} Pages"
        )

    except Exception as e:
        logger.error(f"[ARCHIVER] Erreur archivage {request.document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RestoreDocumentRequest(BaseModel):
    """Requête pour restaurer un document."""
    document_id: str = Field(..., description="ID du document à restaurer")


@router.post(
    "/archives/restore",
    summary="Restaurer un document archivé",
    description="""
    Réimporte les nodes structurels depuis l'archive JSON.

    **Workflow**:
    1. Lit le manifest de l'archive
    2. Recrée PageContext, DocItem, TypeAwareChunk dans Neo4j
    3. Rétablit les relations
    4. Supprime l'archive si succès

    **Note**: Opération idempotente - échoue si nodes déjà présents.
    """
)
async def restore_document(
    request: RestoreDocumentRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Restaure un document archivé."""
    from knowbase.structural.archiver import get_archiver

    archiver = get_archiver()

    try:
        result = archiver.restore_document(
            document_id=request.document_id,
            tenant_id=tenant_id
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Archive non trouvée pour {request.document_id}"
            )

        logger.info(
            f"[ARCHIVER] Document {request.document_id} restauré par {admin.get('email')}: "
            f"{result['total_nodes_restored']} nodes"
        )

        return {
            "success": True,
            "document_id": request.document_id,
            "nodes_restored": result["total_nodes_restored"],
            "counts": result["counts"],
            "message": "Document restauré avec succès"
        }

    except Exception as e:
        logger.error(f"[ARCHIVER] Erreur restauration {request.document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/archives/status/{document_id}",
    summary="Statut d'archivage d'un document",
    description="Vérifie si un document est archivé et retourne les détails."
)
async def get_archive_status(
    document_id: str,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Récupère le statut d'archivage d'un document."""
    from knowbase.structural.archiver import get_archiver

    archiver = get_archiver()
    status = archiver.get_archive_status(document_id, tenant_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Document {document_id} non trouvé")

    return status


@router.get(
    "/archives/list",
    summary="Lister toutes les archives",
    description="Retourne la liste de tous les documents archivés pour le tenant."
)
async def list_archives(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Liste toutes les archives."""
    from knowbase.structural.archiver import get_archiver

    archiver = get_archiver()
    archives = archiver.list_archives(tenant_id)

    return {
        "count": len(archives),
        "archives": archives
    }


class BatchArchiveRequest(BaseModel):
    """Requête pour archivage en batch."""
    min_age_days: int = Field(0, description="Âge minimum depuis Pass 3")
    max_documents: int = Field(10, description="Nombre max de documents à archiver")


@router.post(
    "/archives/batch",
    summary="Archiver plusieurs documents en batch",
    description="""
    Archive tous les documents éligibles en un seul appel.

    **Recommandé pour maintenance nocturne.**

    Paramètres:
    - `min_age_days`: Attendre X jours après Pass 3 avant d'archiver
    - `max_documents`: Limiter le nombre de documents par batch

    Les documents sont archivés dans l'ordre de leur date de Pass 3 (plus anciens d'abord).
    """
)
async def batch_archive(
    request: BatchArchiveRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
):
    """Archive plusieurs documents en batch."""
    from knowbase.structural.archiver import archive_completed_documents

    try:
        results = archive_completed_documents(
            tenant_id=tenant_id,
            min_age_days=request.min_age_days,
            max_documents=request.max_documents
        )

        total_nodes = sum(r.total_nodes_archived for r in results)

        logger.info(
            f"[ARCHIVER] Batch archivage par {admin.get('email')}: "
            f"{len(results)} documents, {total_nodes} nodes"
        )

        return {
            "success": True,
            "documents_archived": len(results),
            "total_nodes_archived": total_nodes,
            "details": [
                {
                    "document_id": r.document_id,
                    "nodes_archived": r.total_nodes_archived,
                    "archive_path": r.archive_path
                }
                for r in results
            ]
        }

    except Exception as e:
        logger.error(f"[ARCHIVER] Erreur batch archivage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Settings LLM Mode — Normal / Partial Local / Full Local
# ============================================================================


class LlmModeRequest(BaseModel):
    """Requête pour changer le mode LLM."""
    mode: str = Field(
        ...,
        description="Mode LLM: 'normal' | 'partial_local' | 'full_local'",
        pattern="^(normal|partial_local|full_local)$"
    )


class LlmModeResponse(BaseModel):
    """Réponse du mode LLM actuel."""
    mode: str
    synthesis_model: str
    judge_model: str


class LlmModeStatusResponse(BaseModel):
    """État temps réel du mode LLM."""
    mode: str
    synthesis_model: str
    judge_model: str
    ollama_available: bool
    burst_active: bool
    burst_provider: Optional[str] = None


@router.get("/settings/llm-mode/current")
async def get_llm_mode_current(
    db: Session = Depends(get_db),
):
    """Retourne le mode LLM actuel (endpoint public, pas de role admin requis).
    Utilise par l'indicateur top menu visible sur toutes les pages."""
    import json as _json

    setting = db.query(SystemSetting).filter(
        SystemSetting.key == "llm_mode"
    ).first()

    mode = "normal"
    if setting:
        data = _json.loads(setting.value)
        mode = data.get("mode", "normal")

    return {"mode": mode}


@router.get("/settings/llm-mode", response_model=LlmModeResponse)
async def get_llm_mode(
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Retourne le mode LLM actuel (normal, partial_local, full_local)."""
    import json as _json

    setting = db.query(SystemSetting).filter(
        SystemSetting.key == "llm_mode"
    ).first()

    if setting:
        data = _json.loads(setting.value)
    else:
        data = {"mode": "normal"}

    # Lire les modèles depuis la config YAML
    from knowbase.common.llm_router import get_llm_router
    router_instance = get_llm_router()
    local_config = router_instance._config.get("local_mode", {})

    return LlmModeResponse(
        mode=data.get("mode", "normal"),
        synthesis_model=local_config.get("default_model", "qwen2.5:14b"),
        judge_model=local_config.get("judge_model", "m-prometheus-14b"),
    )


@router.put("/settings/llm-mode", response_model=LlmModeResponse)
async def set_llm_mode(
    request: LlmModeRequest,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Change le mode LLM. Persiste en PostgreSQL et invalide le cache Redis."""
    import json as _json
    from datetime import datetime, timezone

    valid_modes = {"normal", "partial_local", "full_local"}
    if request.mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Mode invalide. Valeurs acceptées: {valid_modes}")

    # Upsert dans PostgreSQL
    setting = db.query(SystemSetting).filter(
        SystemSetting.key == "llm_mode"
    ).first()

    value_json = _json.dumps({"mode": request.mode})

    if setting:
        setting.value = value_json
        setting.updated_at = datetime.now(timezone.utc)
        setting.updated_by = admin.get("email", "admin")
    else:
        setting = SystemSetting(
            key="llm_mode",
            value=value_json,
            updated_by=admin.get("email", "admin"),
        )
        db.add(setting)

    db.commit()

    # Invalider le cache Redis + mémoire du llm_router
    from knowbase.common.llm_router import get_llm_router
    get_llm_router().invalidate_llm_mode_cache()

    logger.info(f"[ADMIN:LLM_MODE] Mode changé → {request.mode} par {admin.get('email', '?')}")

    local_config = get_llm_router()._config.get("local_mode", {})
    return LlmModeResponse(
        mode=request.mode,
        synthesis_model=local_config.get("default_model", "qwen2.5:14b"),
        judge_model=local_config.get("judge_model", "m-prometheus-14b"),
    )


@router.get("/settings/llm-mode/status", response_model=LlmModeStatusResponse)
async def get_llm_mode_status(
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """État temps réel : mode actif, Ollama up/down, burst en cours."""
    import json as _json
    import os

    setting = db.query(SystemSetting).filter(
        SystemSetting.key == "llm_mode"
    ).first()
    mode = "normal"
    if setting:
        data = _json.loads(setting.value)
        mode = data.get("mode", "normal")

    # Vérifier Ollama
    ollama_available = False
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    try:
        import httpx
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{ollama_url}/api/tags")
            ollama_available = resp.status_code == 200
    except Exception:
        pass

    # Vérifier burst actif
    burst_active = False
    burst_provider = None
    try:
        from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
        state = get_burst_state_from_redis()
        if state and state.get("active"):
            burst_active = True
            burst_provider = state.get("provider", "ec2")
    except Exception:
        pass

    from knowbase.common.llm_router import get_llm_router
    local_config = get_llm_router()._config.get("local_mode", {})

    return LlmModeStatusResponse(
        mode=mode,
        synthesis_model=local_config.get("default_model", "qwen2.5:14b"),
        judge_model=local_config.get("judge_model", "m-prometheus-14b"),
        ollama_available=ollama_available,
        burst_active=burst_active,
        burst_provider=burst_provider,
    )


# ============================================================================
# V2 — Configuration LLM par usage (Architecture 4 couches)
# ============================================================================


@router.get("/settings/llm-config")
async def get_llm_config(
    admin: dict = Depends(require_admin),
):
    """Retourne la configuration LLM par usage (toutes les configs)."""
    from knowbase.common.llm_config import get_usage_config_store, check_compatibility

    store = get_usage_config_store()
    configs = store.get_all_configs()
    preset = store._detect_active_preset(configs)
    emb = store.get_embedding_state()

    # Grouper par famille
    families = {
        "search": ["search_simple", "search_crossdoc", "search_tension"],
        "batch": ["claim_extraction", "entity_resolution", "relation_extraction",
                   "crossdoc_reasoning", "perspective_generation", "canonicalization"],
        "dedicated": ["judge_primary", "vision_analysis", "embeddings"],
        "lightweight": ["classification", "enrichment"],
    }

    result = {
        "preset": preset,
        "embedding_state": emb.to_dict(),
        "families": {},
        "configs": {},
    }

    for family, usage_ids in families.items():
        family_configs = []
        for uid_str in usage_ids:
            from knowbase.common.llm_config import UsageId
            try:
                uid = UsageId(uid_str)
            except ValueError:
                continue
            contract = configs.get(uid)
            if contract:
                compat = check_compatibility(contract.runtime, contract)
                family_configs.append({
                    **contract.to_dict(),
                    "compatibility": compat.value,
                })
        result["families"][family] = family_configs

    for uid, contract in configs.items():
        compat = check_compatibility(contract.runtime, contract)
        result["configs"][uid.value] = {
            **contract.to_dict(),
            "compatibility": compat.value,
        }

    return result


@router.put("/settings/llm-config/{usage_id}")
async def update_llm_config(
    usage_id: str,
    request: dict,
    admin: dict = Depends(require_admin),
):
    """Met a jour la config d'un usage. Valide le contrat avant persistence."""
    from knowbase.common.llm_config import UsageId, get_usage_config_store

    try:
        uid = UsageId(usage_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Usage inconnu: {usage_id}")

    store = get_usage_config_store()
    try:
        updated = store.set_config(uid, request, updated_by=admin.get("email", "admin"))
        return {"success": True, "config": updated.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/settings/llm-config/preset")
async def apply_llm_preset(
    request: dict,
    admin: dict = Depends(require_admin),
):
    """Applique un preset (eco/balanced/max_quality)."""
    from knowbase.common.llm_config import get_usage_config_store

    preset = request.get("preset", "")
    store = get_usage_config_store()
    try:
        configs = store.apply_preset(preset, updated_by=admin.get("email", "admin"))
        return {
            "success": True,
            "preset": preset,
            "usages_configured": len(configs),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/settings/llm-config/snapshot")
async def get_llm_config_snapshot(
    admin: dict = Depends(require_admin),
):
    """Snapshot fige de la config — pour benchmark reports."""
    from knowbase.common.llm_config import get_usage_config_store
    store = get_usage_config_store()
    return store.snapshot()


@router.get("/settings/llm-config/status")
async def get_llm_config_status():
    """Etat temps reel (public, pour l'indicateur top menu)."""
    import os
    from knowbase.common.llm_config import get_usage_config_store

    store = get_usage_config_store()
    configs = store.get_all_configs()
    preset = store._detect_active_preset(configs)

    # Verifier Ollama
    ollama_available = False
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    try:
        import httpx
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{ollama_url}/api/tags")
            ollama_available = resp.status_code == 200
    except Exception:
        pass

    # Verifier burst actif
    burst_active = False
    try:
        from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
        state = get_burst_state_from_redis()
        burst_active = bool(state and state.get("active"))
    except Exception:
        pass

    # Compter les runtimes
    from collections import Counter
    runtimes = Counter(c.runtime.value for c in configs.values())

    return {
        "preset": preset,
        "ollama_available": ollama_available,
        "burst_active": burst_active,
        "runtimes": dict(runtimes),
        "v2_enabled": os.getenv("OSMOSIS_USE_V2_CONFIG", "0") == "1",
    }


__all__ = ["router"]
