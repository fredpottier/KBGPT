"""
OSMOSE Burst Types - Types et énumérations pour le mode Burst

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


class BurstStatus(str, Enum):
    """États du mode Burst."""

    # États initiaux
    IDLE = "idle"                           # Pas de batch actif
    PREPARING = "preparing"                 # Préparation des documents

    # Provisioning EC2
    REQUESTING_SPOT = "requesting_spot"     # CloudFormation en cours
    WAITING_CAPACITY = "waiting_capacity"   # Attente allocation Spot
    INSTANCE_STARTING = "instance_starting" # Boot + init services

    # Prêt
    READY = "ready"                         # Providers disponibles, prêt à traiter

    # Traitement
    PROCESSING = "processing"               # Batch en cours

    # Interruption et reprise
    INTERRUPTED = "interrupted"             # Spot perdu, en attente reprise
    RESUMING = "resuming"                   # Nouvelle instance, reprise en cours

    # États finaux
    COMPLETED = "completed"                 # Batch terminé avec succès
    FAILED = "failed"                       # Erreur fatale
    CANCELLED = "cancelled"                 # Annulé par l'utilisateur


class EventSeverity(str, Enum):
    """Niveau de sévérité des événements."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class BurstEvent:
    """Un événement dans la timeline du batch."""

    timestamp: str
    event_type: str
    message: str
    severity: str = "info"
    details: Optional[Dict[str, Any]] = None

    @classmethod
    def create(
        cls,
        event_type: str,
        message: str,
        severity: EventSeverity = EventSeverity.INFO,
        details: Optional[Dict[str, Any]] = None
    ) -> "BurstEvent":
        """Factory method pour créer un événement."""
        return cls(
            timestamp=datetime.utcnow().isoformat() + "Z",
            event_type=event_type,
            message=message,
            severity=severity.value,
            details=details
        )


@dataclass
class DocumentStatus:
    """Statut d'un document dans le batch."""

    path: str
    name: str
    status: str  # "pending", "processing", "completed", "failed"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    chunks_count: Optional[int] = None


@dataclass
class BurstState:
    """
    État persistant du mode Burst.

    Peut être sérialisé en JSON pour persistance S3 et reprise.
    """

    # Identifiants
    batch_id: str
    status: BurstStatus

    # Documents
    documents: List[DocumentStatus] = field(default_factory=list)

    # Infrastructure EC2
    stack_name: Optional[str] = None
    spot_fleet_id: Optional[str] = None
    instance_id: Optional[str] = None
    instance_ip: Optional[str] = None
    instance_type: Optional[str] = None
    instance_launch_time: Optional[str] = None  # Vrai launch time AWS (début facturation)

    # URLs des services
    vllm_url: Optional[str] = None
    embeddings_url: Optional[str] = None

    # Timestamps
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Compteurs
    interruption_count: int = 0
    total_documents: int = 0
    documents_done: int = 0
    documents_failed: int = 0

    # Timeline événements
    events: List[BurstEvent] = field(default_factory=list)

    # Configuration
    config: Dict[str, Any] = field(default_factory=dict)

    # Mode dual-logging (OpenAI + vLLM en parallèle)
    dual_logging: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'état en dictionnaire pour JSON."""
        return {
            "batch_id": self.batch_id,
            "status": self.status.value,
            "documents": [
                {
                    "path": d.path,
                    "name": d.name,
                    "status": d.status,
                    "started_at": d.started_at,
                    "completed_at": d.completed_at,
                    "error": d.error,
                    "chunks_count": d.chunks_count
                }
                for d in self.documents
            ],
            "stack_name": self.stack_name,
            "spot_fleet_id": self.spot_fleet_id,
            "instance_id": self.instance_id,
            "instance_ip": self.instance_ip,
            "instance_type": self.instance_type,
            "instance_launch_time": self.instance_launch_time,
            "vllm_url": self.vllm_url,
            "embeddings_url": self.embeddings_url,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "interruption_count": self.interruption_count,
            "total_documents": self.total_documents,
            "documents_done": self.documents_done,
            "documents_failed": self.documents_failed,
            "events": [
                {
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "message": e.message,
                    "severity": e.severity,
                    "details": e.details
                }
                for e in self.events
            ],
            "config": self.config
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BurstState":
        """Reconstruit l'état depuis un dictionnaire JSON."""
        documents = [
            DocumentStatus(
                path=d["path"],
                name=d["name"],
                status=d["status"],
                started_at=d.get("started_at"),
                completed_at=d.get("completed_at"),
                error=d.get("error"),
                chunks_count=d.get("chunks_count")
            )
            for d in data.get("documents", [])
        ]

        events = [
            BurstEvent(
                timestamp=e["timestamp"],
                event_type=e["event_type"],
                message=e["message"],
                severity=e.get("severity", "info"),
                details=e.get("details")
            )
            for e in data.get("events", [])
        ]

        return cls(
            batch_id=data["batch_id"],
            status=BurstStatus(data["status"]),
            documents=documents,
            stack_name=data.get("stack_name"),
            spot_fleet_id=data.get("spot_fleet_id"),
            instance_id=data.get("instance_id"),
            instance_ip=data.get("instance_ip"),
            instance_type=data.get("instance_type"),
            instance_launch_time=data.get("instance_launch_time"),
            vllm_url=data.get("vllm_url"),
            embeddings_url=data.get("embeddings_url"),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            interruption_count=data.get("interruption_count", 0),
            total_documents=data.get("total_documents", 0),
            documents_done=data.get("documents_done", 0),
            documents_failed=data.get("documents_failed", 0),
            events=events,
            config=data.get("config", {})
        )

    def add_event(
        self,
        event_type: str,
        message: str,
        severity: EventSeverity = EventSeverity.INFO,
        details: Optional[Dict[str, Any]] = None
    ):
        """Ajoute un événement à la timeline."""
        event = BurstEvent.create(event_type, message, severity, details)
        self.events.append(event)

    def get_pending_documents(self) -> List[DocumentStatus]:
        """Retourne les documents en attente de traitement."""
        return [d for d in self.documents if d.status == "pending"]

    def get_progress(self) -> Dict[str, Any]:
        """Retourne la progression actuelle."""
        return {
            "total": self.total_documents,
            "done": self.documents_done,
            "failed": self.documents_failed,
            "pending": self.total_documents - self.documents_done - self.documents_failed,
            "percent": round(
                (self.documents_done / self.total_documents * 100)
                if self.total_documents > 0 else 0,
                1
            )
        }


@dataclass
class BurstConfig:
    """
    Configuration du mode Burst.

    Optimisé pour Qwen 2.5 14B AWQ sur EC2 Spot g6/g6e.
    """

    # AWS
    aws_region: str = "eu-central-1"
    vpc_id: Optional[str] = None
    subnet_id: Optional[str] = None

    # Spot - g6/g6e pour 14B AWQ (L4 GPU 24GB, plus efficace que A10G)
    # Prix max 1.50€ - si dépassé, interruption + resume automatique
    spot_max_price: float = 1.50  # g6e.xlarge ~1.17€/h actuellement
    spot_instance_types: List[str] = field(
        default_factory=lambda: ["g6.2xlarge", "g6e.xlarge", "g5.2xlarge"]
    )

    # Models - Qwen 2.5 14B AWQ (quantifié 4-bit, ~8GB VRAM)
    vllm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    embeddings_model: str = "intfloat/multilingual-e5-large"

    # vLLM Configuration pour AWQ
    vllm_quantization: str = "awq_marlin"  # Kernels Marlin optimisés (~8x plus rapide que awq)
    vllm_dtype: str = "half"  # FP16 pour inférence AWQ
    vllm_gpu_memory_utilization: float = 0.85  # Maximise le cache KV (TEI utilise peu de VRAM)
    vllm_max_model_len: int = 16384  # 16K context — Qwen2.5 14B natif
    vllm_max_num_seqs: int = 64  # Augmenté pour meilleur batching

    # vLLM Optimisations (2026-01-27)
    vllm_enable_prefix_caching: bool = True  # Réutilise le cache KV du prompt système
    vllm_enable_chunked_prefill: bool = True  # Traitement par morceaux des longs prompts
    vllm_max_num_batched_tokens: int = 8192  # Tokens max par batch

    # vLLM Reasoning (vide = pas de reasoning parser pour Qwen2.5)
    vllm_reasoning_parser: str = ""  # Vide pour Qwen2.5, "qwen3" pour Qwen3
    vllm_default_thinking_enabled: bool = False  # Thinking OFF par défaut (activé per-request)

    # Ports
    vllm_port: int = 8000
    embeddings_port: int = 8001

    # Timeouts - augmentés pour 14B (chargement plus long)
    instance_boot_timeout: int = 3600  # 60 minutes (marge large pour EBS froid)
    model_load_timeout: int = 3600  # 60 minutes (marge large pour EBS froid)
    healthcheck_interval: int = 15  # Intervalle entre checks
    healthcheck_timeout: int = 10  # Timeout par check
    max_retries: int = 3
    max_interruption_retries: int = 5

    # AMI - Deep Learning AMI avec drivers NVIDIA préinstallés
    use_deep_learning_ami: bool = True
    deep_learning_ami_os: str = "ubuntu-22.04"  # ou "amazon-linux-2023"

    # Paths
    burst_pending_dir: str = "/data/burst/pending"

    # Callback URL pour notifications d'interruption Spot
    # L'instance EC2 appellera cette URL pour prévenir 2 min avant l'interruption
    callback_url: Optional[str] = None

    # Parallélisme: nombre de documents traités simultanément
    # 2 = bon compromis CPU/RAM local + charge EC2
    # Augmenter si machine locale puissante et EC2 sous-utilisée
    max_concurrent_docs: int = 2

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "aws_region": self.aws_region,
            "vpc_id": self.vpc_id,
            "subnet_id": self.subnet_id,
            "spot_max_price": self.spot_max_price,
            "spot_instance_types": self.spot_instance_types,
            "vllm_model": self.vllm_model,
            "embeddings_model": self.embeddings_model,
            "vllm_quantization": self.vllm_quantization,
            "vllm_dtype": self.vllm_dtype,
            "vllm_gpu_memory_utilization": self.vllm_gpu_memory_utilization,
            "vllm_max_model_len": self.vllm_max_model_len,
            "vllm_max_num_seqs": self.vllm_max_num_seqs,
            "vllm_enable_prefix_caching": self.vllm_enable_prefix_caching,
            "vllm_enable_chunked_prefill": self.vllm_enable_chunked_prefill,
            "vllm_max_num_batched_tokens": self.vllm_max_num_batched_tokens,
            "vllm_port": self.vllm_port,
            "embeddings_port": self.embeddings_port,
            "instance_boot_timeout": self.instance_boot_timeout,
            "model_load_timeout": self.model_load_timeout,
            "healthcheck_interval": self.healthcheck_interval,
            "healthcheck_timeout": self.healthcheck_timeout,
            "max_retries": self.max_retries,
            "max_interruption_retries": self.max_interruption_retries,
            "use_deep_learning_ami": self.use_deep_learning_ami,
            "deep_learning_ami_os": self.deep_learning_ami_os,
            "burst_pending_dir": self.burst_pending_dir,
            "callback_url": self.callback_url,
            "max_concurrent_docs": self.max_concurrent_docs,
            "vllm_reasoning_parser": self.vllm_reasoning_parser,
            "vllm_default_thinking_enabled": self.vllm_default_thinking_enabled
        }

    @classmethod
    def from_env(cls) -> "BurstConfig":
        """Charge la configuration depuis les variables d'environnement."""
        import os

        return cls(
            # AWS - Utiliser AWS_DEFAULT_REGION comme fallback
            aws_region=os.getenv("BURST_AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-central-1")),
            vpc_id=os.getenv("BURST_VPC_ID"),
            subnet_id=os.getenv("BURST_SUBNET_ID"),

            # Spot instances (1.50€ max - interruption si dépassé)
            spot_max_price=float(os.getenv("BURST_SPOT_MAX_PRICE", "1.50")),
            spot_instance_types=os.getenv(
                "BURST_SPOT_INSTANCE_TYPES",
                "g6.2xlarge,g6e.xlarge,g5.2xlarge"
            ).split(","),

            # Models
            vllm_model=os.getenv("BURST_VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ"),
            embeddings_model=os.getenv(
                "BURST_EMBEDDINGS_MODEL",
                "intfloat/multilingual-e5-large"
            ),

            # vLLM AWQ configuration
            vllm_quantization=os.getenv("BURST_VLLM_QUANTIZATION", "awq_marlin"),
            vllm_dtype=os.getenv("BURST_VLLM_DTYPE", "half"),
            vllm_gpu_memory_utilization=float(
                os.getenv("BURST_VLLM_GPU_MEMORY_UTILIZATION", "0.85")
            ),
            vllm_max_model_len=int(os.getenv("BURST_VLLM_MAX_MODEL_LEN", "16384")),
            vllm_max_num_seqs=int(os.getenv("BURST_VLLM_MAX_NUM_SEQS", "64")),

            # vLLM Optimisations (2026-01-27)
            vllm_enable_prefix_caching=os.getenv("BURST_VLLM_ENABLE_PREFIX_CACHING", "true").lower() == "true",
            vllm_enable_chunked_prefill=os.getenv("BURST_VLLM_ENABLE_CHUNKED_PREFILL", "true").lower() == "true",
            vllm_max_num_batched_tokens=int(os.getenv("BURST_VLLM_MAX_NUM_BATCHED_TOKENS", "8192")),

            # Reasoning (vide pour Qwen2.5, "qwen3" pour Qwen3)
            vllm_reasoning_parser=os.getenv("BURST_VLLM_REASONING_PARSER", ""),
            vllm_default_thinking_enabled=os.getenv("BURST_VLLM_DEFAULT_THINKING", "false").lower() == "true",

            # Ports
            vllm_port=int(os.getenv("BURST_VLLM_PORT", "8000")),
            embeddings_port=int(os.getenv("BURST_EMBEDDINGS_PORT", "8001")),

            # Timeouts (augmentés pour 14B)
            instance_boot_timeout=int(os.getenv("BURST_INSTANCE_BOOT_TIMEOUT", "3600")),
            model_load_timeout=int(os.getenv("BURST_MODEL_LOAD_TIMEOUT", "3600")),
            healthcheck_interval=int(os.getenv("BURST_HEALTHCHECK_INTERVAL", "15")),
            healthcheck_timeout=int(os.getenv("BURST_HEALTHCHECK_TIMEOUT", "10")),
            max_retries=int(os.getenv("BURST_MAX_RETRIES", "3")),
            max_interruption_retries=int(os.getenv("BURST_MAX_INTERRUPTION_RETRIES", "5")),

            # AMI
            use_deep_learning_ami=os.getenv("BURST_USE_DEEP_LEARNING_AMI", "true").lower() == "true",
            deep_learning_ami_os=os.getenv("BURST_DEEP_LEARNING_AMI_OS", "ubuntu-22.04"),

            # Paths
            burst_pending_dir=os.getenv("BURST_PENDING_DIR", "/data/burst/pending"),

            # Callback URL pour notification d'interruption Spot
            callback_url=os.getenv("BURST_CALLBACK_URL"),

            # Parallélisme (nombre de docs traités simultanément)
            max_concurrent_docs=int(os.getenv("BURST_MAX_CONCURRENT_DOCS", "2"))
        )
