"""
Redis Client pour OSMOSE Architecture Agentique.

Utilisé pour:
- Quotas tracking multi-tenant (budget caps par jour)
- FSM state persistence (optionnel, future)
- Cache (optionnel, future)
- Gate Redis pour vLLM (partage inter-processus)

Author: OSMOSE Phase 1.5
Date: 2025-10-15
"""

import os
import redis
import logging
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _parse_redis_url(redis_url: str) -> Tuple[str, int, int]:
    """
    Parse une URL Redis et retourne (host, port, db).

    Formats supportés:
    - redis://host:port/db
    - redis://host:port
    - redis://host

    Returns:
        Tuple (host, port, db)
    """
    try:
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        # Le path est /db_number, donc on enlève le /
        db = int(parsed.path.lstrip('/')) if parsed.path and parsed.path != '/' else 0
        return host, port, db
    except Exception as e:
        logger.warning(f"[REDIS] Failed to parse REDIS_URL '{redis_url}': {e}")
        return "localhost", 6379, 0


class RedisClient:
    """
    Client Redis pour OSMOSE Agentique.

    Fonctionnalités:
    - Quotas tracking tenant/jour avec TTL 24h
    - Atomic operations (INCR, DECR)
    - Multi-tenant isolation (keys prefixées tenant_id)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        decode_responses: bool = True
    ):
        """
        Initialise client Redis.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (si AUTH activé)
            decode_responses: Auto-decode bytes → str
        """
        self.host = host
        self.port = port
        self.db = db

        try:
            self.client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=decode_responses,
                socket_timeout=5,
                socket_connect_timeout=5
            )

            # Test connexion
            self.client.ping()

            logger.info(f"[REDIS] Connected to {host}:{port} db={db}")

        except redis.ConnectionError as e:
            logger.error(f"[REDIS] Connection failed: {e}")
            self.client = None

        except Exception as e:
            logger.error(f"[REDIS] Initialization error: {e}")
            self.client = None

    def is_connected(self) -> bool:
        """Vérifie si Redis est connecté."""
        if self.client is None:
            return False

        try:
            self.client.ping()
            return True
        except:
            return False

    def get_budget_key(
        self,
        tenant_id: str,
        model_tier: str,
        date: Optional[datetime] = None
    ) -> str:
        """
        Génère clé Redis pour budget quota.

        Format: budget:tenant:{tenant_id}:{tier}:{YYYY-MM-DD}

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            date: Date pour quota (default: aujourd'hui)

        Returns:
            Clé Redis
        """
        if date is None:
            date = datetime.utcnow()

        date_str = date.strftime("%Y-%m-%d")

        return f"budget:tenant:{tenant_id}:{model_tier}:{date_str}"

    def get_budget_cost_key(
        self,
        tenant_id: str,
        model_tier: str,
        date: Optional[datetime] = None
    ) -> str:
        """
        Génère clé Redis pour budget cost tracking.

        Format: budget:tenant:{tenant_id}:{tier}:{YYYY-MM-DD}:cost

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            date: Date pour quota (default: aujourd'hui)

        Returns:
            Clé Redis
        """
        base_key = self.get_budget_key(tenant_id, model_tier, date)
        return f"{base_key}:cost"

    def get_budget_consumed(
        self,
        tenant_id: str,
        model_tier: str,
        date: Optional[datetime] = None
    ) -> int:
        """
        Récupère nombre d'appels LLM consommés pour tenant/tier/jour.

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            date: Date pour quota (default: aujourd'hui)

        Returns:
            Nombre appels consommés (0 si key inexistante)
        """
        if not self.is_connected():
            logger.warning("[REDIS] Not connected, returning 0")
            return 0

        key = self.get_budget_key(tenant_id, model_tier, date)

        try:
            value = self.client.get(key)
            return int(value) if value else 0

        except Exception as e:
            logger.error(f"[REDIS] get_budget_consumed error: {e}")
            return 0

    def increment_budget(
        self,
        tenant_id: str,
        model_tier: str,
        calls: int = 1,
        cost: float = 0.0,
        ttl_seconds: int = 86400  # 24h
    ) -> int:
        """
        Incrémente compteur budget (atomic).

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            calls: Nombre d'appels à incrémenter
            cost: Coût à ajouter ($)
            ttl_seconds: TTL pour auto-expiration (default 24h)

        Returns:
            Nouvelle valeur après incrément
        """
        if not self.is_connected():
            logger.warning("[REDIS] Not connected, skipping increment")
            return 0

        key = self.get_budget_key(tenant_id, model_tier)
        cost_key = self.get_budget_cost_key(tenant_id, model_tier)

        try:
            # Pipeline pour atomicité
            pipe = self.client.pipeline()

            # Incrémenter calls
            pipe.incrby(key, calls)
            pipe.expire(key, ttl_seconds)

            # Incrémenter cost (si > 0)
            if cost > 0.0:
                pipe.incrbyfloat(cost_key, cost)
                pipe.expire(cost_key, ttl_seconds)

            results = pipe.execute()

            new_value = results[0]  # Première commande (INCRBY)

            logger.debug(
                f"[REDIS] Budget incremented: {tenant_id}/{model_tier} "
                f"+{calls} calls, +${cost:.3f} → {new_value} total"
            )

            return new_value

        except Exception as e:
            logger.error(f"[REDIS] increment_budget error: {e}")
            return 0

    def decrement_budget(
        self,
        tenant_id: str,
        model_tier: str,
        calls: int = 1,
        cost: float = 0.0
    ) -> int:
        """
        Décremente compteur budget (refund).

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            calls: Nombre d'appels à décrémenter
            cost: Coût à retirer ($)

        Returns:
            Nouvelle valeur après décrément
        """
        if not self.is_connected():
            logger.warning("[REDIS] Not connected, skipping decrement")
            return 0

        key = self.get_budget_key(tenant_id, model_tier)
        cost_key = self.get_budget_cost_key(tenant_id, model_tier)

        try:
            # Pipeline pour atomicité
            pipe = self.client.pipeline()

            # Décrémenter calls
            pipe.decrby(key, calls)

            # Décrémenter cost (si > 0)
            if cost > 0.0:
                pipe.incrbyfloat(cost_key, -cost)  # Incrément négatif

            results = pipe.execute()

            new_value = results[0]

            logger.debug(
                f"[REDIS] Budget decremented (refund): {tenant_id}/{model_tier} "
                f"-{calls} calls, -${cost:.3f} → {new_value} total"
            )

            return new_value

        except Exception as e:
            logger.error(f"[REDIS] decrement_budget error: {e}")
            return 0

    def get_budget_stats(
        self,
        tenant_id: str,
        model_tier: str,
        date: Optional[datetime] = None
    ) -> Dict[str, float]:
        """
        Récupère statistiques budget pour tenant/tier/jour.

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            date: Date pour quota (default: aujourd'hui)

        Returns:
            Dict avec calls, cost
        """
        if not self.is_connected():
            logger.warning("[REDIS] Not connected, returning empty stats")
            return {"calls": 0, "cost": 0.0}

        key = self.get_budget_key(tenant_id, model_tier, date)
        cost_key = self.get_budget_cost_key(tenant_id, model_tier, date)

        try:
            # Récupérer calls et cost en parallèle
            pipe = self.client.pipeline()
            pipe.get(key)
            pipe.get(cost_key)
            results = pipe.execute()

            calls = int(results[0]) if results[0] else 0
            cost = float(results[1]) if results[1] else 0.0

            return {
                "calls": calls,
                "cost": cost
            }

        except Exception as e:
            logger.error(f"[REDIS] get_budget_stats error: {e}")
            return {"calls": 0, "cost": 0.0}

    def reset_budget(
        self,
        tenant_id: str,
        model_tier: str,
        date: Optional[datetime] = None
    ) -> bool:
        """
        Reset budget pour tenant/tier/jour (admin uniquement).

        Args:
            tenant_id: ID tenant
            model_tier: SMALL, BIG, VISION
            date: Date pour quota (default: aujourd'hui)

        Returns:
            True si reset OK
        """
        if not self.is_connected():
            logger.warning("[REDIS] Not connected, skipping reset")
            return False

        key = self.get_budget_key(tenant_id, model_tier, date)
        cost_key = self.get_budget_cost_key(tenant_id, model_tier, date)

        try:
            pipe = self.client.pipeline()
            pipe.delete(key)
            pipe.delete(cost_key)
            pipe.execute()

            logger.info(f"[REDIS] Budget reset: {tenant_id}/{model_tier}")

            return True

        except Exception as e:
            logger.error(f"[REDIS] reset_budget error: {e}")
            return False


# Singleton instance
_redis_client: Optional[RedisClient] = None


def get_redis_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
    db: Optional[int] = None,
    password: Optional[str] = None
) -> RedisClient:
    """
    Récupère instance singleton Redis client.

    La configuration est lue depuis la variable d'environnement REDIS_URL si disponible,
    sinon utilise les paramètres fournis ou localhost:6379.

    Args:
        host: Redis host (override REDIS_URL si fourni)
        port: Redis port (override REDIS_URL si fourni)
        db: Redis database (override REDIS_URL si fourni)
        password: Redis password

    Returns:
        RedisClient instance
    """
    global _redis_client

    if _redis_client is None:
        # Lire REDIS_URL depuis l'environnement si aucun paramètre explicite
        redis_url = os.environ.get("REDIS_URL")

        if redis_url and host is None and port is None:
            # Utiliser REDIS_URL
            parsed_host, parsed_port, parsed_db = _parse_redis_url(redis_url)
            host = parsed_host
            port = parsed_port
            db = parsed_db if db is None else db
            logger.debug(f"[REDIS] Using REDIS_URL: {host}:{port}/{db}")
        else:
            # Utiliser les valeurs par défaut
            host = host or "localhost"
            port = port or 6379
            db = db if db is not None else 0

        _redis_client = RedisClient(
            host=host,
            port=port,
            db=db,
            password=password
        )

    return _redis_client
