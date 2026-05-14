"""V5 IdempotencyStore — dedup 24h via Redis.

ADR V1.5 §3h : si le client retry après timeout réseau, l'API détecte
(via Redis dedup 24h) que c'est la même requête et retourne la réponse
cached, sans re-jouer 30-90s d'agent.

Politique :
- Clé : `(tenant_id, idempotency_key)`
- Valeur : `(request_hash, response_json)` — request_hash = sha256 du payload normalisé
- TTL : 24h

Cas :
1. Key absente → store payload (PENDING) puis exécution → save final response
2. Key présente avec MÊME request_hash + response PRÊTE → retourne cached
3. Key présente avec MÊME request_hash + response PENDING → 409 ou poll
4. Key présente avec request_hash DIFFÉRENT → 409 `idempotency_conflict`

Backend :
- Production : Redis (RedisIdempotencyStore)
- Tests : InMemoryIdempotencyStore (déterministe)

Domain-agnostic strict.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


# ─── Errors ──────────────────────────────────────────────────────────────────


class IdempotencyConflict(Exception):
    """Levée quand 2 requêtes différentes utilisent le même Idempotency-Key."""
    def __init__(self, key: str, stored_hash: str, current_hash: str):
        self.key = key
        self.stored_hash = stored_hash
        self.current_hash = current_hash
        super().__init__(
            f"Idempotency-Key '{key}' already used for different request "
            f"(stored hash {stored_hash[:8]}..., current {current_hash[:8]}...)"
        )


# ─── Entry status ────────────────────────────────────────────────────────────


class EntryStatus(str, Enum):
    PENDING = "pending"  # request en cours
    COMPLETED = "completed"  # response cached
    FAILED = "failed"  # request a échoué (avec error)


@dataclass
class IdempotencyEntry:
    """État d'une entry idempotency."""
    request_hash: str
    status: EntryStatus
    response_json: Optional[str] = None  # JSON-encoded response if COMPLETED/FAILED
    created_at: float = 0.0
    completed_at: Optional[float] = None
    request_id: Optional[str] = None


# ─── Helpers : hash de la request ────────────────────────────────────────────


def compute_request_hash(payload: dict) -> str:
    """sha256 canonique du payload (clés triées, ensure_ascii=False)."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─── Backend Protocol ────────────────────────────────────────────────────────


class IdempotencyBackend(Protocol):
    def get(self, key: str) -> Optional[IdempotencyEntry]: ...
    def set(self, key: str, entry: IdempotencyEntry, ttl_s: int) -> None: ...
    def delete(self, key: str) -> bool: ...


# ─── In-memory backend (tests + dev) ─────────────────────────────────────────


class InMemoryIdempotencyBackend:
    """Backend in-memory thread-safe avec TTL manuel."""

    def __init__(self, time_provider: Optional[Any] = None):
        self._lock = threading.RLock()
        self._store: dict[str, tuple[IdempotencyEntry, float]] = {}  # key → (entry, expires_at)
        self._time = time_provider  # FakeTimeProvider compat

    def _now(self) -> float:
        if self._time:
            return self._time.now()
        return time.monotonic()

    def get(self, key: str) -> Optional[IdempotencyEntry]:
        with self._lock:
            data = self._store.get(key)
            if data is None:
                return None
            entry, expires_at = data
            if self._now() >= expires_at:
                # expired
                del self._store[key]
                return None
            return entry

    def set(self, key: str, entry: IdempotencyEntry, ttl_s: int) -> None:
        with self._lock:
            expires_at = self._now() + ttl_s
            self._store[key] = (entry, expires_at)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None


# ─── IdempotencyStore ────────────────────────────────────────────────────────


class IdempotencyStore:
    """Gère l'idempotence multi-tenant.

    Args:
        backend : InMemoryIdempotencyBackend OU RedisIdempotencyBackend (futur)
        ttl_s : TTL des entries (default 24h)
        key_prefix : prefix pour la clé Redis composite
    """

    DEFAULT_TTL_S = 86_400  # 24h

    def __init__(
        self,
        backend: Optional[IdempotencyBackend] = None,
        ttl_s: int = DEFAULT_TTL_S,
        key_prefix: str = "v5:idemp:",
    ):
        self.backend = backend or InMemoryIdempotencyBackend()
        self.ttl_s = ttl_s
        self.key_prefix = key_prefix

    def _key(self, tenant_id: str, idempotency_key: str) -> str:
        return f"{self.key_prefix}{tenant_id}:{idempotency_key}"

    # ─── Check + reserve ─────────────────────────────────────────────────────

    def check_or_reserve(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_payload: dict,
        request_id: str,
    ) -> tuple[bool, Optional[IdempotencyEntry]]:
        """Vérifie si key déjà utilisée, sinon reserve PENDING.

        Returns:
            (is_new, entry) où :
            - is_new=True : key réservée pour cette request, exec à faire
            - is_new=False : entry existe déjà (cached ou pending)

        Raises:
            IdempotencyConflict si key existe avec request différente
        """
        if not idempotency_key:
            # Pas de header → pas d'idempotency
            return True, None

        k = self._key(tenant_id, idempotency_key)
        current_hash = compute_request_hash(request_payload)
        existing = self.backend.get(k)

        if existing is not None:
            if existing.request_hash != current_hash:
                raise IdempotencyConflict(
                    key=idempotency_key,
                    stored_hash=existing.request_hash,
                    current_hash=current_hash,
                )
            # Même request — retourne cached
            return False, existing

        # New : reserve PENDING
        entry = IdempotencyEntry(
            request_hash=current_hash,
            status=EntryStatus.PENDING,
            request_id=request_id,
            created_at=time.monotonic(),
        )
        self.backend.set(k, entry, ttl_s=self.ttl_s)
        return True, entry

    def save_completed(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_payload: dict,
    ) -> None:
        """Persiste la response post-exécution (status=COMPLETED)."""
        if not idempotency_key:
            return
        k = self._key(tenant_id, idempotency_key)
        existing = self.backend.get(k)
        if existing is None:
            # Recreated TTL after expiry? skip save
            logger.warning(f"[Idempotency] save_completed without prior reserve : {k}")
            return
        entry = IdempotencyEntry(
            request_hash=existing.request_hash,
            status=EntryStatus.COMPLETED,
            response_json=json.dumps(response_payload, ensure_ascii=False, default=str),
            request_id=existing.request_id,
            created_at=existing.created_at,
            completed_at=time.monotonic(),
        )
        self.backend.set(k, entry, ttl_s=self.ttl_s)

    def save_failed(
        self,
        tenant_id: str,
        idempotency_key: str,
        error_payload: dict,
    ) -> None:
        """Persiste l'erreur (pour pas re-rejouer une request qui foire toujours)."""
        if not idempotency_key:
            return
        k = self._key(tenant_id, idempotency_key)
        existing = self.backend.get(k)
        if existing is None:
            return
        entry = IdempotencyEntry(
            request_hash=existing.request_hash,
            status=EntryStatus.FAILED,
            response_json=json.dumps(error_payload, ensure_ascii=False, default=str),
            request_id=existing.request_id,
            created_at=existing.created_at,
            completed_at=time.monotonic(),
        )
        self.backend.set(k, entry, ttl_s=self.ttl_s)

    def delete(self, tenant_id: str, idempotency_key: str) -> bool:
        """Supprime une entry (admin / test cleanup)."""
        return self.backend.delete(self._key(tenant_id, idempotency_key))

    # ─── Convenience getters ────────────────────────────────────────────────

    def get_cached_response(
        self, tenant_id: str, idempotency_key: str
    ) -> Optional[dict]:
        """Retourne la response cached si COMPLETED, sinon None."""
        entry = self.backend.get(self._key(tenant_id, idempotency_key))
        if entry is None or entry.status != EntryStatus.COMPLETED:
            return None
        if not entry.response_json:
            return None
        try:
            return json.loads(entry.response_json)
        except json.JSONDecodeError:
            return None
