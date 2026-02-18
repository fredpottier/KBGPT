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


def _restore_burst_state() -> None:
    """Restaure le burst mode depuis Redis ou le fichier persistant /data.

    get_burst_state_from_redis() vérifie Redis puis fallback sur le fichier
    .burst_state.json sur le volume /data (survit aux rebuilds et évictions Redis).
    Si un état est trouvé et vLLM est accessible, active le burst mode.
    """
    logger = logging.getLogger(__name__)
    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis,
            activate_burst_providers,
        )

        state = get_burst_state_from_redis()
        if not state or not state.get("active"):
            logger.info("[WORKER:STARTUP] No active burst state (Redis + file empty)")
            return

        vllm_url = state.get("vllm_url")
        embeddings_url = state.get("embeddings_url")
        vllm_model = state.get("vllm_model")
        logger.info(
            f"[WORKER:STARTUP] Burst state found: "
            f"vLLM={vllm_url}, model={vllm_model}"
        )

        # Vérifier que vLLM est accessible avant d'activer
        try:
            import requests
            resp = requests.get(f"{vllm_url.rstrip('/')}/health", timeout=5)
            if not resp.ok:
                logger.warning(f"[WORKER:STARTUP] vLLM not healthy at {vllm_url}, skipping burst")
                return
        except Exception as e:
            logger.warning(f"[WORKER:STARTUP] vLLM unreachable at {vllm_url}: {e}, skipping burst")
            return

        result = activate_burst_providers(
            vllm_url=vllm_url,
            embeddings_url=embeddings_url,
            vllm_model=vllm_model,
        )
        if result.get("llm_router"):
            logger.info("[WORKER:STARTUP] Burst mode restored successfully")
        else:
            logger.warning(
                f"[WORKER:STARTUP] Burst mode restore partial: {result}"
            )
    except Exception as e:
        logger.warning(f"[WORKER:STARTUP] Failed to restore burst state: {e}")


def warm_clients() -> None:
    """Preload shared heavy clients so all jobs reuse the same instances.

    Using SimpleWorker (no fork), we can safely warm all clients including GPU models.
    """
    get_openai_client()
    get_qdrant_client()
    get_sentence_transformer()  # Safe with SimpleWorker (no fork)
    _restore_burst_state()


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
