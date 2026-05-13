"""V5 ReasoningAgent — Cancellation token async-aware (Sprint S4.4).

ADR V1.5 §3e §Y6 : permettre l'arrêt propre de l'agent quand le user
ferme l'onglet (HTTP disconnect, abort signal). V1.0 oubliait ce point
= coût gaspillé pur si l'agent continuait 60s post-cancel.

Pattern emprunté à .NET CancellationToken / asyncio.CancelledError. Le token
est passé via async/await dans la boucle agent, et check :
- avant chaque iter
- avant chaque tool call
- entre les LLM calls

Si cancelled, raise `CancellationRequested` qui est attrapée par l'agent
qui retourne une réponse `partial` avec `cancelled_at_iter=N`.

Domain-agnostic : aucune dépendance métier. Modèle générique reusable
sur tout système async qui veut un cancellation propagable.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


class CancellationRequested(Exception):
    """Levée par CancellationToken.check() ou .raise_if_cancelled() si cancel actif."""
    def __init__(self, reason: str = "", source: str = ""):
        self.reason = reason
        self.source = source
        msg = f"Cancellation requested"
        if source:
            msg += f" (source={source})"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)


@dataclass
class CancellationToken:
    """Token cancellable thread-safe + async-aware.

    Args:
        timeout_s : si fourni, le token devient cancelled automatiquement après ce délai
        reason_prefix : préfixe ajouté à toutes les raisons (pour debug)

    Usage :
        token = CancellationToken(timeout_s=60)
        try:
            for i in range(100):
                await token.check_async()
                # ... work ...
        except CancellationRequested as e:
            # cleanup
            pass

        # External cancellation
        token.cancel(reason="user disconnected")
    """
    timeout_s: Optional[float] = None
    reason_prefix: str = ""

    _cancelled: bool = field(default=False, init=False)
    _reason: str = field(default="", init=False)
    _source: str = field(default="", init=False)
    _cancelled_at: Optional[float] = field(default=None, init=False)
    _created_at: float = field(default_factory=time.monotonic, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # ─── Cancellation triggers ───────────────────────────────────────────────

    def cancel(self, reason: str = "", source: str = "external") -> None:
        """Marque le token comme cancelled. Idempotent.

        Args:
            reason : raison libre (audit)
            source : 'user', 'timeout', 'external', 'budget', 'admission_control', ...
        """
        with self._lock:
            if not self._cancelled:
                self._cancelled = True
                self._reason = reason
                self._source = source
                self._cancelled_at = time.monotonic()

    # ─── Status check ────────────────────────────────────────────────────────

    def is_cancelled(self) -> bool:
        """True si déjà cancelled OU timeout dépassé."""
        with self._lock:
            if self._cancelled:
                return True
            if self.timeout_s is not None:
                elapsed = time.monotonic() - self._created_at
                if elapsed > self.timeout_s:
                    # Auto-cancel via timeout
                    self._cancelled = True
                    self._reason = f"timeout after {self.timeout_s}s (elapsed={elapsed:.1f}s)"
                    self._source = "timeout"
                    self._cancelled_at = time.monotonic()
                    return True
            return False

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def source(self) -> str:
        return self._source

    def elapsed_s(self) -> float:
        """Secondes depuis création."""
        return time.monotonic() - self._created_at

    def time_since_cancelled_s(self) -> Optional[float]:
        """Secondes depuis cancel (None si pas cancelled)."""
        if self._cancelled_at is None:
            return None
        return time.monotonic() - self._cancelled_at

    # ─── Sync check ──────────────────────────────────────────────────────────

    def check(self) -> None:
        """Raise CancellationRequested si cancelled. Sync version."""
        if self.is_cancelled():
            raise CancellationRequested(reason=self._reason, source=self._source)

    raise_if_cancelled = check  # alias

    # ─── Async check ─────────────────────────────────────────────────────────

    async def check_async(self) -> None:
        """Yield control then check. Async-friendly version."""
        # Yield to event loop : permet à un cancel concurrent d'être visible
        await asyncio.sleep(0)
        self.check()

    # ─── Snapshot ────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cancelled": self._cancelled,
                "reason": self._reason,
                "source": self._source,
                "elapsed_s": round(self.elapsed_s(), 3),
                "timeout_s": self.timeout_s,
                "time_since_cancelled_s": (
                    round(self.time_since_cancelled_s(), 3)
                    if self._cancelled_at else None
                ),
            }


# ─── Helper : never-cancelled token (pour tests et default args) ─────────────


class _NullCancellationToken(CancellationToken):
    """Sentinel : jamais cancelled, jamais timeout. Pour code optionnel-aware."""
    def is_cancelled(self) -> bool:
        return False
    def check(self) -> None:
        return
    async def check_async(self) -> None:
        return


NULL_TOKEN = _NullCancellationToken()
"""Singleton sentinel — utiliser quand pas de cancellation requise."""
