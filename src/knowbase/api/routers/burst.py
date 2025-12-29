"""
Router FastAPI pour le Mode Burst (EC2 Spot).

Phase 4 - API Administration Mode Burst

Endpoints:
- GET  /api/burst/status     - Statut actuel du mode Burst
- GET  /api/burst/config     - Configuration Burst actuelle
- POST /api/burst/prepare    - Préparer un batch de documents
- POST /api/burst/start      - Démarrer l'infrastructure Spot
- POST /api/burst/process    - Lancer le traitement du batch
- POST /api/burst/cancel     - Annuler le batch en cours
- GET  /api/burst/events     - Timeline des événements
- GET  /api/burst/documents  - Statut des documents du batch
- GET  /api/burst/providers  - Statut des providers (LLM/Embeddings)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from pathlib import Path
import os

from knowbase.api.dependencies import require_admin, get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "burst_router.log")

router = APIRouter(prefix="/api/burst", tags=["burst"])


# ============================================================================
# Schemas Pydantic
# ============================================================================

class InstanceDetails(BaseModel):
    """Détails de l'instance EC2 Spot."""
    instance_id: Optional[str] = None
    public_ip: Optional[str] = None
    instance_type: Optional[str] = None
    availability_zone: Optional[str] = None
    spot_price_hourly: Optional[float] = None  # Prix spot actuel $/h
    uptime_seconds: Optional[int] = None  # Temps depuis démarrage
    gpu_type: Optional[str] = None  # Ex: "NVIDIA L4 24GB"
    gpu_memory_gb: Optional[int] = None
    vllm_status: str = "unknown"  # healthy, unhealthy, starting, unknown
    embeddings_status: str = "unknown"  # healthy, unhealthy, starting, unknown
    ami_id: Optional[str] = None
    launch_time: Optional[str] = None


class BurstStatusResponse(BaseModel):
    """Réponse statut Burst."""
    active: bool
    status: str  # idle, preparing, requesting_spot, waiting_capacity, instance_starting, ready, processing, interrupted, resuming, completed, failed, cancelled
    batch_id: Optional[str] = None
    total_documents: int = 0
    documents_done: int = 0
    documents_failed: int = 0
    documents_pending: int = 0
    progress_percent: float = 0.0
    instance_ip: Optional[str] = None
    instance_type: Optional[str] = None
    interruption_count: int = 0
    vllm_url: Optional[str] = None
    embeddings_url: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    # Phase 4.1: Détails enrichis de l'instance
    instance_details: Optional[InstanceDetails] = None
    # Mode dual-logging (OpenAI + vLLM en parallèle)
    dual_logging: bool = False


class BurstConfigResponse(BaseModel):
    """Configuration Burst actuelle."""
    enabled: bool = False
    aws_region: str = "eu-west-1"
    spot_max_price: float = 0.80
    spot_instance_types: List[str] = ["g5.xlarge", "g5.2xlarge", "g4dn.xlarge"]
    vllm_model: str = "Qwen/Qwen2.5-7B-Instruct"
    embeddings_model: str = "intfloat/multilingual-e5-large"
    vllm_port: int = 8000
    embeddings_port: int = 8001
    instance_boot_timeout: int = 600
    max_retries: int = 3


class PrepareBatchRequest(BaseModel):
    """Requête pour préparer un batch."""
    document_paths: Optional[List[str]] = Field(
        None,
        description="Liste des chemins de documents à traiter. Si vide, utilise data/burst/pending/"
    )
    batch_id: Optional[str] = Field(
        None,
        description="ID du batch personnalisé. Si vide, génération automatique."
    )


class PrepareBatchResponse(BaseModel):
    """Réponse préparation batch."""
    success: bool
    batch_id: str
    documents_count: int
    documents: List[Dict]
    message: str


class StartInfraRequest(BaseModel):
    """Requête pour démarrer l'infrastructure."""
    force: bool = Field(
        False,
        description="Force le redémarrage même si une instance existe"
    )
    dual_logging: bool = Field(
        False,
        description="Active le dual-logging: OpenAI + vLLM en parallèle pour comparaison qualité"
    )


class StartInfraResponse(BaseModel):
    """Réponse démarrage infrastructure."""
    success: bool
    batch_id: str
    status: str
    instance_ip: Optional[str] = None
    vllm_url: Optional[str] = None
    embeddings_url: Optional[str] = None
    message: str


class ProcessBatchResponse(BaseModel):
    """Réponse traitement batch."""
    success: bool
    batch_id: str
    status: str
    documents_done: int
    documents_failed: int
    message: str


class CancelResponse(BaseModel):
    """Réponse annulation."""
    success: bool
    batch_id: Optional[str] = None
    message: str


class BurstEventResponse(BaseModel):
    """Un événement dans la timeline."""
    timestamp: str
    event_type: str
    message: str
    severity: str = "info"
    details: Optional[Dict] = None


class EventsListResponse(BaseModel):
    """Liste des événements."""
    batch_id: Optional[str] = None
    total: int
    events: List[BurstEventResponse]


class DocumentStatusResponse(BaseModel):
    """Statut d'un document."""
    path: str
    name: str
    status: str  # pending, processing, completed, failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    chunks_count: Optional[int] = None


class DocumentsListResponse(BaseModel):
    """Liste des documents du batch."""
    batch_id: Optional[str] = None
    total: int
    done: int
    failed: int
    pending: int
    documents: List[DocumentStatusResponse]


class ProvidersStatusResponse(BaseModel):
    """Statut des providers Burst."""
    burst_mode_active: bool
    llm_provider: str  # "local" ou "burst"
    llm_endpoint: Optional[str] = None
    llm_model: Optional[str] = None
    embeddings_provider: str  # "local" ou "burst"
    embeddings_endpoint: Optional[str] = None
    health: Dict = {}


class ActiveStackInfo(BaseModel):
    """Info sur une stack Burst active."""
    stack_name: str
    status: str
    created: Optional[str] = None
    spot_fleet_id: Optional[str] = None


class ActiveStacksResponse(BaseModel):
    """Liste des stacks actives."""
    stacks: List[ActiveStackInfo]
    count: int


class ReconnectRequest(BaseModel):
    """Requête de reconnexion."""
    stack_name: str = Field(..., description="Nom de la stack CloudFormation")


class ReconnectResponse(BaseModel):
    """Réponse de reconnexion."""
    success: bool
    batch_id: Optional[str] = None
    instance_ip: Optional[str] = None
    instance_type: Optional[str] = None
    status: str
    message: str


# ============================================================================
# Endpoints
# ============================================================================

@router.get(
    "/status",
    response_model=BurstStatusResponse,
    summary="Statut du mode Burst",
    description="""
    Retourne le statut actuel du mode Burst.

    **Statuts possibles:**
    - `idle`: Aucun batch actif
    - `preparing`: Préparation des documents
    - `requesting_spot`: CloudFormation en cours
    - `waiting_capacity`: Attente allocation Spot
    - `instance_starting`: Boot + init services
    - `ready`: Providers disponibles
    - `processing`: Batch en cours
    - `interrupted`: Spot perdu
    - `resuming`: Reprise en cours
    - `completed`: Batch terminé
    - `failed`: Erreur fatale
    - `cancelled`: Annulé
    """
)
async def get_burst_status(
    tenant_id: str = Depends(get_tenant_id),
) -> BurstStatusResponse:
    """Récupère le statut actuel du mode Burst."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()
        status = orchestrator.get_status()

        if status["status"] == "no_batch":
            return BurstStatusResponse(
                active=False,
                status="idle",
                batch_id=None,
            )

        state = orchestrator.state
        progress = state.get_progress() if state else {}

        return BurstStatusResponse(
            active=state.status.value not in ["idle", "completed", "failed", "cancelled"],
            status=state.status.value,
            batch_id=state.batch_id,
            total_documents=state.total_documents,
            documents_done=state.documents_done,
            documents_failed=state.documents_failed,
            documents_pending=progress.get("pending", 0),
            progress_percent=progress.get("percent", 0.0),
            instance_ip=state.instance_ip,
            instance_type=state.instance_type,
            interruption_count=state.interruption_count,
            vllm_url=state.vllm_url,
            embeddings_url=state.embeddings_url,
            created_at=state.created_at,
            started_at=state.started_at,
            dual_logging=getattr(state, 'dual_logging', False),
        )

    except ImportError:
        return BurstStatusResponse(
            active=False,
            status="unavailable",
            batch_id=None,
        )
    except Exception as e:
        logger.error(f"Erreur get_burst_status: {e}")
        return BurstStatusResponse(
            active=False,
            status="error",
            batch_id=None,
        )


@router.get(
    "/config",
    response_model=BurstConfigResponse,
    summary="Configuration Burst",
    description="Retourne la configuration actuelle du mode Burst (depuis variables d'environnement)."
)
async def get_burst_config(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> BurstConfigResponse:
    """Récupère la configuration Burst."""
    try:
        from knowbase.ingestion.burst import BurstConfig

        config = BurstConfig.from_env()

        return BurstConfigResponse(
            enabled=os.getenv("BURST_MODE_ENABLED", "false").lower() == "true",
            aws_region=config.aws_region,
            spot_max_price=config.spot_max_price,
            spot_instance_types=config.spot_instance_types,
            vllm_model=config.vllm_model,
            embeddings_model=config.embeddings_model,
            vllm_port=config.vllm_port,
            embeddings_port=config.embeddings_port,
            instance_boot_timeout=config.instance_boot_timeout,
            max_retries=config.max_retries,
        )

    except ImportError:
        return BurstConfigResponse(enabled=False)
    except Exception as e:
        logger.error(f"Erreur get_burst_config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/active-stacks",
    response_model=ActiveStacksResponse,
    summary="Lister les stacks actives",
    description="Liste les stacks CloudFormation Burst actives (pour reconnexion après redémarrage)."
)
async def get_active_stacks(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> ActiveStacksResponse:
    """Liste les stacks Burst actives dans AWS."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()
        stacks = orchestrator.find_active_burst_stacks()

        return ActiveStacksResponse(
            stacks=[
                ActiveStackInfo(
                    stack_name=s['stack_name'],
                    status=s['status'],
                    created=str(s['created']) if s.get('created') else None,
                    spot_fleet_id=s.get('spot_fleet_id'),
                )
                for s in stacks
            ],
            count=len(stacks)
        )

    except ImportError:
        return ActiveStacksResponse(stacks=[], count=0)
    except Exception as e:
        logger.error(f"Erreur get_active_stacks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/reconnect",
    response_model=ReconnectResponse,
    summary="Reconnecter à une stack existante",
    description="""
    Reconnecte l'orchestrator à une stack CloudFormation existante.

    Utilisé après un redémarrage du container pour récupérer l'état
    d'une infrastructure Burst toujours active.
    """
)
async def reconnect_to_stack(
    request: ReconnectRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> ReconnectResponse:
    """Reconnecte à une stack Burst existante."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        # Vérifier si déjà connecté
        if orchestrator.state is not None:
            return ReconnectResponse(
                success=False,
                status="already_connected",
                message=f"Déjà connecté au batch {orchestrator.state.batch_id}. Annulez d'abord."
            )

        # Tenter la reconnexion
        orchestrator.reconnect_to_stack(request.stack_name)

        return ReconnectResponse(
            success=True,
            batch_id=orchestrator.state.batch_id,
            instance_ip=orchestrator.state.instance_ip,
            instance_type=orchestrator.state.instance_type,
            status=orchestrator.state.status.value,
            message=f"Reconnecté avec succès à {request.stack_name}"
        )

    except ImportError as e:
        raise HTTPException(status_code=500, detail="Module burst non disponible")
    except Exception as e:
        logger.error(f"Erreur reconnect: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/prepare",
    response_model=PrepareBatchResponse,
    summary="Préparer un batch de documents",
    description="""
    Prépare un batch de documents pour traitement en mode Burst.

    **Options:**
    - Fournir une liste de chemins de documents
    - Ou utiliser automatiquement le répertoire `data/burst/pending/`

    **Note:** Cette étape ne démarre pas encore l'infrastructure EC2.
    """
)
async def prepare_batch(
    request: PrepareBatchRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> PrepareBatchResponse:
    """Prépare un batch de documents."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, BurstConfig

        config = BurstConfig.from_env()
        orchestrator = get_burst_orchestrator()

        # Déterminer les documents
        if request.document_paths:
            document_paths = [Path(p) for p in request.document_paths]
        else:
            # Scanner le répertoire burst/pending
            pending_dir = Path(config.burst_pending_dir)
            if not pending_dir.exists():
                pending_dir.mkdir(parents=True, exist_ok=True)
                return PrepareBatchResponse(
                    success=False,
                    batch_id="",
                    documents_count=0,
                    documents=[],
                    message=f"Répertoire {pending_dir} créé. Ajoutez des documents à traiter."
                )

            document_paths = list(pending_dir.glob("*"))
            document_paths = [p for p in document_paths if p.is_file() and p.suffix.lower() in [".pdf", ".pptx", ".docx", ".xlsx"]]

        if not document_paths:
            return PrepareBatchResponse(
                success=False,
                batch_id="",
                documents_count=0,
                documents=[],
                message="Aucun document trouvé à traiter."
            )

        # Préparer le batch
        batch_id = orchestrator.prepare_batch(
            document_paths=document_paths,
            batch_id=request.batch_id
        )

        # Récupérer les documents préparés
        state = orchestrator.state
        documents = [
            {
                "path": d.path,
                "name": d.name,
                "status": d.status
            }
            for d in state.documents
        ]

        logger.info(f"[BURST] Batch {batch_id} préparé avec {len(documents)} documents")

        return PrepareBatchResponse(
            success=True,
            batch_id=batch_id,
            documents_count=len(documents),
            documents=documents,
            message=f"Batch préparé avec {len(documents)} documents. Utilisez /start pour lancer l'infrastructure."
        )

    except Exception as e:
        logger.error(f"Erreur prepare_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/start",
    response_model=StartInfraResponse,
    summary="Démarrer l'infrastructure Spot",
    description="""
    Démarre l'infrastructure EC2 Spot pour le mode Burst.

    **Étapes:**
    1. Déploiement CloudFormation Spot Fleet
    2. Attente allocation instance
    3. Boot et initialisation services (vLLM, Embeddings)
    4. Healthcheck et basculement des providers

    **Note:** Un batch doit être préparé au préalable via `/prepare`.
    """
)
async def start_infrastructure(
    request: StartInfraRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> StartInfraResponse:
    """Démarre l'infrastructure EC2 Spot."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, BurstStatus

        orchestrator = get_burst_orchestrator()

        # Vérifier qu'un batch est préparé
        if not orchestrator.state:
            raise HTTPException(
                status_code=400,
                detail="Aucun batch préparé. Utilisez /prepare d'abord."
            )

        if orchestrator.state.status != BurstStatus.PREPARING:
            if not request.force:
                raise HTTPException(
                    status_code=400,
                    detail=f"Batch en statut {orchestrator.state.status.value}. Utilisez force=true pour forcer."
                )

        # Configurer dual-logging si demandé
        if request.dual_logging:
            orchestrator.state.dual_logging = True
            logger.info("[BURST] Mode dual-logging activé pour ce batch")

        # Démarrer l'infrastructure (sync call wrapped)
        import asyncio
        success = await asyncio.to_thread(orchestrator.start_infrastructure)

        if not success:
            return StartInfraResponse(
                success=False,
                batch_id=orchestrator.state.batch_id,
                status=orchestrator.state.status.value,
                message="Échec du démarrage de l'infrastructure."
            )

        msg = "Infrastructure prête. "
        if request.dual_logging:
            msg += "Mode dual-logging activé (OpenAI + vLLM en parallèle)."
        else:
            msg += "Providers basculés vers EC2 Spot."

        return StartInfraResponse(
            success=True,
            batch_id=orchestrator.state.batch_id,
            status=orchestrator.state.status.value,
            instance_ip=orchestrator.state.instance_ip,
            vllm_url=orchestrator.state.vllm_url,
            embeddings_url=orchestrator.state.embeddings_url,
            message=msg
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur start_infrastructure: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/process",
    response_model=ProcessBatchResponse,
    summary="Lancer le traitement du batch",
    description="""
    Lance le traitement des documents du batch.

    **Prérequis:**
    - Batch préparé via `/prepare`
    - Infrastructure démarrée via `/start`

    **Note:** Le traitement utilise le pipeline d'ingestion existant,
    mais les appels LLM/Embeddings sont routés vers l'EC2 Spot.
    """
)
async def process_batch(
    background_tasks: BackgroundTasks,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> ProcessBatchResponse:
    """Lance le traitement du batch en arrière-plan."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, BurstStatus, EventSeverity

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state:
            raise HTTPException(
                status_code=400,
                detail="Aucun batch actif."
            )

        if orchestrator.state.status != BurstStatus.READY:
            raise HTTPException(
                status_code=400,
                detail=f"Batch pas prêt. Statut actuel: {orchestrator.state.status.value}"
            )

        # Lancer le traitement en arrière-plan (async)
        import asyncio
        from datetime import datetime, timezone

        async def run_batch():
            """Traite les documents du batch de manière async."""
            import traceback
            from knowbase.ingestion.pipelines.pptx_pipeline import process_pptx
            from knowbase.ingestion.pipelines.pdf_pipeline import process_pdf

            try:
                orchestrator.state.status = BurstStatus.PROCESSING
                orchestrator.state.started_at = datetime.now(timezone.utc).isoformat()
                orchestrator._add_event("processing_started", "Traitement du batch démarré")

                # Copier la liste pour éviter modification pendant itération
                docs_to_process = [d for d in orchestrator.state.documents if d.status == "pending"]
                logger.info(f"[BURST] Traitement de {len(docs_to_process)} documents...")

                for doc_status in docs_to_process:
                    doc_path = Path(doc_status.path)
                    doc_status.status = "processing"
                    doc_status.started_at = datetime.now(timezone.utc).isoformat()

                    try:
                        suffix = doc_path.suffix.lower()
                        logger.info(f"[BURST] Processing: {doc_path.name}")

                        # Les pipelines sont synchrones - utiliser to_thread pour ne pas bloquer
                        if suffix == ".pptx":
                            result = await asyncio.to_thread(process_pptx, doc_path)
                        elif suffix == ".pdf":
                            result = await asyncio.to_thread(process_pdf, doc_path)
                        else:
                            raise ValueError(f"Format non supporté: {suffix}")

                        doc_status.status = "completed"
                        doc_status.completed_at = datetime.now(timezone.utc).isoformat()
                        # Récupérer le nombre de concepts (OSMOSE) ou chunks selon le pipeline
                        if isinstance(result, dict):
                            doc_status.chunks_count = result.get("canonical_concepts", result.get("chunks_count", 0))
                        else:
                            doc_status.chunks_count = 0
                        orchestrator.state.documents_done += 1
                        logger.info(f"[BURST] ✅ Completed: {doc_path.name} ({doc_status.chunks_count} concepts)")

                    except Exception as e:
                        doc_status.status = "failed"
                        doc_status.error = str(e)
                        doc_status.completed_at = datetime.now(timezone.utc).isoformat()
                        orchestrator.state.documents_failed += 1
                        logger.error(f"[BURST] ❌ Failed: {doc_path.name} - {e}")
                        logger.error(f"[BURST] Traceback: {traceback.format_exc()}")

                # Batch terminé
                orchestrator.state.status = BurstStatus.COMPLETED
                orchestrator.state.completed_at = datetime.now(timezone.utc).isoformat()
                progress = orchestrator.state.get_progress()
                orchestrator._add_event(
                    "batch_completed",
                    f"Batch terminé: {orchestrator.state.documents_done} OK, {orchestrator.state.documents_failed} échecs",
                    details=progress
                )
                logger.info(f"[BURST:ORCHESTRATOR] ✅ Batch completed: {progress}")

            except Exception as e:
                orchestrator.state.status = BurstStatus.FAILED
                orchestrator._add_event("batch_error", f"Erreur batch: {e}", EventSeverity.ERROR)
                logger.error(f"[BURST] Erreur traitement batch: {e}")
                logger.error(f"[BURST] Traceback: {traceback.format_exc()}")

        background_tasks.add_task(run_batch)

        return ProcessBatchResponse(
            success=True,
            batch_id=orchestrator.state.batch_id,
            status="processing",
            documents_done=orchestrator.state.documents_done,
            documents_failed=orchestrator.state.documents_failed,
            message="Traitement lancé en arrière-plan. Utilisez /status pour suivre la progression."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur process_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/cancel",
    response_model=CancelResponse,
    summary="Annuler le batch en cours",
    description="""
    Annule le batch en cours et libère les ressources.

    **Actions:**
    - Désactive les providers Burst
    - Supprime le stack CloudFormation
    - Marque le batch comme annulé
    """
)
async def cancel_batch(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> CancelResponse:
    """Annule le batch en cours."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state:
            return CancelResponse(
                success=True,
                batch_id=None,
                message="Aucun batch actif à annuler."
            )

        batch_id = orchestrator.state.batch_id
        orchestrator.cancel()

        logger.info(f"[BURST] Batch {batch_id} annulé")

        return CancelResponse(
            success=True,
            batch_id=batch_id,
            message=f"Batch {batch_id} annulé. Ressources libérées."
        )

    except Exception as e:
        logger.error(f"Erreur cancel_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/events",
    response_model=EventsListResponse,
    summary="Timeline des événements",
    description="Retourne la timeline des événements du batch actuel."
)
async def get_events(
    limit: int = Query(100, ge=1, le=500, description="Nombre max d'événements"),
    offset: int = Query(0, ge=0, description="Offset pour pagination"),
    severity: Optional[str] = Query(None, description="Filtrer par sévérité (debug, info, warning, error)"),
    tenant_id: str = Depends(get_tenant_id),
) -> EventsListResponse:
    """Récupère la timeline des événements."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state:
            return EventsListResponse(
                batch_id=None,
                total=0,
                events=[]
            )

        events = orchestrator.state.events

        # Filtrer par sévérité si demandé
        if severity:
            events = [e for e in events if e.severity == severity]

        total = len(events)

        # Pagination (events les plus récents en premier)
        events = list(reversed(events))[offset:offset + limit]

        return EventsListResponse(
            batch_id=orchestrator.state.batch_id,
            total=total,
            events=[
                BurstEventResponse(
                    timestamp=e.timestamp,
                    event_type=e.event_type,
                    message=e.message,
                    severity=e.severity,
                    details=e.details
                )
                for e in events
            ]
        )

    except ImportError:
        return EventsListResponse(batch_id=None, total=0, events=[])
    except Exception as e:
        logger.error(f"Erreur get_events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/documents",
    response_model=DocumentsListResponse,
    summary="Statut des documents",
    description="Retourne le statut de tous les documents du batch."
)
async def get_documents(
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrer par statut (pending, processing, completed, failed)"),
    tenant_id: str = Depends(get_tenant_id),
) -> DocumentsListResponse:
    """Récupère le statut des documents du batch."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state:
            return DocumentsListResponse(
                batch_id=None,
                total=0,
                done=0,
                failed=0,
                pending=0,
                documents=[]
            )

        documents = orchestrator.state.documents

        # Filtrer par statut si demandé
        if status_filter:
            documents = [d for d in documents if d.status == status_filter]

        # Compter par statut
        all_docs = orchestrator.state.documents
        done = len([d for d in all_docs if d.status == "completed"])
        failed = len([d for d in all_docs if d.status == "failed"])
        pending = len([d for d in all_docs if d.status == "pending"])

        return DocumentsListResponse(
            batch_id=orchestrator.state.batch_id,
            total=len(all_docs),
            done=done,
            failed=failed,
            pending=pending,
            documents=[
                DocumentStatusResponse(
                    path=d.path,
                    name=d.name,
                    status=d.status,
                    started_at=d.started_at,
                    completed_at=d.completed_at,
                    error=d.error,
                    chunks_count=d.chunks_count
                )
                for d in documents
            ]
        )

    except ImportError:
        return DocumentsListResponse(batch_id=None, total=0, done=0, failed=0, pending=0, documents=[])
    except Exception as e:
        logger.error(f"Erreur get_documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/providers",
    response_model=ProvidersStatusResponse,
    summary="Statut des providers",
    description="Retourne le statut des providers LLM/Embeddings (local vs burst)."
)
async def get_providers_status(
    tenant_id: str = Depends(get_tenant_id),
) -> ProvidersStatusResponse:
    """Récupère le statut des providers."""
    try:
        from knowbase.ingestion.burst import get_burst_providers_status, check_burst_providers_health

        status = get_burst_providers_status()
        health = {}

        if status.get("burst_mode_active"):
            health = check_burst_providers_health()

        return ProvidersStatusResponse(
            burst_mode_active=status.get("burst_mode_active", False),
            llm_provider=status.get("llm_provider", "local"),
            llm_endpoint=status.get("llm_endpoint"),
            llm_model=status.get("llm_model"),
            embeddings_provider=status.get("embeddings_provider", "local"),
            embeddings_endpoint=status.get("embeddings_endpoint"),
            health=health
        )

    except ImportError:
        return ProvidersStatusResponse(
            burst_mode_active=False,
            llm_provider="local",
            embeddings_provider="local"
        )
    except Exception as e:
        logger.error(f"Erreur get_providers_status: {e}")
        return ProvidersStatusResponse(
            burst_mode_active=False,
            llm_provider="error",
            embeddings_provider="error",
            health={"error": str(e)}
        )


@router.get(
    "/instance-details",
    response_model=InstanceDetails,
    summary="Détails de l'instance EC2",
    description="""
    Récupère les détails enrichis de l'instance EC2 Spot en cours.

    Inclut:
    - Informations AWS (IP, type, AZ, AMI)
    - Prix Spot horaire estimé
    - Uptime depuis démarrage
    - Type et mémoire GPU
    - Statut des services vLLM et Embeddings
    """
)
async def get_instance_details(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> InstanceDetails:
    """Récupère les détails enrichis de l'instance."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator
        from datetime import datetime
        import httpx

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state or not orchestrator.state.instance_ip:
            return InstanceDetails()

        state = orchestrator.state

        # Calculer uptime
        uptime_seconds = None
        if state.started_at:
            try:
                start_dt = datetime.fromisoformat(state.started_at.replace("Z", "+00:00"))
                uptime_seconds = int((datetime.now(start_dt.tzinfo) - start_dt).total_seconds())
            except Exception:
                pass

        # GPU par type d'instance
        GPU_INFO = {
            "g6.2xlarge": ("NVIDIA L4", 24),
            "g6.xlarge": ("NVIDIA L4", 24),
            "g6e.xlarge": ("NVIDIA L4", 24),
            "g6e.2xlarge": ("NVIDIA L4", 24),
            "g5.xlarge": ("NVIDIA A10G", 24),
            "g5.2xlarge": ("NVIDIA A10G", 24),
            "g4dn.xlarge": ("NVIDIA T4", 16),
            "g4dn.2xlarge": ("NVIDIA T4", 16),
        }

        instance_type = state.instance_type or "g6.2xlarge"
        gpu_type, gpu_memory = GPU_INFO.get(instance_type, ("Unknown", 0))

        # Récupérer le prix Spot RÉEL depuis AWS
        spot_price = None
        availability_zone = getattr(state, 'availability_zone', None)

        try:
            import boto3
            ec2 = boto3.client('ec2', region_name=os.getenv('AWS_DEFAULT_REGION', 'eu-central-1'))

            # Récupérer le prix Spot actuel pour ce type d'instance
            price_response = ec2.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=['Linux/UNIX'],
                MaxResults=1,
                AvailabilityZone=availability_zone if availability_zone else None
            )

            if price_response.get('SpotPriceHistory'):
                spot_price = float(price_response['SpotPriceHistory'][0]['SpotPrice'])
                # Mettre à jour la zone si pas définie
                if not availability_zone:
                    availability_zone = price_response['SpotPriceHistory'][0].get('AvailabilityZone')
        except Exception as e:
            logger.warning(f"Impossible de récupérer le prix Spot réel: {e}")
            # Fallback sur estimation
            SPOT_PRICES_FALLBACK = {
                "g6.2xlarge": 0.65, "g6.xlarge": 0.35, "g6e.xlarge": 0.40,
                "g5.xlarge": 0.45, "g5.2xlarge": 0.75,
                "g4dn.xlarge": 0.25, "g4dn.2xlarge": 0.40,
            }
            spot_price = SPOT_PRICES_FALLBACK.get(instance_type, 0.50)

        # Vérifier statut des services
        vllm_status = "unknown"
        embeddings_status = "unknown"

        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check vLLM
            if state.vllm_url:
                try:
                    resp = await client.get(f"{state.vllm_url}/v1/models")
                    vllm_status = "healthy" if resp.status_code == 200 else "unhealthy"
                except Exception:
                    vllm_status = "unhealthy"

            # Check Embeddings
            if state.embeddings_url:
                try:
                    resp = await client.get(f"{state.embeddings_url}/health")
                    embeddings_status = "healthy" if resp.status_code == 200 else "unhealthy"
                except Exception:
                    embeddings_status = "unhealthy"

        return InstanceDetails(
            instance_id=getattr(state, 'instance_id', None),
            public_ip=state.instance_ip,
            instance_type=instance_type,
            availability_zone=availability_zone or getattr(state, 'availability_zone', "eu-central-1a"),
            spot_price_hourly=spot_price,
            uptime_seconds=uptime_seconds,
            gpu_type=gpu_type,
            gpu_memory_gb=gpu_memory,
            vllm_status=vllm_status,
            embeddings_status=embeddings_status,
            ami_id=getattr(state, 'ami_id', None),
            launch_time=state.started_at,
        )

    except ImportError:
        return InstanceDetails()
    except Exception as e:
        logger.error(f"Erreur get_instance_details: {e}")
        return InstanceDetails()


__all__ = ["router"]
