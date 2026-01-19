"""
Pass 3.5 Background Jobs for RQ Queue.

Système de jobs async pour Pass 3.5 (Evidence Bundle Resolver).
Pattern identique à pass3_jobs.py pour cohérence.

Author: OSMOSE
Date: 2026-01-17
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

import redis
from rq import Queue

from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


# =============================================================================
# Job State Management (Redis-backed)
# =============================================================================

class Pass35JobStatus(str, Enum):
    """États possibles d'un job Pass3.5."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Pass35JobProgress:
    """Progression d'un job Pass3.5."""
    current_phase: str = ""
    phase_index: int = 0
    total_phases: int = 3  # Detection, Validation, Promotion
    pairs_found: int = 0
    bundles_created: int = 0
    bundles_promoted: int = 0
    bundles_rejected: int = 0
    started_at: Optional[str] = None
    phase_started_at: Optional[str] = None
    elapsed_seconds: float = 0
    estimated_remaining_seconds: float = 0
    last_message: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.current_phase
        if self.pairs_found > 0:
            data["percentage"] = (self.bundles_created / self.pairs_found) * 100
        else:
            data["percentage"] = 0
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass35JobProgress":
        errors = data.get("errors") or []
        return cls(
            current_phase=data.get("current_phase", ""),
            phase_index=data.get("phase_index", 0),
            total_phases=data.get("total_phases", 3),
            pairs_found=data.get("pairs_found", 0),
            bundles_created=data.get("bundles_created", 0),
            bundles_promoted=data.get("bundles_promoted", 0),
            bundles_rejected=data.get("bundles_rejected", 0),
            started_at=data.get("started_at"),
            phase_started_at=data.get("phase_started_at"),
            elapsed_seconds=data.get("elapsed_seconds", 0),
            estimated_remaining_seconds=data.get("estimated_remaining_seconds", 0),
            last_message=data.get("last_message", ""),
            errors=errors
        )


@dataclass
class Pass35JobState:
    """État complet d'un job Pass3.5."""
    job_id: str
    tenant_id: str
    status: Pass35JobStatus
    document_id: Optional[str] = None
    lang: str = "fr"
    auto_promote: bool = True
    min_confidence: float = 0.6
    progress: Pass35JobProgress = field(default_factory=Pass35JobProgress)
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_by: str = "admin"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value,
            "document_id": self.document_id,
            "lang": self.lang,
            "auto_promote": self.auto_promote,
            "min_confidence": self.min_confidence,
            "progress": self.progress.to_dict(),
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_by": self.created_by
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass35JobState":
        return cls(
            job_id=data["job_id"],
            tenant_id=data.get("tenant_id", "default"),
            status=Pass35JobStatus(data.get("status", "pending")),
            document_id=data.get("document_id"),
            lang=data.get("lang", "fr"),
            auto_promote=data.get("auto_promote", True),
            min_confidence=data.get("min_confidence", 0.6),
            progress=Pass35JobProgress.from_dict(data.get("progress", {})),
            result=data.get("result", {}),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_by=data.get("created_by", "admin")
        )


class Pass35JobManager:
    """Gestionnaire des jobs Pass3.5 avec persistance Redis."""

    REDIS_PREFIX = "pass35:job:"
    JOB_TTL_SECONDS = 86400 * 7  # 7 jours

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        if redis_client:
            self._redis = redis_client
        else:
            settings = get_settings()
            redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
            self._redis = redis.from_url(redis_url, decode_responses=True)

    def _job_key(self, job_id: str) -> str:
        return f"{self.REDIS_PREFIX}{job_id}"

    def _list_key(self, tenant_id: str) -> str:
        return f"{self.REDIS_PREFIX}list:{tenant_id}"

    def create_job(
        self,
        tenant_id: str = "default",
        document_id: Optional[str] = None,
        lang: str = "fr",
        auto_promote: bool = True,
        min_confidence: float = 0.6,
        created_by: str = "admin"
    ) -> Pass35JobState:
        """Crée un nouveau job Pass3.5."""
        job_id = f"p35_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat() + "Z"

        state = Pass35JobState(
            job_id=job_id,
            tenant_id=tenant_id,
            status=Pass35JobStatus.PENDING,
            document_id=document_id,
            lang=lang,
            auto_promote=auto_promote,
            min_confidence=min_confidence,
            created_at=now,
            created_by=created_by
        )

        self._save_state(state)
        self._redis.lpush(self._list_key(tenant_id), job_id)
        self._redis.ltrim(self._list_key(tenant_id), 0, 99)

        logger.info(f"[OSMOSE:Pass3.5] Created job {job_id}")
        return state

    def get_job(self, job_id: str) -> Optional[Pass35JobState]:
        """Récupère l'état d'un job."""
        data = self._redis.get(self._job_key(job_id))
        if not data:
            return None
        try:
            return Pass35JobState.from_dict(json.loads(data))
        except Exception as e:
            logger.error(f"[OSMOSE:Pass3.5] Error parsing job {job_id}: {e}")
            return None

    def list_jobs(self, tenant_id: str = "default", limit: int = 20) -> List[Pass35JobState]:
        """Liste les jobs d'un tenant."""
        job_ids = self._redis.lrange(self._list_key(tenant_id), 0, limit - 1)
        jobs = []
        for job_id in job_ids:
            state = self.get_job(job_id)
            if state:
                jobs.append(state)
        return jobs

    def update_progress(
        self,
        job_id: str,
        current_phase: Optional[str] = None,
        pairs_found: Optional[int] = None,
        bundles_created: Optional[int] = None,
        bundles_promoted: Optional[int] = None,
        bundles_rejected: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Met à jour la progression d'un job."""
        state = self.get_job(job_id)
        if not state:
            return

        if current_phase is not None:
            state.progress.current_phase = current_phase
            state.progress.phase_started_at = datetime.utcnow().isoformat() + "Z"
        if pairs_found is not None:
            state.progress.pairs_found = pairs_found
        if bundles_created is not None:
            state.progress.bundles_created = bundles_created
        if bundles_promoted is not None:
            state.progress.bundles_promoted = bundles_promoted
        if bundles_rejected is not None:
            state.progress.bundles_rejected = bundles_rejected
        if message:
            state.progress.last_message = message
        if error:
            state.progress.errors.append(error)

        # Calculer temps écoulé
        if state.started_at:
            try:
                started = datetime.fromisoformat(state.started_at.replace("Z", "+00:00"))
                now = datetime.utcnow().replace(tzinfo=started.tzinfo)
                state.progress.elapsed_seconds = (now - started).total_seconds()
            except Exception:
                pass

        self._save_state(state)

    def start_job(self, job_id: str):
        """Marque un job comme démarré."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass35JobStatus.RUNNING
            state.started_at = datetime.utcnow().isoformat() + "Z"
            state.progress.started_at = state.started_at
            self._save_state(state)
            logger.info(f"[OSMOSE:Pass3.5] Job {job_id} started")

    def complete_job(self, job_id: str, result: Optional[Dict] = None):
        """Marque un job comme terminé."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass35JobStatus.COMPLETED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            if result:
                state.result = result
            state.progress.last_message = "Pass 3.5 completed successfully"
            self._save_state(state)
            logger.info(f"[OSMOSE:Pass3.5] Job {job_id} completed")

    def fail_job(self, job_id: str, error: str):
        """Marque un job comme échoué."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass35JobStatus.FAILED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            state.progress.errors.append(error)
            state.progress.last_message = f"Failed: {error}"
            self._save_state(state)
            logger.error(f"[OSMOSE:Pass3.5] Job {job_id} failed: {error}")

    def cancel_job(self, job_id: str) -> bool:
        """Annule un job."""
        state = self.get_job(job_id)
        if not state or state.status not in [Pass35JobStatus.PENDING, Pass35JobStatus.RUNNING]:
            return False

        state.status = Pass35JobStatus.CANCELLED
        state.completed_at = datetime.utcnow().isoformat() + "Z"
        state.progress.last_message = "Cancelled by user"
        self._save_state(state)
        logger.info(f"[OSMOSE:Pass3.5] Job {job_id} cancelled")
        return True

    def is_cancelled(self, job_id: str) -> bool:
        """Vérifie si un job a été annulé."""
        state = self.get_job(job_id)
        return state.status == Pass35JobStatus.CANCELLED if state else False

    def _save_state(self, state: Pass35JobState):
        """Sauvegarde l'état dans Redis."""
        self._redis.setex(
            self._job_key(state.job_id),
            self.JOB_TTL_SECONDS,
            json.dumps(state.to_dict())
        )


# Singleton
_job_manager: Optional[Pass35JobManager] = None


def get_pass35_job_manager() -> Pass35JobManager:
    """Récupère l'instance singleton du gestionnaire."""
    global _job_manager
    if _job_manager is None:
        _job_manager = Pass35JobManager()
    return _job_manager


# =============================================================================
# Main Worker Function - Execute Pass 3.5 with Progress
# =============================================================================

def execute_pass35_job(job_id: str):
    """
    Fonction worker RQ: Exécute Pass 3.5 (Evidence Bundle Resolver) avec progression.

    Args:
        job_id: ID du job à exécuter
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.relations.evidence_bundle_resolver import EvidenceBundleResolver

    manager = get_pass35_job_manager()
    state = manager.get_job(job_id)

    if not state:
        logger.error(f"[OSMOSE:Pass3.5] Job {job_id} not found")
        return

    if state.status == Pass35JobStatus.CANCELLED:
        logger.info(f"[OSMOSE:Pass3.5] Job {job_id} was cancelled, skipping")
        return

    manager.start_job(job_id)

    try:
        # Initialiser le client Neo4j
        neo4j_client = Neo4jClient()

        # Initialiser le resolver
        resolver = EvidenceBundleResolver(
            neo4j_client=neo4j_client,
            lang=state.lang,
            auto_promote=state.auto_promote,
            min_confidence_for_promotion=state.min_confidence,
        )

        # Phase 1: Détection
        manager.update_progress(
            job_id,
            current_phase="CANDIDATE_DETECTION",
            message="Detecting candidate pairs..."
        )

        if manager.is_cancelled(job_id):
            return

        # Exécuter le traitement
        result = resolver.process_document(
            document_id=state.document_id,
            tenant_id=state.tenant_id,
        )

        if manager.is_cancelled(job_id):
            return

        # Phase finale: mise à jour
        manager.update_progress(
            job_id,
            current_phase="COMPLETED",
            pairs_found=result.stats.pairs_found,
            bundles_created=result.stats.bundles_created,
            bundles_promoted=result.stats.bundles_promoted,
            bundles_rejected=result.stats.bundles_rejected,
            message=f"Completed: {result.stats.bundles_promoted} relations promoted"
        )

        result_dict = {
            "success": True,
            "document_id": result.document_id,
            "pairs_found": result.stats.pairs_found,
            "pairs_with_charspan": result.stats.pairs_with_charspan,
            "bundles_created": result.stats.bundles_created,
            "bundles_promoted": result.stats.bundles_promoted,
            "bundles_rejected": result.stats.bundles_rejected,
            "rejection_counts": result.stats.rejection_counts,
            "processing_time_seconds": result.processing_time_seconds,
        }

        manager.complete_job(job_id, result_dict)
        logger.info(
            f"[OSMOSE:Pass3.5] Job {job_id} completed: "
            f"{result.stats.bundles_promoted} relations promoted"
        )

    except Exception as e:
        logger.exception(f"[OSMOSE:Pass3.5] Job {job_id} failed")
        manager.fail_job(job_id, str(e))


def enqueue_pass35_job(
    tenant_id: str = "default",
    document_id: Optional[str] = None,
    lang: str = "fr",
    auto_promote: bool = True,
    min_confidence: float = 0.6,
    created_by: str = "admin"
) -> Pass35JobState:
    """
    Crée et enqueue un job Pass3.5.

    Args:
        tenant_id: ID du tenant
        document_id: Document à traiter (requis)
        lang: Code langue (fr, en, de)
        auto_promote: Si True, promeut automatiquement les bundles valides
        min_confidence: Seuil de confiance pour promotion
        created_by: Email du créateur

    Returns:
        Pass35JobState avec job_id pour suivi
    """
    if not document_id:
        raise ValueError("document_id is required for Pass 3.5")

    manager = get_pass35_job_manager()

    state = manager.create_job(
        tenant_id=tenant_id,
        document_id=document_id,
        lang=lang,
        auto_promote=auto_promote,
        min_confidence=min_confidence,
        created_by=created_by
    )

    settings = get_settings()
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
    redis_conn = redis.from_url(redis_url)
    queue = Queue("ingestion", connection=redis_conn)

    queue.enqueue(
        execute_pass35_job,
        state.job_id,
        job_timeout="1h",
        result_ttl=86400,
        job_id=f"rq_{state.job_id}"
    )

    logger.info(f"[OSMOSE:Pass3.5] Enqueued job {state.job_id} for document {document_id}")
    return state


def process_pass35_evidence_bundles(
    document_id: str,
    tenant_id: str = "default",
    lang: str = "fr",
    auto_promote: bool = True,
) -> Dict[str, Any]:
    """
    Fonction synchrone pour traiter les bundles d'un document.

    Utilisable directement sans passer par la queue RQ.

    Args:
        document_id: ID du document
        tenant_id: Tenant ID
        lang: Code langue
        auto_promote: Si True, promeut automatiquement

    Returns:
        Dict avec résultats du traitement
    """
    from knowbase.common.clients.neo4j_client import Neo4jClient
    from knowbase.relations.evidence_bundle_resolver import EvidenceBundleResolver

    logger.info(f"[OSMOSE:Pass3.5] Processing bundles for document {document_id}")

    neo4j_client = Neo4jClient()

    resolver = EvidenceBundleResolver(
        neo4j_client=neo4j_client,
        lang=lang,
        auto_promote=auto_promote,
    )

    result = resolver.process_document(document_id, tenant_id)

    return {
        "success": True,
        "document_id": result.document_id,
        "pairs_found": result.stats.pairs_found,
        "bundles_created": result.stats.bundles_created,
        "bundles_promoted": result.stats.bundles_promoted,
        "bundles_rejected": result.stats.bundles_rejected,
        "processing_time_seconds": result.processing_time_seconds,
    }


__all__ = [
    "Pass35JobStatus",
    "Pass35JobProgress",
    "Pass35JobState",
    "Pass35JobManager",
    "get_pass35_job_manager",
    "execute_pass35_job",
    "enqueue_pass35_job",
    "process_pass35_evidence_bundles",
]
