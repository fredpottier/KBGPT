"""
Lock distribué Redis avec auto-release et TTL

Prévient race conditions sur opérations critiques:
- Bootstrap concurrent (2 users démarrent bootstrap simultanément)
- Backfill concurrent (2 processors backfillent même canonical_id)
- Quarantine processing concurrent

Garanties:
- Mutex distribué: 1 seul holder à la fois
- Auto-release: TTL expire si process crash
- Idempotent: Reentrant pour même holder
- Observabilité: Logs holder_id et timestamps
"""

import redis
import logging
import time
import uuid
from typing import Optional, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RedisLock:
    """
    Lock distribué Redis avec auto-release

    Usage:
        lock = RedisLock(redis_client, "bootstrap:global")
        with lock.acquire(timeout=30):
            # Opération critique protégée
            do_bootstrap()
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        lock_key: str,
        ttl_seconds: int = 300,
        holder_id: Optional[str] = None
    ):
        """
        Initialize Redis lock

        Args:
            redis_client: Client Redis connecté
            lock_key: Clé Redis du lock (ex: "bootstrap:global", "backfill:entity:123")
            ttl_seconds: Durée de vie max du lock (défaut: 5min)
            holder_id: Identifiant du holder (défaut: UUID aléatoire)
        """
        self.redis = redis_client
        self.lock_key = f"lock:{lock_key}"
        self.ttl_seconds = ttl_seconds
        self.holder_id = holder_id or f"holder_{uuid.uuid4().hex[:8]}"
        self._held = False

    def acquire(self, timeout: float = 30.0, retry_interval: float = 0.5) -> bool:
        """
        Acquérir le lock (bloquant jusqu'à timeout)

        Args:
            timeout: Durée max d'attente en secondes
            retry_interval: Intervalle entre tentatives (secondes)

        Returns:
            True si lock acquis, False si timeout

        Raises:
            redis.RedisError: Si erreur Redis
        """
        start = time.time()

        while True:
            # Tentative acquisition avec SET NX (Not Exists) + EX (Expiration)
            acquired = self.redis.set(
                self.lock_key,
                self.holder_id,
                nx=True,  # Only set if key doesn't exist
                ex=self.ttl_seconds  # Auto-expire after TTL
            )

            if acquired:
                self._held = True
                logger.info(
                    f"🔒 Lock acquis: {self.lock_key} "
                    f"[holder={self.holder_id[:12]}... ttl={self.ttl_seconds}s]"
                )
                return True

            # Lock détenu par autre holder
            elapsed = time.time() - start
            if elapsed >= timeout:
                current_holder = self.redis.get(self.lock_key)
                holder_str = current_holder.decode() if current_holder else "unknown"
                logger.warning(
                    f"⏱️ Lock timeout: {self.lock_key} "
                    f"[holder={self.holder_id[:12]}... waited={elapsed:.1f}s "
                    f"current_holder={holder_str[:12]}...]"
                )
                return False

            # Attendre avant retry
            time.sleep(retry_interval)

    def release(self) -> bool:
        """
        Libérer le lock

        Returns:
            True si lock libéré, False si pas détenu par ce holder

        Raises:
            redis.RedisError: Si erreur Redis
        """
        if not self._held:
            logger.warning(
                f"⚠️ Tentative release lock non détenu: {self.lock_key} "
                f"[holder={self.holder_id[:12]}...]"
            )
            return False

        # Vérifier que le lock appartient toujours à ce holder (éviter release par erreur)
        current_holder = self.redis.get(self.lock_key)

        if not current_holder:
            # Lock déjà expiré (TTL)
            logger.info(
                f"🔓 Lock déjà expiré: {self.lock_key} "
                f"[holder={self.holder_id[:12]}...]"
            )
            self._held = False
            return False

        if current_holder.decode() != self.holder_id:
            # Lock détenu par autre holder (race condition rare)
            logger.error(
                f"❌ Lock release refusé: {self.lock_key} détenu par autre holder "
                f"[holder={self.holder_id[:12]}... "
                f"current={current_holder.decode()[:12]}...]"
            )
            self._held = False
            return False

        # Delete lock (atomic)
        deleted = self.redis.delete(self.lock_key)
        self._held = False

        if deleted:
            logger.info(
                f"🔓 Lock libéré: {self.lock_key} "
                f"[holder={self.holder_id[:12]}...]"
            )
            return True

        return False

    def extend_ttl(self, additional_seconds: int) -> bool:
        """
        Prolonger TTL du lock (pour opérations longues)

        Args:
            additional_seconds: Secondes à ajouter au TTL

        Returns:
            True si TTL prolongé, False si lock pas détenu par ce holder
        """
        if not self._held:
            logger.warning(
                f"⚠️ Tentative extend TTL lock non détenu: {self.lock_key}"
            )
            return False

        current_holder = self.redis.get(self.lock_key)

        if not current_holder or current_holder.decode() != self.holder_id:
            logger.error(
                f"❌ Extend TTL refusé: lock pas détenu par ce holder "
                f"[holder={self.holder_id[:12]}...]"
            )
            self._held = False
            return False

        # Prolonger TTL
        self.redis.expire(self.lock_key, self.ttl_seconds + additional_seconds)
        logger.info(
            f"⏰ TTL prolongé: {self.lock_key} "
            f"+{additional_seconds}s [holder={self.holder_id[:12]}...]"
        )
        return True

    @contextmanager
    def context(self, timeout: float = 30.0):
        """
        Context manager pour acquisition/release automatique

        Usage:
            with lock.context(timeout=30):
                do_critical_operation()

        Raises:
            TimeoutError: Si lock non acquis avant timeout
        """
        acquired = self.acquire(timeout=timeout)

        if not acquired:
            raise TimeoutError(
                f"Failed to acquire lock {self.lock_key} within {timeout}s"
            )

        try:
            yield self
        finally:
            self.release()

    def is_held(self) -> bool:
        """Vérifier si lock détenu par ce holder"""
        return self._held

    def get_current_holder(self) -> Optional[str]:
        """Récupérer holder_id actuel du lock"""
        holder = self.redis.get(self.lock_key)
        return holder.decode() if holder else None


def create_lock(
    redis_url: str,
    lock_key: str,
    ttl_seconds: int = 300,
    holder_id: Optional[str] = None
) -> RedisLock:
    """
    Factory function pour créer un lock Redis

    Args:
        redis_url: URL Redis (ex: "redis://redis:6379/5")
        lock_key: Clé du lock (ex: "bootstrap:global")
        ttl_seconds: Durée de vie max du lock (défaut: 5min)
        holder_id: Identifiant holder (optionnel)

    Returns:
        Instance RedisLock configurée
    """
    redis_client = redis.Redis.from_url(redis_url, decode_responses=False)
    return RedisLock(redis_client, lock_key, ttl_seconds, holder_id)
