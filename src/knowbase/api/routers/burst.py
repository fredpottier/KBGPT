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
from knowbase.common.logging import setup_logging, LazyFlushingFileHandler
from knowbase.config.settings import get_settings
import logging

settings = get_settings()
logger = setup_logging(settings.logs_dir, "burst_router.log")


def _setup_burst_module_logging():
    """
    Configure le logging pour tous les modules burst (orchestrator, importer, etc.)
    afin que leurs logs aillent dans le même fichier burst_router.log.
    """
    # Modules burst à capturer
    burst_modules = [
        # Modules burst core
        "knowbase.ingestion.burst",
        "knowbase.ingestion.burst.orchestrator",
        "knowbase.ingestion.burst.artifact_importer",
        "knowbase.ingestion.burst.artifact_exporter",
        "knowbase.ingestion.burst.provider_switch",
        "knowbase.ingestion.burst.resilient_client",
        # Modules OSMOSE appelés pendant le processing burst
        "knowbase.ingestion.osmose_agentique",
        "knowbase.ingestion.osmose_integration",
        "knowbase.ingestion.osmose_persistence",
        "knowbase.ingestion.osmose_enrichment",
        "knowbase.ingestion.osmose_utils",
        "knowbase.ingestion.extraction_cache",
        "knowbase.ingestion.text_chunker",
        "knowbase.ingestion.hybrid_anchor_chunker",
        "knowbase.ingestion.enrichment_tracker",
        # Modules extraction V2 (Docling, etc.)
        "knowbase.extraction_v2",
        "knowbase.extraction_v2.extractors.docling_extractor",
        "knowbase.extraction_v2.adapters.docling_adapter",
    ]

    log_file = settings.logs_dir / "burst_router.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s]: %(message)s")

    # Créer un handler partagé
    file_handler = LazyFlushingFileHandler(str(log_file), mode='a', encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    for module_name in burst_modules:
        module_logger = logging.getLogger(module_name)
        module_logger.setLevel(logging.DEBUG)
        module_logger.propagate = False

        # Éviter d'ajouter plusieurs fois le même handler
        has_file_handler = any(
            isinstance(h, (logging.FileHandler, LazyFlushingFileHandler))
            for h in module_logger.handlers
        )
        if not has_file_handler:
            module_logger.addHandler(file_handler)

    logger.info("[BURST] Module logging configured for all burst components")


# Configurer le logging des modules burst au démarrage
_setup_burst_module_logging()

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


class ResumableBatchInfo(BaseModel):
    """Info sur un batch pouvant être repris."""
    batch_id: str
    saved_at: str
    pending_documents: int
    completed_documents: int


class PrepareBatchResponse(BaseModel):
    """Réponse préparation batch."""
    success: bool
    batch_id: str
    documents_count: int
    documents: List[Dict]
    message: str
    resumable_batch: Optional[ResumableBatchInfo] = None


class StartInfraRequest(BaseModel):
    """Requête pour démarrer l'infrastructure."""
    force: bool = Field(
        False,
        description="Force le redémarrage même si une instance existe"
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


class CancelRequest(BaseModel):
    """Requête d'annulation avec options."""
    terminate_infrastructure: bool = Field(
        True,
        description="Si True, détruit l'infrastructure EC2. Si False, garde l'instance pour relancer un traitement."
    )


class CancelResponse(BaseModel):
    """Réponse annulation."""
    success: bool
    batch_id: Optional[str] = None
    infrastructure_terminated: bool = False
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


class AttachInstanceRequest(BaseModel):
    """Requête pour attacher une instance EC2 existante (lancée manuellement)."""
    instance_ip: str = Field(..., description="IP publique de l'instance EC2")
    instance_type: str = Field("g6.2xlarge", description="Type d'instance EC2")
    instance_id: Optional[str] = Field(None, description="ID de l'instance (optionnel)")
    vllm_port: int = Field(8000, description="Port vLLM")
    embeddings_port: int = Field(8001, description="Port embeddings")


class AttachInstanceResponse(BaseModel):
    """Réponse d'attachement d'instance."""
    success: bool
    batch_id: Optional[str] = None
    instance_ip: Optional[str] = None
    instance_type: Optional[str] = None
    vllm_url: Optional[str] = None
    embeddings_url: Optional[str] = None
    vllm_healthy: bool = False
    embeddings_healthy: bool = False
    providers_activated: bool = False
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
    "/attach-instance",
    response_model=AttachInstanceResponse,
    summary="Attacher une instance EC2 existante",
    description="""
    Attache une instance EC2 existante (lancée manuellement via AWS CLI ou console)
    à l'orchestrateur Burst.

    **Cas d'usage:**
    - Instance lancée manuellement pour tests
    - Instance créée sans CloudFormation
    - Récupération après perte de l'état orchestrateur

    **Comportement:**
    1. Vérifie que vLLM et Embeddings sont accessibles
    2. Active les providers Burst (routing LLM vers EC2)
    3. Crée un état standalone dans l'orchestrateur

    **Note:** Après attachement, utilisez /prepare puis /process pour lancer un batch.
    """
)
async def attach_instance(
    request: AttachInstanceRequest,
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> AttachInstanceResponse:
    """Attache une instance EC2 existante à l'orchestrateur."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, BurstStatus
        from knowbase.ingestion.burst.types import BurstState, BurstConfig
        from knowbase.ingestion.burst.provider_switch import (
            activate_burst_providers,
            check_burst_providers_health
        )
        from datetime import datetime, timezone
        import httpx

        orchestrator = get_burst_orchestrator()

        # Construire les URLs
        vllm_url = f"http://{request.instance_ip}:{request.vllm_port}"
        embeddings_url = f"http://{request.instance_ip}:{request.embeddings_port}"

        logger.info(f"[BURST] Attaching instance {request.instance_ip} (vLLM: {vllm_url}, Embeddings: {embeddings_url})")

        # Vérifier la santé des services
        vllm_healthy = False
        embeddings_healthy = False

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check vLLM
            try:
                resp = await client.get(f"{vllm_url}/v1/models")
                vllm_healthy = resp.status_code == 200
                logger.info(f"[BURST] vLLM health check: {vllm_healthy} (status: {resp.status_code})")
            except Exception as e:
                logger.warning(f"[BURST] vLLM health check failed: {e}")

            # Check Embeddings
            try:
                resp = await client.get(f"{embeddings_url}/health")
                embeddings_healthy = resp.status_code == 200
                logger.info(f"[BURST] Embeddings health check: {embeddings_healthy} (status: {resp.status_code})")
            except Exception as e:
                logger.warning(f"[BURST] Embeddings health check failed: {e}")

        if not vllm_healthy and not embeddings_healthy:
            return AttachInstanceResponse(
                success=False,
                instance_ip=request.instance_ip,
                vllm_url=vllm_url,
                embeddings_url=embeddings_url,
                vllm_healthy=vllm_healthy,
                embeddings_healthy=embeddings_healthy,
                status="unhealthy",
                message=f"Les services ne sont pas accessibles sur {request.instance_ip}. Vérifiez que l'instance est démarrée et les ports ouverts."
            )

        # Créer un état standalone avec l'instance attachée
        config = BurstConfig.from_env()
        standalone_id = f"attached-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        orchestrator.state = BurstState(
            batch_id=standalone_id,
            status=BurstStatus.READY,
            documents=[],
            total_documents=0,
            instance_id=request.instance_id,
            instance_ip=request.instance_ip,
            instance_type=request.instance_type,
            vllm_url=vllm_url,
            embeddings_url=embeddings_url,
            created_at=datetime.now(timezone.utc).isoformat(),
            config=config.to_dict()
        )

        # Activer les providers Burst
        providers_activated = False
        try:
            result = activate_burst_providers(
                vllm_url=vllm_url,
                embeddings_url=embeddings_url,
                vllm_model=config.vllm_model
            )
            providers_activated = result.get('llm_router', False) or result.get('embedding_manager', False)
            logger.info(f"[BURST] Providers activation result: {result}")
        except Exception as e:
            logger.error(f"[BURST] Failed to activate providers: {e}")

        orchestrator._add_event(
            "instance_attached",
            f"Instance {request.instance_ip} ({request.instance_type}) attachée manuellement",
            details={
                "instance_id": request.instance_id,
                "vllm_healthy": vllm_healthy,
                "embeddings_healthy": embeddings_healthy,
                "providers_activated": providers_activated
            }
        )

        logger.info(f"[BURST] ✅ Instance attached: {request.instance_ip} (standalone_id: {standalone_id})")

        return AttachInstanceResponse(
            success=True,
            batch_id=standalone_id,
            instance_ip=request.instance_ip,
            instance_type=request.instance_type,
            vllm_url=vllm_url,
            embeddings_url=embeddings_url,
            vllm_healthy=vllm_healthy,
            embeddings_healthy=embeddings_healthy,
            providers_activated=providers_activated,
            status="ready",
            message=f"Instance {request.instance_ip} attachée. Providers {'activés' if providers_activated else 'non activés'}. Utilisez /prepare puis /process pour lancer un batch."
        )

    except Exception as e:
        logger.error(f"Erreur attach_instance: {e}")
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
        import json

        config = BurstConfig.from_env()
        orchestrator = get_burst_orchestrator()

        # Sauvegarder l'instance si elle est déjà attachée (pour la préserver après prepare)
        # MAIS PAS si le batch précédent était cancelled/failed (instance détruite)
        existing_instance_ip = None
        existing_instance_type = None
        existing_instance_id = None
        existing_vllm_url = None
        existing_embeddings_url = None
        from knowbase.ingestion.burst.types import BurstStatus
        terminal_statuses = [BurstStatus.CANCELLED, BurstStatus.FAILED, BurstStatus.COMPLETED]
        if orchestrator.state is not None and orchestrator.state.status not in terminal_statuses:
            existing_instance_ip = orchestrator.state.instance_ip
            existing_instance_type = orchestrator.state.instance_type
            existing_instance_id = getattr(orchestrator.state, 'instance_id', None)
            existing_vllm_url = orchestrator.state.vllm_url
            existing_embeddings_url = orchestrator.state.embeddings_url

        # Vérifier s'il y a un batch interrompu à reprendre
        resumable_info = None
        saved_state = orchestrator.load_saved_state()
        if saved_state:
            docs = saved_state.get("documents", [])
            completed = sum(1 for d in docs if d.get("status") in ("completed", "done"))
            pending = len(docs) - completed

            if pending > 0:
                resumable_info = ResumableBatchInfo(
                    batch_id=saved_state.get("batch_id", "unknown"),
                    saved_at=saved_state.get("saved_at", ""),
                    pending_documents=pending,
                    completed_documents=completed
                )
                logger.info(f"[BURST] Found resumable batch: {resumable_info.batch_id} with {pending} pending docs")

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

        # Restaurer l'instance si elle était attachée avant
        if existing_instance_ip and orchestrator.state:
            from knowbase.ingestion.burst.types import BurstStatus
            orchestrator.state.instance_ip = existing_instance_ip
            orchestrator.state.instance_type = existing_instance_type
            orchestrator.state.instance_id = existing_instance_id
            orchestrator.state.vllm_url = existing_vllm_url
            orchestrator.state.embeddings_url = existing_embeddings_url
            # Mettre le statut à READY si l'instance est déjà prête
            orchestrator.state.status = BurstStatus.READY
            logger.info(f"[BURST] Instance préservée: {existing_instance_ip} ({existing_instance_type})")

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

        # Message avec info sur batch resumable
        message = f"Batch préparé avec {len(documents)} documents. Utilisez /start pour lancer l'infrastructure."
        if resumable_info:
            message += f" ⚠️ Un batch interrompu ({resumable_info.batch_id}) peut être repris ({resumable_info.pending_documents} docs en attente)."

        return PrepareBatchResponse(
            success=True,
            batch_id=batch_id,
            documents_count=len(documents),
            documents=documents,
            message=message,
            resumable_batch=resumable_info
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

        # Verification explicite que le burst mode est actif
        from knowbase.common.llm_router import get_llm_router
        llm_router = get_llm_router()
        burst_check = llm_router.get_burst_status()
        logger.info(
            f"[BURST] Provider verification after start: "
            f"burst_mode={burst_check.get('burst_mode')}, "
            f"endpoint={burst_check.get('burst_endpoint')}, "
            f"model={burst_check.get('burst_model')}, "
            f"client_ready={burst_check.get('client_ready')}"
        )

        return StartInfraResponse(
            success=True,
            batch_id=orchestrator.state.batch_id,
            status=orchestrator.state.status.value,
            instance_ip=orchestrator.state.instance_ip,
            vllm_url=orchestrator.state.vllm_url,
            embeddings_url=orchestrator.state.embeddings_url,
            message="Infrastructure prête. Providers basculés vers EC2 Spot (vLLM)."
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
        from knowbase.ingestion.burst.types import BurstConfig

        # Configuration parallélisme depuis BurstConfig (défaut: 2 documents en parallèle)
        burst_config = BurstConfig.from_env()
        MAX_CONCURRENT_DOCS = burst_config.max_concurrent_docs

        async def run_batch():
            """Traite les documents du batch de manière async avec parallélisme."""
            import traceback
            from knowbase.ingestion.queue.jobs_v2 import ingest_document_v2_job
            from knowbase.common.llm_router import get_llm_router

            # Verification du burst mode au debut du batch
            llm_router = get_llm_router()
            burst_check = llm_router.get_burst_status()
            logger.info(
                f"[BURST:PROCESS] Batch starting - burst_mode={burst_check.get('burst_mode')}, "
                f"endpoint={burst_check.get('burst_endpoint')}, client_ready={burst_check.get('client_ready')}"
            )

            if not burst_check.get('burst_mode'):
                logger.warning("[BURST:PROCESS] ⚠️ BURST MODE NOT ACTIVE - LLM calls will go to OpenAI/Anthropic!")

            # Lock pour les mises à jour d'état partagé
            state_lock = asyncio.Lock()
            # Semaphore pour limiter la concurrence
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOCS)

            async def process_single_doc(doc_status):
                """Traite un document avec contrôle de concurrence."""
                async with semaphore:
                    doc_path = Path(doc_status.path)

                    async with state_lock:
                        doc_status.status = "processing"
                        doc_status.started_at = datetime.now(timezone.utc).isoformat()

                    try:
                        suffix = doc_path.suffix.lower()
                        logger.info(f"[BURST] Processing: {doc_path.name} (concurrency: {MAX_CONCURRENT_DOCS})")

                        # Pipeline V2 unifié (Docling + Vision Gating V4 + OSMOSE)
                        # Supporte: .pdf, .pptx, .docx, .xlsx
                        if suffix in [".pdf", ".pptx", ".docx", ".xlsx"]:
                            result = await asyncio.to_thread(
                                lambda p=str(doc_path): ingest_document_v2_job(file_path=p)
                            )
                        else:
                            raise ValueError(f"Format non supporté: {suffix}")

                        async with state_lock:
                            doc_status.status = "completed"
                            doc_status.completed_at = datetime.now(timezone.utc).isoformat()
                            # Récupérer le nombre de ProtoConcepts extraits depuis le résultat V2
                            # Note: Depuis ADR_UNIFIED_CORPUS_PROMOTION, canonical_concepts est 0 en Pass 1
                            # Les CanonicalConcepts sont créés en Pass 2.0 (CORPUS_PROMOTION)
                            if isinstance(result, dict):
                                osmose = result.get("osmose", {})
                                doc_status.chunks_count = osmose.get("concepts_extracted", 0)
                            else:
                                doc_status.chunks_count = 0
                            orchestrator.state.documents_done += 1

                        logger.info(f"[BURST] ✅ Completed: {doc_path.name} ({doc_status.chunks_count} proto-concepts)")

                    except Exception as e:
                        async with state_lock:
                            doc_status.status = "failed"
                            doc_status.error = str(e)
                            doc_status.completed_at = datetime.now(timezone.utc).isoformat()
                            orchestrator.state.documents_failed += 1

                        logger.error(f"[BURST] ❌ Failed: {doc_path.name} - {e}")
                        logger.error(f"[BURST] Traceback: {traceback.format_exc()}")

            try:
                orchestrator.state.status = BurstStatus.PROCESSING
                orchestrator.state.started_at = datetime.now(timezone.utc).isoformat()
                orchestrator._add_event(
                    "processing_started",
                    f"Traitement du batch démarré (parallélisme: {MAX_CONCURRENT_DOCS} docs)"
                )

                # Copier la liste pour éviter modification pendant itération
                docs_to_process = [d for d in orchestrator.state.documents if d.status == "pending"]
                logger.info(f"[BURST] Traitement de {len(docs_to_process)} documents (max {MAX_CONCURRENT_DOCS} en parallèle)...")

                # Lancer tous les traitements en parallèle (limités par le semaphore)
                tasks = [process_single_doc(doc) for doc in docs_to_process]
                await asyncio.gather(*tasks, return_exceptions=True)

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
    Annule le batch en cours avec options.

    **Options:**
    - `terminate_infrastructure: true` (défaut) - Arrête tout et détruit l'instance EC2
    - `terminate_infrastructure: false` - Arrête le traitement mais garde l'instance EC2 prête

    **Cas d'usage "garder l'infrastructure":**
    - Arrêter un import problématique
    - Relancer avec d'autres documents
    - Économiser le temps de boot (~5-10 min)
    """
)
async def cancel_batch(
    request: CancelRequest = CancelRequest(),
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
                infrastructure_terminated=False,
                message="Aucun batch actif à annuler."
            )

        batch_id = orchestrator.state.batch_id

        if request.terminate_infrastructure:
            # Annulation complète (comportement actuel)
            orchestrator.cancel()
            logger.info(f"[BURST] Batch {batch_id} annulé avec destruction infrastructure")
            return CancelResponse(
                success=True,
                batch_id=batch_id,
                infrastructure_terminated=True,
                message=f"Batch {batch_id} annulé. Infrastructure EC2 détruite."
            )
        else:
            # Annulation du traitement uniquement, garde l'infrastructure
            orchestrator.cancel_processing_only()
            logger.info(f"[BURST] Batch {batch_id} annulé (infrastructure conservée)")
            return CancelResponse(
                success=True,
                batch_id=batch_id,
                infrastructure_terminated=False,
                message=f"Traitement annulé. Infrastructure EC2 conservée - prête pour nouveau batch."
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

        # Variable pour stocker le vrai launch_time AWS
        aws_launch_time = getattr(state, 'instance_launch_time', None)

        try:
            import boto3
            ec2 = boto3.client('ec2', region_name=os.getenv('AWS_DEFAULT_REGION', 'eu-central-1'))

            # Récupérer le launch_time réel depuis AWS si pas dans le state
            instance_id = getattr(state, 'instance_id', None)
            if not aws_launch_time and instance_id:
                try:
                    instance_response = ec2.describe_instances(InstanceIds=[instance_id])
                    reservations = instance_response.get('Reservations', [])
                    if reservations and reservations[0].get('Instances'):
                        instance_data = reservations[0]['Instances'][0]
                        launch_time_dt = instance_data.get('LaunchTime')
                        if launch_time_dt:
                            aws_launch_time = launch_time_dt.isoformat()
                            # Mettre à jour le state pour les prochains appels
                            if hasattr(state, 'instance_launch_time'):
                                state.instance_launch_time = aws_launch_time
                            logger.info(f"[BURST] Retrieved EC2 launch time from AWS: {aws_launch_time}")
                except Exception as e:
                    logger.warning(f"Impossible de récupérer le launch_time AWS: {e}")

            # Récupérer le prix Spot actuel pour ce type d'instance
            # Ne pas inclure AvailabilityZone si None (l'API n'accepte pas None)
            spot_params = {
                'InstanceTypes': [instance_type],
                'ProductDescriptions': ['Linux/UNIX'],
                'MaxResults': 1,
            }
            if availability_zone:
                spot_params['AvailabilityZone'] = availability_zone

            price_response = ec2.describe_spot_price_history(**spot_params)

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
            launch_time=aws_launch_time or state.started_at,  # Vrai AWS launch time
        )

    except ImportError:
        return InstanceDetails()
    except Exception as e:
        logger.error(f"Erreur get_instance_details: {e}")
        return InstanceDetails()


# ============================================================================
# Spot Interruption Warning Endpoint
# ============================================================================

class SpotWarningRequest(BaseModel):
    """Notification d'interruption Spot depuis EC2."""
    instance_id: str
    action: Optional[dict] = None
    instance_type: Optional[str] = None
    timestamp: Optional[str] = None


class SpotWarningResponse(BaseModel):
    """Réponse à la notification d'interruption."""
    received: bool
    message: str
    graceful_shutdown_initiated: bool = False


class SavedStateInfo(BaseModel):
    """Informations sur un état sauvegardé."""
    batch_id: str
    saved_at: str
    status: str
    total_documents: int
    completed: int
    pending: int
    failed: int
    file_path: str


class SavedStatesResponse(BaseModel):
    """Liste des états sauvegardés."""
    states: List[SavedStateInfo]
    has_resumable: bool


# ============================================================================
# Schemas Standalone Mode
# ============================================================================

class StartStandaloneRequest(BaseModel):
    """Requête pour démarrer EC2 sans batch."""
    hibernate_on_stop: bool = Field(
        True,
        description="Si True, garde le fleet avec capacity=0 pour redémarrage rapide"
    )


class StartStandaloneResponse(BaseModel):
    """Réponse démarrage standalone."""
    success: bool
    standalone_id: str
    status: str
    instance_ip: Optional[str] = None
    instance_type: Optional[str] = None
    vllm_url: Optional[str] = None
    embeddings_url: Optional[str] = None
    message: str


class StopStandaloneRequest(BaseModel):
    """Requête pour arrêter le mode standalone."""
    terminate_infrastructure: bool = Field(
        False,
        description="Si True, détruit complètement la stack. Si False (défaut), scale le fleet à 0 pour redémarrage rapide."
    )


class StopStandaloneResponse(BaseModel):
    """Réponse arrêt standalone."""
    success: bool
    infrastructure_terminated: bool
    fleet_hibernated: bool
    message: str


@router.post(
    "/spot-warning",
    response_model=SpotWarningResponse,
    summary="Notification d'interruption Spot",
    description="Reçoit la notification 2 minutes avant interruption Spot AWS. Déclenche une sauvegarde gracieuse.",
    tags=["burst"]
)
async def receive_spot_warning(
    warning: SpotWarningRequest,
) -> SpotWarningResponse:
    """
    Endpoint appelé par le spot-monitor.sh sur l'instance EC2.
    Déclenche une sauvegarde gracieuse de l'état du traitement.

    Note: Pas d'authentification requise car appelé depuis EC2.
    """
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, EventSeverity

        logger.warning(
            f"[BURST] ⚠️ SPOT INTERRUPTION WARNING received! "
            f"Instance: {warning.instance_id}, Time: {warning.timestamp}"
        )

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state:
            logger.warning("[BURST] Spot warning received but no active batch")
            return SpotWarningResponse(
                received=True,
                message="No active batch to save",
                graceful_shutdown_initiated=False
            )

        # Ajouter événement
        orchestrator._add_event(
            "spot_warning_received",
            f"⚠️ Interruption Spot dans ~2 min! Instance {warning.instance_id}",
            EventSeverity.WARNING,
            details={
                "instance_id": warning.instance_id,
                "instance_type": warning.instance_type,
                "action": warning.action,
                "timestamp": warning.timestamp
            }
        )

        # Déclencher sauvegarde gracieuse
        try:
            orchestrator.initiate_graceful_shutdown()
            graceful = True
            message = "Graceful shutdown initiated - saving state"
        except Exception as e:
            logger.error(f"[BURST] Failed to initiate graceful shutdown: {e}")
            graceful = False
            message = f"Warning received but graceful shutdown failed: {e}"

        return SpotWarningResponse(
            received=True,
            message=message,
            graceful_shutdown_initiated=graceful
        )

    except Exception as e:
        logger.error(f"[BURST] Error handling spot warning: {e}")
        return SpotWarningResponse(
            received=True,
            message=f"Error: {e}",
            graceful_shutdown_initiated=False
        )


@router.get(
    "/saved-states",
    response_model=SavedStatesResponse,
    summary="États sauvegardés",
    description="Liste les états de batches interrompus pouvant être repris.",
    tags=["burst"]
)
async def list_saved_states(
    admin: dict = Depends(require_admin),
) -> SavedStatesResponse:
    """Liste les états sauvegardés pour reprise."""
    try:
        from pathlib import Path
        import json

        state_dir = Path("/app/data/burst_state") if Path("/app").exists() else Path("data/burst_state")

        states = []
        if state_dir.exists():
            for state_file in state_dir.glob("burst_state_*.json"):
                try:
                    with open(state_file) as f:
                        data = json.load(f)

                    docs = data.get("documents", [])
                    completed = sum(1 for d in docs if d.get("status") in ("completed", "done"))
                    failed = sum(1 for d in docs if d.get("status") == "failed")
                    pending = len(docs) - completed - failed

                    states.append(SavedStateInfo(
                        batch_id=data.get("batch_id", "unknown"),
                        saved_at=data.get("saved_at", ""),
                        status=data.get("status", "unknown"),
                        total_documents=len(docs),
                        completed=completed,
                        pending=pending,
                        failed=failed,
                        file_path=str(state_file)
                    ))
                except Exception as e:
                    logger.warning(f"Error reading state file {state_file}: {e}")

        # Trier par date de sauvegarde (plus récent en premier)
        states.sort(key=lambda s: s.saved_at, reverse=True)

        return SavedStatesResponse(
            states=states,
            has_resumable=any(s.pending > 0 for s in states)
        )

    except Exception as e:
        logger.error(f"Error listing saved states: {e}")
        return SavedStatesResponse(states=[], has_resumable=False)


@router.delete(
    "/saved-states/{batch_id}",
    summary="Supprimer un état sauvegardé",
    description="Supprime l'état sauvegardé d'un batch (après reprise réussie ou abandon).",
    tags=["burst"]
)
async def delete_saved_state(
    batch_id: str,
    admin: dict = Depends(require_admin),
) -> dict:
    """Supprime un état sauvegardé."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()
        orchestrator.clear_saved_state(batch_id)

        return {"success": True, "message": f"État {batch_id} supprimé"}

    except Exception as e:
        logger.error(f"Error deleting saved state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/resume",
    response_model=PrepareBatchResponse,
    summary="Reprendre un batch interrompu",
    description="Reprend un batch interrompu en chargeant les documents non traités depuis l'état sauvegardé.",
    tags=["burst"]
)
async def resume_batch(
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> PrepareBatchResponse:
    """Reprend un batch interrompu."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator

        orchestrator = get_burst_orchestrator()

        # Charger l'état sauvegardé
        saved_state = orchestrator.load_saved_state()
        if not saved_state:
            return PrepareBatchResponse(
                success=False,
                batch_id="",
                documents_count=0,
                documents=[],
                message="Aucun batch interrompu à reprendre."
            )

        # Extraire les documents non complétés
        docs = saved_state.get("documents", [])
        pending_docs = [
            d for d in docs
            if d.get("status") not in ("completed", "done")
        ]

        if not pending_docs:
            # Tous les docs étaient terminés, nettoyer l'état
            orchestrator.clear_saved_state(saved_state.get("batch_id"))
            return PrepareBatchResponse(
                success=False,
                batch_id=saved_state.get("batch_id", ""),
                documents_count=0,
                documents=[],
                message="Tous les documents du batch interrompu ont été traités. État nettoyé."
            )

        # Préparer le batch avec uniquement les documents en attente
        document_paths = [Path(d["path"]) for d in pending_docs if Path(d["path"]).exists()]

        if not document_paths:
            return PrepareBatchResponse(
                success=False,
                batch_id=saved_state.get("batch_id", ""),
                documents_count=0,
                documents=[],
                message="Les fichiers du batch interrompu ne sont plus disponibles."
            )

        # Utiliser le même batch_id pour la continuité
        original_batch_id = saved_state.get("batch_id", "")
        batch_id = orchestrator.prepare_batch(
            document_paths=document_paths,
            batch_id=f"{original_batch_id}-resume"
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

        # Supprimer l'ancien état sauvegardé
        orchestrator.clear_saved_state(original_batch_id)

        logger.info(f"[BURST] Resumed batch {batch_id} with {len(documents)} pending documents")

        return PrepareBatchResponse(
            success=True,
            batch_id=batch_id,
            documents_count=len(documents),
            documents=documents,
            message=f"Batch repris avec {len(documents)} documents en attente (sur {len(docs)} originaux). "
                    f"Utilisez /start pour relancer l'infrastructure."
        )

    except Exception as e:
        logger.error(f"Error resuming batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Standalone EC2 Mode - On-demand vLLM (sans batch)
# ============================================================================

@router.post(
    "/start-standalone",
    response_model=StartStandaloneResponse,
    summary="Démarrer EC2 vLLM sans batch",
    description="""
    Démarre l'infrastructure EC2 Spot en mode standalone (sans batch de documents).

    **Cas d'usage:**
    - Enrichissement KG (Pass 2/3) avec LLM local
    - Entity Resolution avec LLM Merge Gate
    - Tests et expérimentations LLM

    **Comportement:**
    - Lance EC2 Spot avec vLLM + TEI
    - Active le mode Burst sur LLMRouter (tous les appels LLM vont vers vLLM)
    - Les appels Vision restent sur GPT-4o Vision
    - Ne crée pas de batch de documents

    **Note:** Pour un batch d'ingestion, utilisez /prepare puis /start.
    """,
    tags=["burst"]
)
async def start_standalone(
    request: StartStandaloneRequest = StartStandaloneRequest(),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> StartStandaloneResponse:
    """Démarre EC2 en mode standalone (vLLM on-demand sans batch)."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, BurstStatus
        from knowbase.ingestion.burst.types import BurstState, BurstConfig
        from datetime import datetime, timezone
        import asyncio

        orchestrator = get_burst_orchestrator()

        # Vérifier si déjà actif
        if orchestrator.state is not None:
            if orchestrator.state.status in [BurstStatus.READY, BurstStatus.PROCESSING]:
                return StartStandaloneResponse(
                    success=True,
                    standalone_id=orchestrator.state.batch_id,
                    status=orchestrator.state.status.value,
                    instance_ip=orchestrator.state.instance_ip,
                    instance_type=orchestrator.state.instance_type,
                    vllm_url=orchestrator.state.vllm_url,
                    embeddings_url=orchestrator.state.embeddings_url,
                    message="Infrastructure déjà active. Utilisez /stop-standalone pour arrêter."
                )

        # Créer un état minimal "standalone" (sans documents)
        standalone_id = f"standalone-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        config = BurstConfig.from_env()

        orchestrator.state = BurstState(
            batch_id=standalone_id,
            status=BurstStatus.PREPARING,
            documents=[],  # Pas de documents en mode standalone
            total_documents=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            config=config.to_dict()
        )

        orchestrator._add_event(
            "standalone_starting",
            "Démarrage mode standalone (vLLM on-demand)",
            details={"hibernate_on_stop": request.hibernate_on_stop}
        )

        logger.info(f"[BURST] Starting standalone mode: {standalone_id}")

        # Démarrer l'infrastructure (sync call wrapped)
        success = await asyncio.to_thread(orchestrator.start_infrastructure)

        if not success:
            return StartStandaloneResponse(
                success=False,
                standalone_id=standalone_id,
                status=orchestrator.state.status.value,
                message="Échec du démarrage de l'infrastructure EC2."
            )

        logger.info(
            f"[BURST] ✅ Standalone mode ready: {standalone_id} @ {orchestrator.state.instance_ip}"
        )

        return StartStandaloneResponse(
            success=True,
            standalone_id=standalone_id,
            status=orchestrator.state.status.value,
            instance_ip=orchestrator.state.instance_ip,
            instance_type=orchestrator.state.instance_type,
            vllm_url=orchestrator.state.vllm_url,
            embeddings_url=orchestrator.state.embeddings_url,
            message="Mode standalone actif. Tous les appels LLM (sauf Vision) utilisent vLLM sur EC2."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur start_standalone: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/stop-standalone",
    response_model=StopStandaloneResponse,
    summary="Arrêter EC2 mode standalone",
    description="""
    Arrête le mode standalone et désactive le routing vers vLLM.

    **Options:**
    - `terminate_infrastructure: false` (défaut) - Scale le fleet à 0 (hibernate)
      → Redémarrage rapide (~1-2 min vs ~5-7 min)
      → L'instance est détruite mais la stack reste
    - `terminate_infrastructure: true` - Détruit complètement la stack CloudFormation

    **Comportement:**
    - Désactive le mode Burst sur LLMRouter
    - Les appels LLM retournent vers OpenAI/Anthropic
    - L'infrastructure est stoppée/hibernée selon l'option
    """,
    tags=["burst"]
)
async def stop_standalone(
    request: StopStandaloneRequest = StopStandaloneRequest(),
    admin: dict = Depends(require_admin),
    tenant_id: str = Depends(get_tenant_id),
) -> StopStandaloneResponse:
    """Arrête le mode standalone EC2."""
    try:
        from knowbase.ingestion.burst import get_burst_orchestrator, deactivate_burst_providers
        from knowbase.ingestion.burst.types import BurstStatus
        import boto3

        orchestrator = get_burst_orchestrator()

        if not orchestrator.state:
            # Vérifier quand même si des providers sont actifs
            deactivate_burst_providers()
            return StopStandaloneResponse(
                success=True,
                infrastructure_terminated=False,
                fleet_hibernated=False,
                message="Aucune infrastructure active. Providers désactivés par précaution."
            )

        # Désactiver les providers d'abord
        deactivate_result = deactivate_burst_providers()
        logger.info(f"[BURST] Providers deactivated: {deactivate_result}")

        if request.terminate_infrastructure:
            # Destruction complète via cancel()
            orchestrator.cancel()
            logger.info("[BURST] Infrastructure completely terminated")
            return StopStandaloneResponse(
                success=True,
                infrastructure_terminated=True,
                fleet_hibernated=False,
                message="Mode standalone arrêté. Infrastructure EC2 complètement détruite."
            )
        else:
            # Hibernate: scale fleet à 0 (garde la stack pour redémarrage rapide)
            fleet_id = orchestrator.state.spot_fleet_id
            if fleet_id:
                try:
                    ec2 = boto3.client(
                        'ec2',
                        region_name=os.getenv('AWS_DEFAULT_REGION', 'eu-central-1')
                    )
                    ec2.modify_spot_fleet_request(
                        SpotFleetRequestId=fleet_id,
                        TargetCapacity=0
                    )
                    logger.info(f"[BURST] Fleet {fleet_id} scaled to 0 (hibernated)")

                    # Mettre à jour l'état
                    orchestrator.state.status = BurstStatus.IDLE
                    orchestrator.state.instance_ip = None
                    orchestrator.state.instance_id = None
                    orchestrator._add_event(
                        "standalone_hibernated",
                        f"Fleet {fleet_id} mis en veille (capacity=0)"
                    )

                    return StopStandaloneResponse(
                        success=True,
                        infrastructure_terminated=False,
                        fleet_hibernated=True,
                        message="Mode standalone arrêté. Fleet en veille (redémarrage rapide possible)."
                    )

                except Exception as e:
                    logger.warning(f"[BURST] Failed to hibernate fleet: {e}")
                    # Fallback: cancel complet
                    orchestrator.cancel()
                    return StopStandaloneResponse(
                        success=True,
                        infrastructure_terminated=True,
                        fleet_hibernated=False,
                        message=f"Hibernate échoué ({e}). Infrastructure détruite."
                    )
            else:
                # Pas de fleet_id, cancel complet
                orchestrator.cancel()
                return StopStandaloneResponse(
                    success=True,
                    infrastructure_terminated=True,
                    fleet_hibernated=False,
                    message="Mode standalone arrêté. Infrastructure détruite (pas de fleet à hibernater)."
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur stop_standalone: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
