from __future__ import annotations

import logging
import os
import sys

import debugpy
from rq import SimpleWorker

# Configure logging at module load - CRITICAL for seeing OSMOSE logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout,
    force=True  # Override any existing config
)

from knowbase.common.clients import (
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)

from .connection import DEFAULT_QUEUE_NAME, get_queue, get_redis_connection


def warm_clients() -> None:
    """Preload shared heavy clients so all jobs reuse the same instances.

    Using SimpleWorker (no fork), we can safely warm all clients including GPU models.
    """
    get_openai_client()
    get_qdrant_client()
    get_sentence_transformer()  # Safe with SimpleWorker (no fork)


def run_worker(*, queue_name: str | None = None, with_scheduler: bool = True) -> None:
    if os.getenv("DEBUG_WORKER") == "true":
        print("🐛 Attaching debugpy to worker on port 5679...")
        debugpy.listen(("0.0.0.0", 5679))
        debugpy.wait_for_client()
        print("🐛 Worker debugger attached!")

    warm_clients()
    queue = get_queue(queue_name)

    # Déterminer le nombre de jobs avant rechargement selon l'environnement
    # En développement : recharger après chaque job pour éviter redémarrages manuels
    # En production : recharger après 10 jobs pour éviter fuites mémoire
    is_dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"
    max_jobs = 1 if is_dev_mode else 10

    logger = logging.getLogger(__name__)
    if is_dev_mode:
        logger.info("🔄 Mode développement activé : rechargement automatique du code après chaque job")

    # IMPORTANT: Use SimpleWorker instead of Worker to avoid fork() with CUDA
    # SimpleWorker runs jobs in the same process (no fork), making it safe for GPU operations
    # Écouter la queue principale + la queue reprocess (séquentiel, pas de concurrence)
    reprocess_queue = get_queue("reprocess")
    worker = SimpleWorker(
        [queue.name, reprocess_queue.name],
        connection=get_redis_connection(),
        job_monitoring_interval=30,  # Vérifier les jobs toutes les 30s au lieu de 10s par défaut
    )

    # Augmenter le délai avant de considérer un worker comme mort
    # Par défaut RQ tue les jobs après 420 secondes (7 minutes) sans heartbeat
    # On augmente à 1800 secondes (30 minutes)
    worker.work(
        with_scheduler=with_scheduler,
        logging_level=logging.INFO,
        max_jobs=max_jobs,  # 1 en dev (auto-reload), 10 en prod (éviter fuites mémoire)
    )


def main() -> None:
    run_worker(queue_name=DEFAULT_QUEUE_NAME)


__all__ = [
    "run_worker",
    "main",
]
