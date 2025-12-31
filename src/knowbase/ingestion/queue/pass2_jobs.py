"""
Pass 2 Background Jobs for RQ Queue.

Jobs pour le traitement asynchrone de Pass 2:
- process_pass2_queue: Traite les jobs Pass 2 en attente
- run_pass2_for_document: Exécute Pass 2 pour un document spécifique
- scheduled_pass2_consolidation: Batch nocturne pour consolidation

Author: OSMOSE Phase 2
Date: 2024-12
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional

from rq import get_current_job

logger = logging.getLogger(__name__)


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


__all__ = [
    "process_pass2_queue",
    "run_pass2_for_document",
    "scheduled_pass2_consolidation",
    "enqueue_pass2_processing"
]
