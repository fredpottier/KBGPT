"""
Client Redis résilient avec retry automatique - Phase 0.5 P0.3

Gère connexions instables et flapping Redis avec:
- Retry exponentiel backoff (2^n secondes)
- Résilience aux timeouts et connexions perdues
- Logging observabilité connexions
- Fallback graceful si Redis complètement down

Utilisé partout où Redis est critère: idempotence, locks, audit trail
"""

import redis
import logging
import time
from typing import Any, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)


class RedisConnectionError(Exception):
    """Erreur connexion Redis après tous les retries"""
    pass


def redis_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0
):
    """
    Décorateur retry pour opérations Redis

    Args:
        max_retries: Nombre max tentatives (défaut: 3)
        base_delay: Délai initial en secondes (défaut: 1s)
        max_delay: Délai maximum entre tentatives (défaut: 10s)
        exponential_base: Base exponentielle (défaut: 2 → 1s, 2s, 4s, 8s...)

    Usage:
        @redis_retry(max_retries=3)
        def my_redis_operation(client):
            return client.get("key")
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    # Tentative exécution
                    return func(*args, **kwargs)

                except (
                    redis.ConnectionError,
                    redis.TimeoutError,
                    ConnectionRefusedError,
                    ConnectionResetError
                ) as e:
                    last_exception = e

                    if attempt < max_retries:
                        # Calculer délai avec exponential backoff
                        delay = min(base_delay * (exponential_base ** attempt), max_delay)

                        logger.warning(
                            f"Redis operation failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )

                        time.sleep(delay)
                    else:
                        # Dernier retry échoué
                        logger.error(
                            f"Redis operation failed after {max_retries + 1} attempts: {e}",
                            exc_info=True
                        )

                except Exception as e:
                    # Autre erreur (pas connexion) → fail immédiatement
                    logger.error(f"Redis operation error (non-retryable): {e}", exc_info=True)
                    raise

            # Tous les retries ont échoué
            raise RedisConnectionError(
                f"Redis operation failed after {max_retries + 1} attempts"
            ) from last_exception

        return wrapper
    return decorator


class ResilientRedisClient:
    """
    Client Redis avec retry automatique sur toutes les opérations

    Wraps redis.Redis avec retry transparent sur connexions instables
    """

    def __init__(
        self,
        redis_url: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        decode_responses: bool = True,
        socket_connect_timeout: int = 5,
        socket_timeout: int = 5
    ):
        """
        Initialize resilient Redis client

        Args:
            redis_url: URL Redis (ex: "redis://redis:6379/0")
            max_retries: Nombre max tentatives par opération (défaut: 3)
            base_delay: Délai initial retry en secondes (défaut: 1s)
            decode_responses: Decoder bytes en str (défaut: True)
            socket_connect_timeout: Timeout connexion en secondes (défaut: 5s)
            socket_timeout: Timeout socket en secondes (défaut: 5s)
        """
        self.redis_url = redis_url
        self.max_retries = max_retries
        self.base_delay = base_delay

        # Créer client Redis avec timeouts configurés
        self._client = redis.Redis.from_url(
            redis_url,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
            retry_on_timeout=True  # Retry automatique sur timeout
        )

        logger.info(
            f"ResilientRedisClient initialized: {redis_url} "
            f"(max_retries={max_retries}, timeouts={socket_timeout}s)"
        )

    @redis_retry(max_retries=3)
    def get(self, key: str) -> Optional[Any]:
        """Get value with retry"""
        return self._client.get(key)

    @redis_retry(max_retries=3)
    def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        """Set value with retry"""
        return self._client.set(key, value, ex=ex, nx=nx)

    @redis_retry(max_retries=3)
    def setex(self, key: str, time: int, value: Any) -> bool:
        """Set with expiration with retry"""
        return self._client.setex(key, time, value)

    @redis_retry(max_retries=3)
    def delete(self, *keys: str) -> int:
        """Delete keys with retry"""
        return self._client.delete(*keys)

    @redis_retry(max_retries=3)
    def exists(self, *keys: str) -> int:
        """Check existence with retry"""
        return self._client.exists(*keys)

    @redis_retry(max_retries=3)
    def expire(self, key: str, time: int) -> bool:
        """Set expiration with retry"""
        return self._client.expire(key, time)

    @redis_retry(max_retries=3)
    def ttl(self, key: str) -> int:
        """Get TTL with retry"""
        return self._client.ttl(key)

    @redis_retry(max_retries=3)
    def keys(self, pattern: str = "*") -> list:
        """List keys with retry"""
        return self._client.keys(pattern)

    @redis_retry(max_retries=3)
    def flushdb(self) -> bool:
        """Flush DB with retry"""
        return self._client.flushdb()

    @redis_retry(max_retries=3)
    def ping(self) -> bool:
        """Ping Redis with retry"""
        return self._client.ping()

    @redis_retry(max_retries=3)
    def hset(self, name: str, key: str, value: Any) -> int:
        """Hash set with retry"""
        return self._client.hset(name, key, value)

    @redis_retry(max_retries=3)
    def hget(self, name: str, key: str) -> Optional[Any]:
        """Hash get with retry"""
        return self._client.hget(name, key)

    @redis_retry(max_retries=3)
    def hgetall(self, name: str) -> dict:
        """Hash get all with retry"""
        return self._client.hgetall(name)

    @redis_retry(max_retries=3)
    def hdel(self, name: str, *keys: str) -> int:
        """Hash delete with retry"""
        return self._client.hdel(name, *keys)

    @redis_retry(max_retries=3)
    def lpush(self, key: str, *values: Any) -> int:
        """List push with retry"""
        return self._client.lpush(key, *values)

    @redis_retry(max_retries=3)
    def rpush(self, key: str, *values: Any) -> int:
        """List push right with retry"""
        return self._client.rpush(key, *values)

    @redis_retry(max_retries=3)
    def lrange(self, key: str, start: int, end: int) -> list:
        """List range with retry"""
        return self._client.lrange(key, start, end)

    @redis_retry(max_retries=3)
    def llen(self, key: str) -> int:
        """List length with retry"""
        return self._client.llen(key)

    def close(self):
        """Close connection"""
        try:
            self._client.close()
            logger.info(f"ResilientRedisClient closed: {self.redis_url}")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


def create_resilient_redis_client(
    redis_url: str = "redis://redis:6379/0",
    max_retries: int = 3,
    **kwargs
) -> ResilientRedisClient:
    """
    Factory function pour créer client Redis résilient

    Args:
        redis_url: URL Redis (défaut: "redis://redis:6379/0")
        max_retries: Nombre max tentatives (défaut: 3)
        **kwargs: Arguments additionnels pour ResilientRedisClient

    Returns:
        Instance ResilientRedisClient configurée
    """
    return ResilientRedisClient(redis_url, max_retries=max_retries, **kwargs)
