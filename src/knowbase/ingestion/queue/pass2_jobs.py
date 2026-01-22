"""
Pass 2 Background Jobs for RQ Queue.

Architecture production-ready avec:
- Persistance de l'état dans Redis
- Progression en temps réel
- Reprise sur erreur
- Annulation possible

Jobs:
- execute_pass2_full_job: Exécute Pass 2 complet avec progression
- process_pass2_queue: Traite les jobs Pass 2 en attente
- run_pass2_for_document: Exécute Pass 2 pour un document spécifique
- scheduled_pass2_consolidation: Batch nocturne pour consolidation

Author: OSMOSE Phase 2
Date: 2024-12 (Updated 2024-12-31 for production-ready job management)
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
from rq import get_current_job, Queue

from knowbase.config.settings import get_settings
from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


# =============================================================================
# Phase Registry for Dynamic Execution (ADR Dynamic Phases)
# =============================================================================

@dataclass
class PhaseConfig:
    """Configuration pour une phase Pass2."""
    name: str                    # Nom dans feature_flags.yaml
    display_name: str            # Nom pour le progress tracking
    handler: str                 # Nom de la fonction handler
    skip_flag: Optional[str]     # Flag skip_* correspondant (None = toujours exécuter)


# Registre des phases - ordre d'exécution déterminé par enabled_phases dans config
PHASE_REGISTRY: Dict[str, PhaseConfig] = {
    "corpus_promotion": PhaseConfig(
        "corpus_promotion", "CORPUS_PROMOTION",
        "_execute_corpus_promotion", "skip_promotion"
    ),
    "structural_topics": PhaseConfig(
        "structural_topics", "STRUCTURAL_TOPICS",
        "_execute_structural_topics", None
    ),
    "classify_fine": PhaseConfig(
        "classify_fine", "CLASSIFY_FINE",
        "_execute_classify_fine", "skip_classify"
    ),
    "enrich_relations": PhaseConfig(
        "enrich_relations", "ENRICH_RELATIONS",
        "_execute_enrich_relations", "skip_enrich"
    ),
    "normative_extraction": PhaseConfig(
        "normative_extraction", "NORMATIVE_EXTRACTION",
        "_execute_normative_extraction", None
    ),
    "semantic_consolidation": PhaseConfig(
        "semantic_consolidation", "SEMANTIC_CONSOLIDATION",
        "_execute_semantic_consolidation", None
    ),
    "cross_doc": PhaseConfig(
        "cross_doc", "CORPUS_ER",
        "_execute_corpus_er", "skip_corpus_er"
    ),
}


# =============================================================================
# Job State Management (Redis-backed)
# =============================================================================

class Pass2JobStatus(str, Enum):
    """États possibles d'un job Pass2."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"  # vLLM temporairement indisponible, reprise possible


@dataclass
class Pass2JobProgress:
    """Progression d'un job Pass2."""
    current_phase: str = ""
    phase_index: int = 0
    total_phases: int = 4
    iteration: int = 0
    total_iterations: int = 0
    items_processed: int = 0
    items_total: int = 0
    items_updated: int = 0
    type_changes: int = 0
    started_at: Optional[str] = None
    phase_started_at: Optional[str] = None
    elapsed_seconds: float = 0
    estimated_remaining_seconds: float = 0
    last_message: str = ""
    errors: List[str] = field(default_factory=list)
    # Checkpoint pour reprise après suspension (vLLM down)
    processed_item_ids: List[str] = field(default_factory=list)
    checkpoint_iteration: int = 0
    suspended_at: Optional[str] = None
    suspension_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Add frontend-expected fields
        data["phase"] = self.current_phase  # Frontend expects 'phase'
        data["current_batch"] = self.iteration
        data["total_batches"] = self.total_iterations if self.total_iterations > 0 else max(1, self.items_total // 500)
        # Calculate percentage
        if self.items_total > 0:
            data["percentage"] = (self.items_processed / self.items_total) * 100
        else:
            data["percentage"] = 0
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass2JobProgress":
        errors = data.get("errors") or []
        processed_item_ids = data.get("processed_item_ids") or []
        return cls(
            current_phase=data.get("current_phase", ""),
            phase_index=data.get("phase_index", 0),
            total_phases=data.get("total_phases", 4),
            iteration=data.get("iteration", 0),
            total_iterations=data.get("total_iterations", 0),
            items_processed=data.get("items_processed", 0),
            items_total=data.get("items_total", 0),
            items_updated=data.get("items_updated", 0),
            type_changes=data.get("type_changes", 0),
            started_at=data.get("started_at"),
            phase_started_at=data.get("phase_started_at"),
            elapsed_seconds=data.get("elapsed_seconds", 0),
            estimated_remaining_seconds=data.get("estimated_remaining_seconds", 0),
            last_message=data.get("last_message", ""),
            errors=errors,
            processed_item_ids=processed_item_ids,
            checkpoint_iteration=data.get("checkpoint_iteration", 0),
            suspended_at=data.get("suspended_at"),
            suspension_reason=data.get("suspension_reason", "")
        )


@dataclass
class Pass2JobState:
    """État complet d'un job Pass2."""
    job_id: str
    tenant_id: str
    status: Pass2JobStatus
    document_id: Optional[str] = None
    skip_promotion: bool = False  # Pass 2.0: ProtoConcepts → CanonicalConcepts
    skip_classify: bool = False
    skip_enrich: bool = False
    skip_consolidate: bool = False
    skip_corpus_er: bool = False
    batch_size: int = 500
    process_all: bool = True
    progress: Pass2JobProgress = field(default_factory=Pass2JobProgress)
    phase_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
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
            "skip_promotion": self.skip_promotion,
            "skip_classify": self.skip_classify,
            "skip_enrich": self.skip_enrich,
            "skip_consolidate": self.skip_consolidate,
            "skip_corpus_er": self.skip_corpus_er,
            "batch_size": self.batch_size,
            "process_all": self.process_all,
            "progress": self.progress.to_dict(),
            "phase_results": self.phase_results,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_by": self.created_by
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pass2JobState":
        return cls(
            job_id=data["job_id"],
            tenant_id=data.get("tenant_id", "default"),
            status=Pass2JobStatus(data.get("status", "pending")),
            document_id=data.get("document_id"),
            skip_promotion=data.get("skip_promotion", False),
            skip_classify=data.get("skip_classify", False),
            skip_enrich=data.get("skip_enrich", False),
            skip_consolidate=data.get("skip_consolidate", False),
            skip_corpus_er=data.get("skip_corpus_er", False),
            batch_size=data.get("batch_size", 500),
            process_all=data.get("process_all", True),
            progress=Pass2JobProgress.from_dict(data.get("progress", {})),
            phase_results=data.get("phase_results", {}),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_by=data.get("created_by", "admin")
        )


class Pass2JobManager:
    """Gestionnaire des jobs Pass2 avec persistance Redis."""

    REDIS_PREFIX = "pass2:job:"
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
        skip_promotion: bool = False,
        skip_classify: bool = False,
        skip_enrich: bool = False,
        skip_consolidate: bool = False,
        skip_corpus_er: bool = False,
        batch_size: int = 500,
        process_all: bool = True,
        created_by: str = "admin"
    ) -> Pass2JobState:
        """Crée un nouveau job Pass2."""
        job_id = f"p2_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat() + "Z"

        state = Pass2JobState(
            job_id=job_id,
            tenant_id=tenant_id,
            status=Pass2JobStatus.PENDING,
            document_id=document_id,
            skip_promotion=skip_promotion,
            skip_classify=skip_classify,
            skip_enrich=skip_enrich,
            skip_consolidate=skip_consolidate,
            skip_corpus_er=skip_corpus_er,
            batch_size=batch_size,
            process_all=process_all,
            created_at=now,
            created_by=created_by
        )

        self._save_state(state)
        self._redis.lpush(self._list_key(tenant_id), job_id)
        self._redis.ltrim(self._list_key(tenant_id), 0, 99)

        logger.info(f"[Pass2JobManager] Created job {job_id} (batch_size={batch_size}, process_all={process_all})")
        return state

    def get_job(self, job_id: str) -> Optional[Pass2JobState]:
        """Récupère l'état d'un job."""
        data = self._redis.get(self._job_key(job_id))
        if not data:
            return None
        try:
            return Pass2JobState.from_dict(json.loads(data))
        except Exception as e:
            logger.error(f"[Pass2JobManager] Error parsing job {job_id}: {e}")
            return None

    def list_jobs(self, tenant_id: str = "default", limit: int = 20) -> List[Pass2JobState]:
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
        phase_index: Optional[int] = None,
        iteration: Optional[int] = None,
        total_iterations: Optional[int] = None,
        items_processed: Optional[int] = None,
        items_total: Optional[int] = None,
        items_updated: Optional[int] = None,
        type_changes: Optional[int] = None,
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
        if phase_index is not None:
            state.progress.phase_index = phase_index
        if iteration is not None:
            state.progress.iteration = iteration
        if total_iterations is not None:
            state.progress.total_iterations = total_iterations
        if items_processed is not None:
            state.progress.items_processed = items_processed
        if items_total is not None:
            state.progress.items_total = items_total
        if items_updated is not None:
            state.progress.items_updated = items_updated
        if type_changes is not None:
            state.progress.type_changes = type_changes
        if message:
            state.progress.last_message = message
        if error:
            state.progress.errors.append(error)

        # Calculer temps écoulé et estimation
        if state.started_at:
            try:
                started = datetime.fromisoformat(state.started_at.replace("Z", "+00:00"))
                now = datetime.utcnow().replace(tzinfo=started.tzinfo)
                state.progress.elapsed_seconds = (now - started).total_seconds()

                if state.progress.items_total > 0 and state.progress.items_processed > 0:
                    rate = state.progress.items_processed / max(state.progress.elapsed_seconds, 1)
                    remaining = state.progress.items_total - state.progress.items_processed
                    state.progress.estimated_remaining_seconds = remaining / rate if rate > 0 else 0
            except Exception:
                pass

        self._save_state(state)

    def start_job(self, job_id: str):
        """Marque un job comme démarré."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass2JobStatus.RUNNING
            state.started_at = datetime.utcnow().isoformat() + "Z"
            state.progress.started_at = state.started_at
            self._save_state(state)
            logger.info(f"[Pass2JobManager] Job {job_id} started")

    def complete_job(self, job_id: str, phase_results: Optional[Dict] = None):
        """Marque un job comme terminé."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass2JobStatus.COMPLETED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            if phase_results:
                state.phase_results = phase_results
            state.progress.last_message = "Pass 2 completed successfully"
            self._save_state(state)
            logger.info(f"[Pass2JobManager] Job {job_id} completed")

    def fail_job(self, job_id: str, error: str):
        """Marque un job comme échoué."""
        state = self.get_job(job_id)
        if state:
            state.status = Pass2JobStatus.FAILED
            state.completed_at = datetime.utcnow().isoformat() + "Z"
            state.progress.errors.append(error)
            state.progress.last_message = f"Failed: {error}"
            self._save_state(state)
            logger.error(f"[Pass2JobManager] Job {job_id} failed: {error}")

    def cancel_job(self, job_id: str) -> bool:
        """Annule un job."""
        state = self.get_job(job_id)
        if not state or state.status not in [Pass2JobStatus.PENDING, Pass2JobStatus.RUNNING]:
            return False

        state.status = Pass2JobStatus.CANCELLED
        state.completed_at = datetime.utcnow().isoformat() + "Z"
        state.progress.last_message = "Cancelled by user"
        self._save_state(state)
        logger.info(f"[Pass2JobManager] Job {job_id} cancelled")
        return True

    def suspend_job(
        self,
        job_id: str,
        reason: str,
        processed_item_ids: Optional[List[str]] = None,
        checkpoint_iteration: int = 0
    ) -> bool:
        """
        Suspend un job avec sauvegarde du checkpoint pour reprise ultérieure.

        Utilisé quand vLLM devient indisponible (Spot interruption, etc.)
        Le job pourra être repris avec resume_job() une fois vLLM disponible.

        Args:
            job_id: ID du job à suspendre
            reason: Raison de la suspension (ex: "vLLM unavailable")
            processed_item_ids: IDs des items déjà traités (checkpoint)
            checkpoint_iteration: Numéro de l'itération pour reprise

        Returns:
            True si le job a été suspendu, False sinon
        """
        state = self.get_job(job_id)
        if not state or state.status not in [Pass2JobStatus.RUNNING]:
            logger.warning(f"[Pass2JobManager] Cannot suspend job {job_id}: invalid status")
            return False

        state.status = Pass2JobStatus.SUSPENDED
        state.progress.suspended_at = datetime.utcnow().isoformat() + "Z"
        state.progress.suspension_reason = reason
        state.progress.last_message = f"Suspended: {reason}"

        if processed_item_ids:
            state.progress.processed_item_ids = processed_item_ids
        state.progress.checkpoint_iteration = checkpoint_iteration

        self._save_state(state)
        logger.warning(
            f"[Pass2JobManager] Job {job_id} SUSPENDED: {reason} "
            f"(checkpoint: {len(processed_item_ids or [])} items, iteration {checkpoint_iteration})"
        )
        return True

    def resume_job(self, job_id: str) -> bool:
        """
        Reprend un job suspendu.

        Le job sera remis en status RUNNING avec son checkpoint préservé.
        Le worker vérifiera le checkpoint pour ne pas retraiter les items déjà traités.

        Args:
            job_id: ID du job à reprendre

        Returns:
            True si le job a été repris, False sinon
        """
        state = self.get_job(job_id)
        if not state or state.status != Pass2JobStatus.SUSPENDED:
            logger.warning(f"[Pass2JobManager] Cannot resume job {job_id}: not suspended")
            return False

        state.status = Pass2JobStatus.RUNNING
        state.progress.last_message = f"Resumed from checkpoint (iteration {state.progress.checkpoint_iteration})"
        self._save_state(state)

        logger.info(
            f"[Pass2JobManager] Job {job_id} RESUMED from checkpoint "
            f"({len(state.progress.processed_item_ids)} items already processed)"
        )
        return True

    def get_suspended_jobs(self, tenant_id: str = "default") -> List[Pass2JobState]:
        """Retourne tous les jobs suspendus d'un tenant."""
        all_jobs = self.list_jobs(tenant_id, limit=100)
        return [j for j in all_jobs if j.status == Pass2JobStatus.SUSPENDED]

    def is_cancelled(self, job_id: str) -> bool:
        """Vérifie si un job a été annulé."""
        state = self.get_job(job_id)
        return state.status == Pass2JobStatus.CANCELLED if state else False

    def set_phase_result(self, job_id: str, phase: str, result: Dict[str, Any]):
        """Enregistre le résultat d'une phase."""
        state = self.get_job(job_id)
        if state:
            state.phase_results[phase] = result
            self._save_state(state)

    def _save_state(self, state: Pass2JobState):
        """Sauvegarde l'état dans Redis."""
        self._redis.setex(
            self._job_key(state.job_id),
            self.JOB_TTL_SECONDS,
            json.dumps(state.to_dict())
        )


# Singleton
_job_manager: Optional[Pass2JobManager] = None


def get_pass2_job_manager() -> Pass2JobManager:
    """Récupère l'instance singleton du gestionnaire."""
    global _job_manager
    if _job_manager is None:
        _job_manager = Pass2JobManager()
    return _job_manager


# =============================================================================
# Phase Handlers - Extracted from execute_pass2_full_job for dynamic execution
# =============================================================================

def _execute_corpus_promotion(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """
    Execute CORPUS_PROMOTION phase (Pass 2.0).
    Promotes ProtoConcepts to CanonicalConcepts.
    """
    try:
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine
        promotion_engine = CorpusPromotionEngine(tenant_id=state.tenant_id)
        promotion_result = asyncio.run(promotion_engine.promote_corpus())

        result = {
            "success": True,
            "proto_count": promotion_result.proto_concepts_processed,
            "promoted_count": promotion_result.canonical_concepts_created,
            "skipped_count": promotion_result.skipped_count,
            "merged_count": promotion_result.merged_count,
            "singleton_count": promotion_result.singleton_count,
            "documents_processed": promotion_result.documents_processed,
            "execution_time_ms": promotion_result.execution_time_ms
        }
        manager.update_progress(job_id,
            message=f"Promotion: {promotion_result.canonical_concepts_created} promoted, "
                   f"{promotion_result.merged_count} merged, {promotion_result.documents_processed} docs")
        logger.info(f"[Pass2Worker] CORPUS_PROMOTION complete: {promotion_result.to_dict()}")
        return result
    except Exception as e:
        logger.error(f"[Pass2Worker] CORPUS_PROMOTION failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _execute_structural_topics(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """Execute STRUCTURAL_TOPICS phase (Pass 2a)."""
    try:
        result = asyncio.run(service.run_structural_topics(state.document_id))
        phase_result = {
            "success": result.success,
            "items_processed": result.items_processed,
            "items_created": result.items_created,
            "execution_time_ms": result.execution_time_ms,
            "details": result.details
        }
        manager.update_progress(job_id,
            message=f"Topics: {result.details.get('topics_created', 0)} sections, "
                   f"{result.details.get('covers_created', 0)} couvertures")
        return phase_result
    except Exception as e:
        logger.warning(f"[Pass2Worker] STRUCTURAL_TOPICS failed: {e}")
        return {"success": False, "error": str(e)}


def _execute_classify_fine(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """
    Execute CLASSIFY_FINE phase (Pass 2b-1).
    Classifies concepts with LLM, supports checkpointing and suspension.
    """
    # Compter les concepts à classifier
    classify_count_query = """
    MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c.type_fine IS NULL OR c.type_fine = ''
          OR c.type_fine_justification = 'Fallback to heuristic type'
    RETURN count(c) AS count
    """
    classify_result = service._execute_query(classify_count_query, {"tenant_id": state.tenant_id})
    concepts_to_classify = classify_result[0]["count"] if classify_result else 0

    if concepts_to_classify == 0:
        logger.info(f"[Pass2Worker] CLASSIFY_FINE skipped for job {job_id}: all concepts already classified")
        manager.update_progress(job_id, message="Classification skipped: all concepts already have type_fine")
        return {
            "success": True,
            "items_processed": 0,
            "items_updated": 0,
            "execution_time_ms": 0,
            "details": {"skipped": True, "reason": "All concepts already classified"}
        }

    total_classify_batches = max(1, (concepts_to_classify + state.batch_size - 1) // state.batch_size)

    manager.update_progress(job_id,
                           items_total=concepts_to_classify,
                           items_processed=0,
                           iteration=0,
                           total_iterations=total_classify_batches,
                           message=f"Starting classification of {concepts_to_classify} concepts...")

    result = asyncio.run(_run_classify_with_progress(
        service, job_id, manager, state
    ))

    phase_result = {
        "success": result.success,
        "items_processed": result.items_processed,
        "items_updated": result.items_updated,
        "execution_time_ms": result.execution_time_ms,
        "details": result.details,
        "suspended": result.details.get("suspended", False)
    }

    return phase_result


def _execute_enrich_relations(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """Execute ENRICH_RELATIONS phase (Pass 2b-2)."""
    # Check feature flag
    pass2_config = get_hybrid_anchor_config("pass2_config", state.tenant_id) or {}
    enabled_phases = pass2_config.get("enabled_phases", [])
    enrich_enabled = "enrich_relations" in enabled_phases

    if not enrich_enabled:
        logger.info(f"[Pass2Worker] ENRICH_RELATIONS skipped for job {job_id}: disabled in feature_flags.yaml")
        return {
            "success": True,
            "items_processed": 0,
            "items_created": 0,
            "execution_time_ms": 0,
            "details": {"skipped": True, "reason": "Disabled in feature_flags.yaml (ADR violation)"}
        }

    try:
        result = asyncio.run(service.run_enrich_relations(state.document_id))
        return {
            "success": result.success,
            "items_processed": result.items_processed,
            "items_created": result.items_created,
            "execution_time_ms": result.execution_time_ms
        }
    except Exception as e:
        logger.error(f"[Pass2Worker] ENRICH_RELATIONS failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _execute_normative_extraction(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """
    Execute NORMATIVE_EXTRACTION phase (Pass 2c).
    Extracts NormativeRule and SpecFact from document segments.
    ADR: ADR_NORMATIVE_RULES_SPEC_FACTS
    """
    from knowbase.ingestion.pass2_orchestrator import (
        Pass2Job, Pass2Stats, Pass2Mode, Pass2Phase, get_pass2_orchestrator
    )

    logger.info(f"[Pass2Worker] NORMATIVE_EXTRACTION starting for job {job_id}")

    try:
        orchestrator = get_pass2_orchestrator(state.tenant_id)
        job = Pass2Job(
            job_id=f"p2_norm_{job_id[:8]}",
            document_id=state.document_id or "all",
            tenant_id=state.tenant_id,
            mode=Pass2Mode.INLINE,
            phases=[Pass2Phase.NORMATIVE_EXTRACTION],
            concepts=[]
        )
        stats = Pass2Stats(document_id=job.document_id)
        asyncio.run(orchestrator._phase_normative_extraction(job, stats))

        result = {
            "success": len(stats.errors) == 0,
            "normative_rules_extracted": stats.normative_rules_extracted,
            "normative_rules_deduplicated": stats.normative_rules_deduplicated,
            "spec_facts_extracted": stats.spec_facts_extracted,
            "spec_facts_deduplicated": stats.spec_facts_deduplicated,
            "errors": stats.errors
        }

        manager.update_progress(job_id,
            message=f"Normative: {stats.normative_rules_extracted} rules, {stats.spec_facts_extracted} facts")
        logger.info(
            f"[Pass2Worker] NORMATIVE_EXTRACTION complete: "
            f"{stats.normative_rules_extracted} rules, {stats.spec_facts_extracted} facts"
        )
        return result

    except Exception as e:
        logger.error(f"[Pass2Worker] NORMATIVE_EXTRACTION failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "errors": [str(e)]}


def _execute_semantic_consolidation(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """
    Execute SEMANTIC_CONSOLIDATION phase (Pass 3).
    Extractive verification with proven relations.
    ADR: ADR_GRAPH_FIRST_ARCHITECTURE
    """
    from knowbase.ingestion.pass2_orchestrator import (
        Pass2Job, Pass2Stats, Pass2Mode, Pass2Phase, get_pass2_orchestrator
    )

    logger.info(f"[Pass2Worker] SEMANTIC_CONSOLIDATION starting for job {job_id}")

    try:
        orchestrator = get_pass2_orchestrator(state.tenant_id)
        job = Pass2Job(
            job_id=f"p2_pass3_{job_id[:8]}",
            document_id=state.document_id or "all",
            tenant_id=state.tenant_id,
            mode=Pass2Mode.INLINE,
            phases=[Pass2Phase.SEMANTIC_CONSOLIDATION],
            concepts=[]
        )
        stats = Pass2Stats(document_id=job.document_id)
        asyncio.run(orchestrator._phase_semantic_consolidation(job, stats))

        result = {
            "success": len(stats.errors) == 0,
            "candidates": stats.pass3_candidates,
            "verified": stats.pass3_verified,
            "abstained": stats.pass3_abstained,
            "errors": stats.errors
        }

        manager.update_progress(job_id,
            message=f"Pass 3: {stats.pass3_verified}/{stats.pass3_candidates} verified, {stats.pass3_abstained} abstained")
        logger.info(
            f"[Pass2Worker] SEMANTIC_CONSOLIDATION complete: "
            f"{stats.pass3_verified}/{stats.pass3_candidates} verified"
        )
        return result

    except Exception as e:
        logger.error(f"[Pass2Worker] SEMANTIC_CONSOLIDATION failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "errors": [str(e)]}


def _execute_corpus_er(
    state: Pass2JobState,
    job_id: str,
    manager: Pass2JobManager,
    service: Any
) -> Dict[str, Any]:
    """Execute CORPUS_ER phase (Entity Resolution)."""
    try:
        result = service.run_corpus_er(dry_run=False)
        phase_result = {
            "success": result.success,
            "items_processed": result.items_processed,
            "items_created": result.items_created,
            "items_updated": result.items_updated,
            "execution_time_ms": result.execution_time_ms,
            "details": result.details
        }

        if result.details:
            manager.update_progress(
                job_id,
                message=f"ER: {result.details.get('auto_merges', 0)} auto-merges, "
                       f"{result.details.get('proposals_created', 0)} proposals"
            )
        return phase_result
    except Exception as e:
        logger.error(f"[Pass2Worker] CORPUS_ER failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# Handler dispatch table
_PHASE_HANDLERS: Dict[str, Any] = {
    "_execute_corpus_promotion": _execute_corpus_promotion,
    "_execute_structural_topics": _execute_structural_topics,
    "_execute_classify_fine": _execute_classify_fine,
    "_execute_enrich_relations": _execute_enrich_relations,
    "_execute_normative_extraction": _execute_normative_extraction,
    "_execute_semantic_consolidation": _execute_semantic_consolidation,
    "_execute_corpus_er": _execute_corpus_er,
}


# =============================================================================
# Main Worker Function - Execute Full Pass2 with Progress
# =============================================================================

def execute_pass2_full_job(job_id: str):
    """
    Fonction worker RQ: Exécute Pass 2 complet avec mise à jour progression.

    Gère:
    - Reprise automatique depuis checkpoint si job suspendu
    - Suspension si vLLM devient indisponible

    Args:
        job_id: ID du job à exécuter
    """
    from knowbase.api.services.pass2_service import Pass2Service, Pass2Result
    from knowbase.ingestion.pass2_orchestrator import Pass2Job, Pass2Stats, Pass2Mode
    from knowbase.ingestion.pass2_orchestrator import Pass2Phase as OrchestratorPhase
    from knowbase.common.llm_router import VLLMUnavailableError

    manager = get_pass2_job_manager()
    state = manager.get_job(job_id)

    if not state:
        logger.error(f"[Pass2Worker] Job {job_id} not found")
        return

    if state.status == Pass2JobStatus.CANCELLED:
        logger.info(f"[Pass2Worker] Job {job_id} was cancelled, skipping")
        return

    # Support reprise depuis état suspendu
    is_resume = state.status == Pass2JobStatus.SUSPENDED
    if is_resume:
        logger.info(
            f"[Pass2Worker] Resuming SUSPENDED job {job_id} from checkpoint "
            f"(phase={state.progress.current_phase}, iteration={state.progress.checkpoint_iteration})"
        )
        manager.resume_job(job_id)
        state = manager.get_job(job_id)
    else:
        manager.start_job(job_id)

    try:
        service = Pass2Service(tenant_id=state.tenant_id)

        # =====================================================================
        # ADR Dynamic Phases: Iterate over enabled_phases from config
        # =====================================================================
        pass2_config = get_hybrid_anchor_config("pass2_config", state.tenant_id) or {}
        enabled_phases = pass2_config.get("enabled_phases", list(PHASE_REGISTRY.keys()))

        # Build effective phase list (respect skip flags)
        effective_phases = []
        for phase_name in enabled_phases:
            config = PHASE_REGISTRY.get(phase_name)
            if not config:
                logger.warning(f"[Pass2Worker] Unknown phase '{phase_name}' in enabled_phases, skipping")
                continue

            # Check skip flag if defined
            if config.skip_flag:
                skip_value = getattr(state, config.skip_flag, False)
                if skip_value:
                    logger.info(f"[Pass2Worker] Phase {phase_name} skipped via {config.skip_flag}")
                    continue

            effective_phases.append(phase_name)

        logger.info(
            f"[Pass2Worker] Job {job_id} executing {len(effective_phases)} phases: "
            f"{effective_phases}"
        )

        phase_results = {}

        # Execute phases dynamically
        for phase_index, phase_name in enumerate(effective_phases):
            # Check cancellation before each phase
            if manager.is_cancelled(job_id):
                logger.info(f"[Pass2Worker] Job {job_id} cancelled before {phase_name}")
                break

            config = PHASE_REGISTRY.get(phase_name)
            if not config:
                continue

            # Update progress with current phase
            manager.update_progress(
                job_id,
                current_phase=config.display_name,
                phase_index=phase_index,
                message=f"Starting {config.display_name}..."
            )

            # Get handler function
            handler = _PHASE_HANDLERS.get(config.handler)
            if not handler:
                logger.error(f"[Pass2Worker] No handler found for {config.handler}")
                phase_results[phase_name] = {"success": False, "error": "No handler"}
                continue

            # Execute handler
            logger.info(f"[Pass2Worker] Executing phase {config.display_name} ({phase_index + 1}/{len(effective_phases)})")
            result = handler(state, job_id, manager, service)

            # Store result
            phase_results[phase_name] = result
            manager.set_phase_result(job_id, phase_name, result)

            # Check for suspension (vLLM down) - only CLASSIFY_FINE supports this
            if result.get("suspended"):
                logger.warning(
                    f"[Pass2Worker] Job {job_id} SUSPENDED during {config.display_name}. "
                    f"Will resume when vLLM is available."
                )
                return  # Don't continue, job is in SUSPENDED state

        # Final cancellation check
        if manager.is_cancelled(job_id):
            return

        manager.complete_job(job_id, phase_results)
        logger.info(f"[Pass2Worker] Job {job_id} completed with {len(phase_results)} phases")

    except Exception as e:
        logger.exception(f"[Pass2Worker] Job {job_id} failed")
        manager.fail_job(job_id, str(e))


async def _run_classify_with_progress(
    service,
    job_id: str,
    manager: Pass2JobManager,
    state: Pass2JobState
):
    """
    Exécute CLASSIFY_FINE avec mise à jour progression Redis.

    Gère:
    - Checkpoint des items traités pour reprise sur incident
    - Suspension automatique si vLLM devient indisponible
    - Reprise depuis le dernier checkpoint

    Args:
        service: Pass2Service instance
        job_id: ID du job pour suivi progression
        manager: Pass2JobManager pour mises à jour
        state: Pass2JobState avec configuration (batch_size, process_all, document_id)
    """
    from knowbase.ingestion.pass2_orchestrator import Pass2Job, Pass2Stats, Pass2Mode
    from knowbase.ingestion.pass2_orchestrator import Pass2Phase as OrchestratorPhase
    from knowbase.api.services.pass2_service import Pass2Result
    from knowbase.common.llm_router import VLLMUnavailableError

    start_time = time.time()
    result = Pass2Result(phase="CLASSIFY_FINE")

    # Récupérer l'état actuel pour checkpoint (reprise possible)
    current_state = manager.get_job(job_id)

    # Initialiser depuis checkpoint si reprise
    processed_item_ids = set(current_state.progress.processed_item_ids if current_state else [])
    start_iteration = current_state.progress.checkpoint_iteration if current_state else 0

    total_processed = current_state.progress.items_processed if current_state else 0
    total_updated = current_state.progress.items_updated if current_state else 0
    total_type_changes = current_state.progress.type_changes if current_state else 0
    iteration = start_iteration

    # Utilise les paramètres du job
    batch_size = state.batch_size
    process_all = state.process_all
    document_id = state.document_id

    # Limite de sécurité: si process_all=False, une seule itération
    max_iterations = 1000 if process_all else 1

    if start_iteration > 0:
        logger.info(
            f"[Pass2Worker] CLASSIFY_FINE resuming from checkpoint: "
            f"iteration={start_iteration}, processed={len(processed_item_ids)} items"
        )

    try:
        while iteration < max_iterations:
            if manager.is_cancelled(job_id):
                result.details["cancelled"] = True
                break

            iteration += 1

            where_clause = "WHERE c.tenant_id = $tenant_id"
            if document_id:
                where_clause += " AND c.source_doc_id = $doc_id"

            # Exclure les items déjà traités (checkpoint)
            exclude_clause = ""
            if processed_item_ids:
                exclude_clause = " AND NOT c.canonical_id IN $processed_ids"

            # Récupérer les concepts à classifier
            # unified_definition et type_coarse sont stockés sur le CanonicalConcept depuis la promotion
            query = f"""
            MATCH (c:CanonicalConcept)
            {where_clause}
            AND (c.type_fine IS NULL OR c.type_fine = ''
                 OR c.type_fine_justification = 'Fallback to heuristic type')
            {exclude_clause}
            RETURN c.canonical_id AS id,
                   c.canonical_name AS label,
                   coalesce(c.type_coarse, 'abstract') AS type_heuristic,
                   coalesce(c.unified_definition, '') AS definition
            LIMIT $limit
            """

            params = {"tenant_id": service.tenant_id, "limit": batch_size}
            if document_id:
                params["doc_id"] = document_id
            if processed_item_ids:
                params["processed_ids"] = list(processed_item_ids)

            concepts = service._execute_query(query, params)
            if not concepts:
                break

            manager.update_progress(
                job_id, iteration=iteration, items_processed=total_processed,
                message=f"Processing batch {iteration} ({len(concepts)} concepts)..."
            )

            concept_dicts = [{
                "id": c["id"],
                "label": c.get("label") or "",
                "type_heuristic": c.get("type_heuristic") or "abstract",
                "definition": c.get("definition") or ""
            } for c in concepts]

            job = Pass2Job(
                job_id=f"p2_classify_{uuid.uuid4().hex[:8]}",
                document_id=document_id or "all",
                tenant_id=service.tenant_id,
                mode=Pass2Mode.INLINE,
                phases=[OrchestratorPhase.CLASSIFY_FINE],
                concepts=concept_dicts
            )

            stats = Pass2Stats(document_id=job.document_id)

            try:
                await service._orchestrator._phase_classify_fine(job, stats)
            except VLLMUnavailableError as e:
                # vLLM down - suspendre le job avec checkpoint
                logger.warning(
                    f"[Pass2Worker] vLLM unavailable during CLASSIFY_FINE: {e}. "
                    f"Suspending job {job_id} with checkpoint."
                )

                # Sauvegarder le checkpoint et suspendre
                manager.suspend_job(
                    job_id=job_id,
                    reason=f"vLLM unavailable: {e.vllm_url}",
                    processed_item_ids=list(processed_item_ids),
                    checkpoint_iteration=iteration - 1  # Reprendre ce batch
                )

                result.success = False
                result.details["suspended"] = True
                result.details["checkpoint_iteration"] = iteration - 1
                result.details["processed_item_ids_count"] = len(processed_item_ids)
                result.errors.append(f"Suspended: vLLM unavailable ({e.vllm_url})")
                result.execution_time_ms = (time.time() - start_time) * 1000
                return result

            batch_updates = 0
            batch_item_ids = []
            for concept in job.concepts:
                batch_item_ids.append(concept["id"])
                if concept.get("type_fine"):
                    service._execute_query("""
                        MATCH (c:CanonicalConcept {canonical_id: $id, tenant_id: $tenant_id})
                        SET c.type_fine = $type_fine,
                            c.type_fine_confidence = $confidence,
                            c.type_fine_justification = $justification
                    """, {
                        "id": concept["id"],
                        "tenant_id": service.tenant_id,
                        "type_fine": concept.get("type_fine"),
                        "confidence": concept.get("type_fine_confidence", 0),
                        "justification": concept.get("type_fine_justification", "")
                    })
                    batch_updates += 1

            # Mettre à jour le checkpoint après chaque batch réussi
            processed_item_ids.update(batch_item_ids)

            total_processed += len(concepts)
            total_updated += batch_updates
            total_type_changes += stats.classify_fine_changes

            manager.update_progress(
                job_id, items_processed=total_processed, items_updated=total_updated,
                type_changes=total_type_changes,
                message=f"Batch {iteration}: {batch_updates} updated, {stats.classify_fine_changes} changes"
            )

        result.items_processed = total_processed
        result.items_updated = total_updated
        result.success = True
        result.details = {
            "iterations": iteration,
            "type_changes": total_type_changes,
            "batch_size": batch_size,
            "process_all": process_all,
            "resumed_from_checkpoint": start_iteration > 0
        }

    except VLLMUnavailableError as e:
        # vLLM down hors de la boucle - suspendre
        logger.warning(
            f"[Pass2Worker] vLLM unavailable: {e}. Suspending job {job_id}."
        )
        manager.suspend_job(
            job_id=job_id,
            reason=f"vLLM unavailable: {e.vllm_url}",
            processed_item_ids=list(processed_item_ids),
            checkpoint_iteration=iteration
        )
        result.success = False
        result.details["suspended"] = True
        result.errors.append(f"Suspended: vLLM unavailable ({e.vllm_url})")

    except Exception as e:
        result.success = False
        result.errors.append(str(e))
        manager.update_progress(job_id, error=str(e))
        logger.exception(f"[Pass2Worker] CLASSIFY_FINE failed: {e}")

    result.execution_time_ms = (time.time() - start_time) * 1000
    return result


def enqueue_pass2_full_job(
    tenant_id: str = "default",
    document_id: Optional[str] = None,
    skip_promotion: bool = False,
    skip_classify: bool = False,
    skip_enrich: bool = False,
    skip_consolidate: bool = False,
    skip_corpus_er: bool = False,
    batch_size: int = 500,
    process_all: bool = True,
    created_by: str = "admin"
) -> Pass2JobState:
    """
    Crée et enqueue un job Pass2 complet.

    Args:
        tenant_id: ID du tenant
        document_id: Optionnel - filtrer par document
        skip_promotion: Ignorer la promotion ProtoConcepts → CanonicalConcepts
        skip_classify: Ignorer la classification
        skip_enrich: Ignorer l'enrichissement relations
        skip_consolidate: Ignorer la consolidation
        skip_corpus_er: Ignorer Entity Resolution corpus-level
        batch_size: Taille des batches de classification (défaut: 500)
        process_all: Si True, traite tous les concepts en boucle (défaut: True)
        created_by: Email du créateur

    Returns:
        Pass2JobState avec job_id pour suivi
    """
    manager = get_pass2_job_manager()

    state = manager.create_job(
        tenant_id=tenant_id,
        document_id=document_id,
        skip_promotion=skip_promotion,
        skip_classify=skip_classify,
        skip_enrich=skip_enrich,
        skip_consolidate=skip_consolidate,
        skip_corpus_er=skip_corpus_er,
        batch_size=batch_size,
        process_all=process_all,
        created_by=created_by
    )

    settings = get_settings()
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
    redis_conn = redis.from_url(redis_url)
    queue = Queue("ingestion", connection=redis_conn)  # Use ingestion queue (worker listens on this)

    queue.enqueue(
        execute_pass2_full_job,
        state.job_id,
        job_timeout="4h",
        result_ttl=86400,
        job_id=f"rq_{state.job_id}"
    )

    logger.info(f"[Pass2Jobs] Enqueued full job {state.job_id}")
    return state


# =============================================================================
# Legacy Functions (kept for compatibility)
# =============================================================================


def process_pass2_queue(
    tenant_id: str = "default",
    max_jobs: int = 10
) -> Dict[str, Any]:
    """
    Job RQ: Traite les jobs Pass 2 en attente.

    Appelé périodiquement par le scheduler RQ.

    Args:
        tenant_id: ID tenant
        max_jobs: Nombre max de jobs à traiter

    Returns:
        Stats d'exécution
    """
    from knowbase.ingestion.pass2_orchestrator import get_pass2_orchestrator

    logger.info(
        f"[OSMOSE:Pass2:Job] Starting background queue processing "
        f"(tenant={tenant_id}, max_jobs={max_jobs})"
    )

    orchestrator = get_pass2_orchestrator(tenant_id=tenant_id)

    # Exécuter dans event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(
            orchestrator.process_background_queue(max_jobs=max_jobs)
        )

        remaining = orchestrator.queue_size
        running = orchestrator.running_jobs

        result = {
            "success": True,
            "jobs_processed": max_jobs,  # Approx
            "queue_remaining": remaining,
            "running_jobs": running
        }

        logger.info(
            f"[OSMOSE:Pass2:Job] Background queue completed: "
            f"{remaining} jobs remaining"
        )

        return result

    except Exception as e:
        logger.error(f"[OSMOSE:Pass2:Job] Background queue failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        loop.close()


def run_pass2_for_document(
    document_id: str,
    concepts: List[Dict[str, Any]],
    tenant_id: str = "default",
    priority: int = 1  # High priority
) -> Dict[str, Any]:
    """
    Job RQ: Exécute Pass 2 immédiatement pour un document.

    Utilisé pour le traitement manuel ou urgent.

    Args:
        document_id: ID document
        concepts: Concepts extraits en Pass 1
        tenant_id: ID tenant
        priority: Priorité du job

    Returns:
        Stats d'exécution Pass 2
    """
    from knowbase.ingestion.pass2_orchestrator import (
        get_pass2_orchestrator,
        Pass2Mode
    )

    logger.info(
        f"[OSMOSE:Pass2:Job] Running Pass 2 for document {document_id} "
        f"({len(concepts)} concepts)"
    )

    orchestrator = get_pass2_orchestrator(tenant_id=tenant_id)

    # Exécuter dans event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        job = loop.run_until_complete(
            orchestrator.schedule_pass2(
                document_id=document_id,
                concepts=concepts,
                mode=Pass2Mode.INLINE,  # Exécution immédiate
                priority=priority
            )
        )

        return {
            "success": True,
            "job_id": job.job_id,
            "document_id": document_id,
            "concepts_processed": len(concepts)
        }

    except Exception as e:
        logger.error(
            f"[OSMOSE:Pass2:Job] Pass 2 failed for {document_id}: {e}",
            exc_info=True
        )
        return {
            "success": False,
            "document_id": document_id,
            "error": str(e)
        }
    finally:
        loop.close()


def scheduled_pass2_consolidation(
    tenant_id: str = "default"
) -> Dict[str, Any]:
    """
    Job RQ: Consolidation nocturne corpus-level.

    Exécute:
    1. Traite tous les jobs scheduled en attente
    2. Consolide RawAssertions → CanonicalRelations
    3. Recalcule scores corpus-level

    À planifier quotidiennement (ex: 02:00 AM).

    Args:
        tenant_id: ID tenant

    Returns:
        Stats de consolidation
    """
    from knowbase.ingestion.pass2_orchestrator import (
        get_pass2_orchestrator,
        Pass2Mode
    )
    from knowbase.relations.relation_consolidator import get_relation_consolidator
    from knowbase.relations.canonical_relation_writer import get_canonical_relation_writer

    logger.info(
        f"[OSMOSE:Pass2:Consolidation] Starting scheduled consolidation "
        f"(tenant={tenant_id})"
    )

    stats = {
        "success": True,
        "scheduled_jobs_processed": 0,
        "raw_assertions_processed": 0,
        "canonical_relations_created": 0,
        "errors": []
    }

    orchestrator = get_pass2_orchestrator(tenant_id=tenant_id)

    # Exécuter dans event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Étape 1: Traiter jobs scheduled
        # Forcer le traitement en changeant temporairement le mode
        initial_queue_size = orchestrator.queue_size

        # Traiter tous les jobs (incluant scheduled)
        loop.run_until_complete(
            orchestrator.process_background_queue(max_jobs=100)
        )

        stats["scheduled_jobs_processed"] = initial_queue_size - orchestrator.queue_size

        # Étape 2: Consolidation globale
        consolidator = get_relation_consolidator(tenant_id=tenant_id)
        consolidator.reset_stats()

        canonical_relations = consolidator.consolidate_all()

        if canonical_relations:
            writer = get_canonical_relation_writer(tenant_id=tenant_id)
            writer.reset_stats()

            for cr in canonical_relations:
                writer.write_canonical_relation(cr)

            writer_stats = writer.get_stats()
            stats["canonical_relations_created"] = writer_stats.get("written", 0)

        consolidator_stats = consolidator.get_stats()
        stats["raw_assertions_processed"] = consolidator_stats.get("groups_processed", 0)

        logger.info(
            f"[OSMOSE:Pass2:Consolidation] Complete: "
            f"{stats['scheduled_jobs_processed']} jobs, "
            f"{stats['canonical_relations_created']} relations"
        )

    except Exception as e:
        logger.error(
            f"[OSMOSE:Pass2:Consolidation] Failed: {e}",
            exc_info=True
        )
        stats["success"] = False
        stats["errors"].append(str(e))

    finally:
        loop.close()

    return stats


def enqueue_pass2_processing(
    document_id: str,
    concepts: List[Dict[str, Any]],
    tenant_id: str = "default"
) -> Optional[str]:
    """
    Ajoute un job Pass 2 à la queue RQ.

    Helper function pour l'ingestion.

    Args:
        document_id: ID document
        concepts: Concepts à traiter
        tenant_id: ID tenant

    Returns:
        Job ID ou None si erreur
    """
    try:
        from knowbase.ingestion.queue.connection import get_queue

        queue = get_queue("pass2")

        job = queue.enqueue(
            run_pass2_for_document,
            document_id=document_id,
            concepts=concepts,
            tenant_id=tenant_id,
            job_timeout="30m",  # 30 min timeout
            result_ttl=86400,  # 24h
            failure_ttl=604800  # 7 jours
        )

        logger.info(
            f"[OSMOSE:Pass2] Enqueued job {job.id} for document {document_id}"
        )

        return job.id

    except Exception as e:
        logger.error(f"[OSMOSE:Pass2] Failed to enqueue: {e}")
        return None


def resume_suspended_jobs(tenant_id: str = "default") -> Dict[str, Any]:
    """
    Vérifie si vLLM est disponible et reprend les jobs suspendus.

    Cette fonction peut être appelée:
    - Périodiquement par un scheduler (ex: toutes les 5 minutes)
    - Manuellement depuis l'admin
    - Automatiquement quand un nouveau burst mode est activé

    Args:
        tenant_id: ID du tenant

    Returns:
        Stats de reprise avec les jobs re-enqueueed
    """
    from knowbase.common.llm_router import get_llm_router

    manager = get_pass2_job_manager()
    stats = {
        "success": True,
        "vllm_available": False,
        "suspended_jobs_found": 0,
        "jobs_resumed": 0,
        "job_ids": [],
        "errors": []
    }

    # Vérifier si vLLM est disponible
    try:
        router = get_llm_router()
        # Force refresh du cache Redis
        router._redis_burst_cache = None
        redis_state = router._get_vllm_state_from_redis()

        if not redis_state or not redis_state.get("active"):
            logger.info("[Pass2Jobs] resume_suspended_jobs: No burst mode configured")
            return stats

        if not redis_state.get("healthy"):
            logger.info(
                f"[Pass2Jobs] resume_suspended_jobs: vLLM still unavailable "
                f"({redis_state.get('vllm_url')})"
            )
            return stats

        stats["vllm_available"] = True
        vllm_url = redis_state.get("vllm_url")
        logger.info(f"[Pass2Jobs] vLLM is available at {vllm_url}, checking for suspended jobs...")

    except Exception as e:
        logger.warning(f"[Pass2Jobs] Error checking vLLM availability: {e}")
        stats["errors"].append(str(e))
        return stats

    # Récupérer les jobs suspendus
    suspended_jobs = manager.get_suspended_jobs(tenant_id)
    stats["suspended_jobs_found"] = len(suspended_jobs)

    if not suspended_jobs:
        logger.info("[Pass2Jobs] No suspended jobs to resume")
        return stats

    # Re-enqueue chaque job suspendu
    settings = get_settings()
    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"
    redis_conn = redis.from_url(redis_url)
    queue = Queue("ingestion", connection=redis_conn)

    for job_state in suspended_jobs:
        try:
            # Enqueue la reprise du job (le worker appellera resume_job via execute_pass2_full_job)
            queue.enqueue(
                execute_pass2_full_job,
                job_state.job_id,
                job_timeout="4h",
                result_ttl=86400,
                job_id=f"rq_{job_state.job_id}_resume"
            )

            stats["jobs_resumed"] += 1
            stats["job_ids"].append(job_state.job_id)

            logger.info(
                f"[Pass2Jobs] Re-enqueued suspended job {job_state.job_id} for resume "
                f"(checkpoint: {len(job_state.progress.processed_item_ids)} items processed)"
            )

        except Exception as e:
            logger.error(f"[Pass2Jobs] Failed to re-enqueue job {job_state.job_id}: {e}")
            stats["errors"].append(f"{job_state.job_id}: {str(e)}")

    logger.info(
        f"[Pass2Jobs] Resume complete: {stats['jobs_resumed']}/{stats['suspended_jobs_found']} "
        f"jobs re-enqueued"
    )

    return stats


def check_vllm_and_resume_jobs(tenant_id: str = "default") -> Dict[str, Any]:
    """
    Job RQ: Vérifie périodiquement vLLM et reprend les jobs suspendus.

    À planifier avec RQ-scheduler (ex: toutes les 2 minutes).

    Args:
        tenant_id: ID du tenant

    Returns:
        Stats d'exécution
    """
    logger.debug("[Pass2Jobs] Periodic vLLM check and resume...")
    return resume_suspended_jobs(tenant_id)


__all__ = [
    # Job Status and State
    "Pass2JobStatus",
    "Pass2JobProgress",
    "Pass2JobState",
    "Pass2JobManager",
    "get_pass2_job_manager",
    # Main job functions
    "execute_pass2_full_job",
    "enqueue_pass2_full_job",
    # Resume/suspension handling
    "resume_suspended_jobs",
    "check_vllm_and_resume_jobs",
    # Legacy functions
    "process_pass2_queue",
    "run_pass2_for_document",
    "scheduled_pass2_consolidation",
    "enqueue_pass2_processing"
]
