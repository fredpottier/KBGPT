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
from knowbase.db.models import AuditLog
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

    Returns:
        Dict avec résultats de purge par composant
    """
    # Permettre appel sans body (compatibilité avec anciennes versions)
    purge_schema = request.purge_schema if request else False

    schema_msg = " + SCHÉMA" if purge_schema else ""
    logger.warning(f"🚨 Requête PURGE SYSTÈME reçue{schema_msg}")

    try:
        purge_service = PurgeService()
        results = await purge_service.purge_all_data(purge_schema=purge_schema)

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
        max_pairs=request.limit
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
# Pass 2 Background Jobs (Production-Ready)
# =============================================================================

class Pass2JobRequest(BaseModel):
    """Requête pour créer un job Pass2."""
    document_id: Optional[str] = None
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


__all__ = ["router"]
