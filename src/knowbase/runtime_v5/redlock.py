"""V5 DSG — Redlock distribué Redis pour l'ingestion concurrente.

ADR V1.5 §3c (Sprint S2.2) : 1 seul job peut ingérer le même `(tenant_id, doc_id)`
à la fois. Les autres attendent (wait_timeout) ou échouent proprement.

Pattern utilisé : **Redlock single-instance** (le single-instance Redlock, pas le
multi-node distributed Redlock à 5 nodes décrit par Antirez). Suffit pour OSMOSE
qui a 1 seul Redis. Documentation :
- https://redis.io/docs/manual/patterns/distributed-locks/

Mécanique :
- ACQUIRE : `SET key fencing_token NX PX timeout_ms` (atomic, NX = only if not exist)
- RELEASE : Lua script qui vérifie le fencing_token AVANT DEL (anti-vol de lock)
- EXTEND : Lua script qui vérifie le fencing_token AVANT PEXPIRE
- WAIT  : retry exponentiel avec jitter jusqu'à wait_timeout

Fencing token : UUID4 unique par appel acquire(). Empêche un client qui aurait
pris du retard (GC pause, etc.) de release un lock désormais possédé par un
autre client.

Usage :
    from knowbase.runtime_v5.redlock import RedlockClient

    redlock = RedlockClient(redis_client)
    with redlock.lock(tenant_id="default", doc_id="003_xxx", timeout_s=300):
        # Section critique : 1 seul job au monde peut être ici à la fois
        # pour ce (tenant_id, doc_id)
        ...
    # auto-release à la sortie du with

Limitation single-instance : si Redis crash, les locks sont perdus et 2 jobs
peuvent ingérer en parallèle. Pour OSMOSE c'est acceptable car :
- Two-phase publish (S2.3) garantit atomicité par doc_version
- Composite key Neo4j refuse les doublons
- Redis persistence AOF + RDB minimise le risque
"""
from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


# Lua scripts (atomic check-and-act) — chargés une fois par instance
LUA_RELEASE = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

LUA_EXTEND = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


class LockAcquireTimeout(Exception):
    """Levée quand acquire() dépasse wait_timeout sans obtenir le lock."""
    pass


class LockReleaseError(Exception):
    """Levée quand release() ne trouve pas le lock (volé, expiré, ou inexistant)."""
    pass


class RedlockClient:
    """Client Redlock single-instance pour ingestion concurrente.

    Args:
        redis_client: instance `RedisClient` (knowbase.common.clients.redis_client)
                      OU directement un `redis.Redis` (duck-typed)
        key_prefix: préfixe Redis pour isoler les locks V5 (default "v5dsg:lock:")
    """

    DEFAULT_TIMEOUT_S = 300  # 5 min : durée max d'ingestion d'1 doc
    DEFAULT_WAIT_S = 0  # 0 = fail-fast sur conflit
    EXTEND_HEARTBEAT_S = 60  # auto-extend toutes les 60s si encore actif

    def __init__(self, redis_client, key_prefix: str = "v5dsg:lock:"):
        # Support 2 formes : RedisClient wrapper OU redis.Redis direct
        if hasattr(redis_client, "client") and redis_client.client is not None:
            self._raw = redis_client.client
        else:
            self._raw = redis_client
        self.key_prefix = key_prefix
        # Pré-charge Lua scripts (SHA1 cached côté Redis)
        self._sha_release = self._raw.script_load(LUA_RELEASE)
        self._sha_extend = self._raw.script_load(LUA_EXTEND)

    def _key(self, tenant_id: str, doc_id: str) -> str:
        return f"{self.key_prefix}{tenant_id}:{doc_id}"

    def acquire(
        self,
        tenant_id: str,
        doc_id: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        wait_s: float = DEFAULT_WAIT_S,
    ) -> str:
        """Acquiert le lock sur `(tenant_id, doc_id)`.

        Args:
            tenant_id: tenant isolation key
            doc_id: doc ID
            timeout_s: durée max du lock (auto-expire après ce délai)
            wait_s: temps max à attendre avant de raise LockAcquireTimeout.
                    0 = fail-fast. >0 = retry avec backoff jusqu'au timeout.

        Returns:
            fencing_token (str UUID4) à passer à release() / extend()

        Raises:
            LockAcquireTimeout si le lock n'est pas obtenu dans wait_s
        """
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id required")

        key = self._key(tenant_id, doc_id)
        token = str(uuid.uuid4())
        timeout_ms = int(timeout_s * 1000)

        deadline = time.monotonic() + wait_s
        backoff = 0.05  # 50ms initial
        backoff_max = 1.0

        while True:
            # SET key token NX PX timeout_ms : atomic acquire
            ok = self._raw.set(key, token, nx=True, px=timeout_ms)
            if ok:
                logger.info(
                    f"[Redlock] ACQUIRED key={key} token={token[:8]}... "
                    f"timeout={timeout_s}s"
                )
                return token

            if time.monotonic() >= deadline:
                # Échec : essayons de connaître le possesseur (info diagnostic)
                holder = self._raw.get(key)
                holder_preview = (holder[:8] + "...") if holder else "<expired>"
                raise LockAcquireTimeout(
                    f"Lock {key} held by {holder_preview} (wait={wait_s}s expired)"
                )

            # Wait avec jitter pour éviter thundering herd
            sleep_for = min(backoff + secrets.randbelow(50) / 1000.0, backoff_max)
            time.sleep(sleep_for)
            backoff = min(backoff * 2, backoff_max)

    def release(self, tenant_id: str, doc_id: str, token: str) -> bool:
        """Release le lock SI le fencing_token correspond.

        Args:
            tenant_id: tenant isolation key
            doc_id: doc ID
            token: fencing_token obtenu via acquire()

        Returns:
            True si le lock a bien été libéré (token matched + DEL OK)
            False si le lock avait déjà expiré OU était possédé par un autre token

        Note : pas d'exception si False — c'est un cas légitime (lock expiré
        naturellement, on a juste pris trop de temps).
        """
        if not tenant_id or not doc_id or not token:
            raise ValueError("tenant_id, doc_id, token required")
        key = self._key(tenant_id, doc_id)
        try:
            result = self._raw.evalsha(self._sha_release, 1, key, token)
        except Exception as e:
            # Script may have been flushed — reload and retry once
            logger.warning(f"[Redlock] evalsha failed, reloading script: {e}")
            self._sha_release = self._raw.script_load(LUA_RELEASE)
            result = self._raw.evalsha(self._sha_release, 1, key, token)
        released = bool(result)
        if released:
            logger.info(f"[Redlock] RELEASED key={key} token={token[:8]}...")
        else:
            logger.warning(
                f"[Redlock] release NOOP key={key} token={token[:8]}... "
                f"(lock expired or stolen)"
            )
        return released

    def extend(
        self, tenant_id: str, doc_id: str, token: str, timeout_s: int
    ) -> bool:
        """Prolonge le TTL du lock SI le fencing_token correspond.

        Useful pour heartbeat pendant des opérations longues.

        Returns:
            True si extension OK, False si lock perdu (expiré ou volé)
        """
        if not tenant_id or not doc_id or not token:
            raise ValueError("tenant_id, doc_id, token required")
        key = self._key(tenant_id, doc_id)
        timeout_ms = int(timeout_s * 1000)
        try:
            result = self._raw.evalsha(
                self._sha_extend, 1, key, token, timeout_ms
            )
        except Exception as e:
            logger.warning(f"[Redlock] evalsha extend failed, reloading: {e}")
            self._sha_extend = self._raw.script_load(LUA_EXTEND)
            result = self._raw.evalsha(
                self._sha_extend, 1, key, token, timeout_ms
            )
        return bool(result)

    def is_locked(self, tenant_id: str, doc_id: str) -> bool:
        """Vérifie si un lock est actif (info diagnostic)."""
        key = self._key(tenant_id, doc_id)
        return bool(self._raw.exists(key))

    def get_holder_token(self, tenant_id: str, doc_id: str) -> Optional[str]:
        """Renvoie le fencing_token actuel (None si pas de lock)."""
        return self._raw.get(self._key(tenant_id, doc_id))

    @contextmanager
    def lock(
        self,
        tenant_id: str,
        doc_id: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        wait_s: float = DEFAULT_WAIT_S,
    ):
        """Context manager : acquire + auto-release.

        Yields:
            fencing_token (utile pour passer à extend() pendant l'opération)

        Raises:
            LockAcquireTimeout si pas obtenu dans wait_s

        Usage :
            with redlock.lock("default", "doc_xxx") as token:
                # operations ingestion
                if took_long_time:
                    redlock.extend("default", "doc_xxx", token, 300)
        """
        token = self.acquire(tenant_id, doc_id, timeout_s=timeout_s, wait_s=wait_s)
        try:
            yield token
        finally:
            self.release(tenant_id, doc_id, token)


# ─── Singleton factory ───────────────────────────────────────────────────────

_default_redlock: Optional[RedlockClient] = None


def get_redlock_client() -> RedlockClient:
    """Factory : singleton avec RedisClient existant (charte OSMOSIS)."""
    global _default_redlock
    if _default_redlock is None:
        from knowbase.common.clients.redis_client import get_redis_client
        _default_redlock = RedlockClient(get_redis_client())
    return _default_redlock


def reset_redlock_client() -> None:
    """Reset singleton (utile pour tests)."""
    global _default_redlock
    _default_redlock = None
