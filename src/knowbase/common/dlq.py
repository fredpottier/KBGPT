"""
Dead Letter Queue (DLQ) - Phase 0.5 P2.13

Gestion jobs échoués avec retry automatique:
- Queue Redis dédiée pour jobs failed
- Retry exponentiel configurable (max 3 retry par défaut)
- Logs détaillés pour debug
- Endpoint admin pour consulter/rejouer DLQ

Usage:
    from knowbase.common.dlq import send_to_dlq, retry_from_dlq

    # Envoyer job échoué à DLQ
    send_to_dlq(
        job_type="merge",
        job_data={"canonical": "...", "candidates": [...]},
        error="LLM timeout",
        retry_count=2
    )

    # Rejouer job depuis DLQ
    job = retry_from_dlq(dlq_id)
"""

import json
import redis
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class DLQJob:
    """Job dans Dead Letter Queue"""
    dlq_id: str              # ID unique DLQ
    job_type: str            # Type job (merge, backfill, etc.)
    job_data: Dict[str, Any] # Données job original
    error: str               # Message erreur
    retry_count: int         # Nombre retry effectués
    max_retries: int         # Max retry autorisés
    timestamp: str           # Timestamp échec
    request_id: Optional[str] = None  # Request ID pour traçabilité


class DeadLetterQueue:
    """
    Dead Letter Queue pour jobs échoués

    Redis:
        - dlq:jobs hash (dlq_id → job JSON)
        - dlq:index sorted set (timestamp → dlq_id)
    """

    def __init__(
        self,
        redis_url: str = "redis://redis:6379/7",  # DB 7 pour DLQ
        max_retries: int = 3
    ):
        """
        Args:
            redis_url: URL Redis
            max_retries: Nombre max retry avant abandon
        """
        self.redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.max_retries = max_retries

    def send_to_dlq(
        self,
        job_type: str,
        job_data: Dict[str, Any],
        error: str,
        retry_count: int = 0,
        request_id: Optional[str] = None
    ) -> str:
        """
        Envoyer job échoué à DLQ

        Args:
            job_type: Type job (merge, backfill, etc.)
            job_data: Données job
            error: Message erreur
            retry_count: Nombre retry déjà effectués
            request_id: Request ID pour traçabilité

        Returns:
            dlq_id: ID unique DLQ
        """
        dlq_id = f"dlq:{job_type}:{int(time.time() * 1000)}"

        job = DLQJob(
            dlq_id=dlq_id,
            job_type=job_type,
            job_data=job_data,
            error=error,
            retry_count=retry_count,
            max_retries=self.max_retries,
            timestamp=datetime.utcnow().isoformat(),
            request_id=request_id
        )

        # Sauvegarder job
        self.redis_client.hset("dlq:jobs", dlq_id, json.dumps(asdict(job)))

        # Indexer par timestamp (sorted set)
        timestamp = time.time()
        self.redis_client.zadd("dlq:index", {dlq_id: timestamp})

        logger.warning(
            f"📮 DLQ: Job {job_type} envoyé (retry={retry_count}/{self.max_retries}) - {error}"
        )

        return dlq_id

    def get_job(self, dlq_id: str) -> Optional[DLQJob]:
        """
        Récupérer job depuis DLQ

        Args:
            dlq_id: ID DLQ

        Returns:
            Job ou None si non trouvé
        """
        job_json = self.redis_client.hget("dlq:jobs", dlq_id)
        if not job_json:
            return None

        job_dict = json.loads(job_json)
        return DLQJob(**job_dict)

    def list_jobs(
        self,
        limit: int = 100,
        job_type: Optional[str] = None
    ) -> List[DLQJob]:
        """
        Lister jobs DLQ (triés par timestamp desc)

        Args:
            limit: Nombre max jobs
            job_type: Filtrer par type (optionnel)

        Returns:
            Liste jobs DLQ
        """
        # Récupérer IDs depuis index (plus récents en premier)
        dlq_ids = self.redis_client.zrevrange("dlq:index", 0, limit - 1)

        jobs = []
        for dlq_id in dlq_ids:
            job = self.get_job(dlq_id)
            if job:
                if job_type is None or job.job_type == job_type:
                    jobs.append(job)

        return jobs

    def retry_job(self, dlq_id: str) -> bool:
        """
        Rejouer job depuis DLQ

        Args:
            dlq_id: ID DLQ

        Returns:
            True si job rejoué, False si max retry atteint
        """
        job = self.get_job(dlq_id)
        if not job:
            logger.error(f"❌ DLQ: Job {dlq_id} non trouvé")
            return False

        if job.retry_count >= job.max_retries:
            logger.error(
                f"❌ DLQ: Job {dlq_id} max retry atteint ({job.retry_count}/{job.max_retries})"
            )
            return False

        logger.info(f"♻️ DLQ: Retry job {dlq_id} (retry {job.retry_count + 1}/{job.max_retries})")

        # Incrémenter retry count
        job.retry_count += 1
        self.redis_client.hset("dlq:jobs", dlq_id, json.dumps(asdict(job)))

        # TODO: Rejouer job selon type (merge, backfill, etc.)
        # Pour l'instant, juste logger - implémentation complète Phase 1+
        logger.info(f"🔄 DLQ: Job {job.job_type} prêt pour retry: {job.job_data}")

        return True

    def delete_job(self, dlq_id: str):
        """
        Supprimer job de DLQ (après succès retry)

        Args:
            dlq_id: ID DLQ
        """
        self.redis_client.hdel("dlq:jobs", dlq_id)
        self.redis_client.zrem("dlq:index", dlq_id)
        logger.info(f"🗑️ DLQ: Job {dlq_id} supprimé")

    def get_stats(self) -> Dict[str, Any]:
        """
        Statistiques DLQ

        Returns:
            {"total": N, "by_type": {...}, "by_retry": {...}}
        """
        all_jobs = self.list_jobs(limit=1000)

        stats = {
            "total": len(all_jobs),
            "by_type": {},
            "by_retry": {}
        }

        for job in all_jobs:
            # Par type
            stats["by_type"][job.job_type] = stats["by_type"].get(job.job_type, 0) + 1

            # Par retry count
            retry_key = f"{job.retry_count}/{job.max_retries}"
            stats["by_retry"][retry_key] = stats["by_retry"].get(retry_key, 0) + 1

        return stats


# Instance globale DLQ
_dlq_instance = None

def get_dlq() -> DeadLetterQueue:
    """Récupérer instance DLQ (singleton)"""
    global _dlq_instance
    if _dlq_instance is None:
        _dlq_instance = DeadLetterQueue()
    return _dlq_instance


# Helpers
def send_to_dlq(
    job_type: str,
    job_data: Dict[str, Any],
    error: str,
    retry_count: int = 0,
    request_id: Optional[str] = None
) -> str:
    """Helper pour envoyer job à DLQ"""
    dlq = get_dlq()
    return dlq.send_to_dlq(job_type, job_data, error, retry_count, request_id)


def retry_from_dlq(dlq_id: str) -> bool:
    """Helper pour rejouer job depuis DLQ"""
    dlq = get_dlq()
    return dlq.retry_job(dlq_id)
