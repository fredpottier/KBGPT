"""Tests Redlock V5 DSG (CH-52.3.2)."""
from __future__ import annotations

import threading
import time
import uuid

import pytest

from knowbase.runtime_v5.redlock import (
    LockAcquireTimeout,
    RedlockClient,
    get_redlock_client,
    reset_redlock_client,
)


@pytest.fixture(scope="module")
def redlock():
    """Redlock singleton + cleanup keys créées par les tests."""
    reset_redlock_client()
    r = get_redlock_client()
    yield r
    # cleanup test keys (préfixe v5dsg:lock:test_*)
    try:
        keys = r._raw.keys("v5dsg:lock:test_*")
        if keys:
            r._raw.delete(*keys)
    except Exception:
        pass


def _rand_doc() -> str:
    return "test_doc_" + uuid.uuid4().hex[:8]


# ─── Acquire / Release basique ───────────────────────────────────────────────

class TestBasicAcquireRelease:
    def test_acquire_release(self, redlock):
        doc = _rand_doc()
        token = redlock.acquire("test_tenant", doc, timeout_s=10)
        assert token
        assert redlock.is_locked("test_tenant", doc)
        released = redlock.release("test_tenant", doc, token)
        assert released is True
        assert not redlock.is_locked("test_tenant", doc)

    def test_double_acquire_fail_fast(self, redlock):
        doc = _rand_doc()
        token1 = redlock.acquire("test_tenant", doc, timeout_s=10)
        try:
            with pytest.raises(LockAcquireTimeout):
                redlock.acquire("test_tenant", doc, timeout_s=10, wait_s=0)
        finally:
            redlock.release("test_tenant", doc, token1)

    def test_release_with_wrong_token(self, redlock):
        doc = _rand_doc()
        token = redlock.acquire("test_tenant", doc, timeout_s=10)
        try:
            # Tentative release avec token fake
            released = redlock.release("test_tenant", doc, "fake-token-xyz")
            assert released is False
            # Le lock est toujours actif
            assert redlock.is_locked("test_tenant", doc)
        finally:
            redlock.release("test_tenant", doc, token)

    def test_context_manager(self, redlock):
        doc = _rand_doc()
        with redlock.lock("test_tenant", doc, timeout_s=10) as token:
            assert token
            assert redlock.is_locked("test_tenant", doc)
        # auto-release
        assert not redlock.is_locked("test_tenant", doc)

    def test_context_manager_release_on_exception(self, redlock):
        doc = _rand_doc()
        with pytest.raises(RuntimeError):
            with redlock.lock("test_tenant", doc, timeout_s=10):
                raise RuntimeError("boom")
        # Lock libéré malgré l'exception
        assert not redlock.is_locked("test_tenant", doc)


# ─── Tenant isolation ────────────────────────────────────────────────────────

class TestTenantIsolation:
    def test_same_doc_id_different_tenants_can_lock(self, redlock):
        """Deux tenants peuvent acquérir le lock sur même doc_id en parallèle."""
        doc = _rand_doc()
        token_a = redlock.acquire("test_tenant_A", doc, timeout_s=10)
        token_b = redlock.acquire("test_tenant_B", doc, timeout_s=10)
        try:
            assert token_a != token_b
            assert redlock.is_locked("test_tenant_A", doc)
            assert redlock.is_locked("test_tenant_B", doc)
        finally:
            redlock.release("test_tenant_A", doc, token_a)
            redlock.release("test_tenant_B", doc, token_b)


# ─── Expiration ──────────────────────────────────────────────────────────────

class TestExpiration:
    def test_lock_auto_expires(self, redlock):
        doc = _rand_doc()
        # Acquire 1s timeout
        token = redlock.acquire("test_tenant", doc, timeout_s=1)
        assert redlock.is_locked("test_tenant", doc)
        # Wait > timeout
        time.sleep(1.2)
        # Lock expiré, un autre client peut l'acquérir
        assert not redlock.is_locked("test_tenant", doc)
        token2 = redlock.acquire("test_tenant", doc, timeout_s=10)
        assert token2 != token
        redlock.release("test_tenant", doc, token2)

    def test_extend_prolongs_ttl(self, redlock):
        doc = _rand_doc()
        token = redlock.acquire("test_tenant", doc, timeout_s=1)
        # Extend à 5s
        ok = redlock.extend("test_tenant", doc, token, timeout_s=5)
        assert ok is True
        time.sleep(1.2)
        # Toujours actif grâce à l'extend
        assert redlock.is_locked("test_tenant", doc)
        redlock.release("test_tenant", doc, token)

    def test_extend_with_wrong_token_fails(self, redlock):
        doc = _rand_doc()
        token = redlock.acquire("test_tenant", doc, timeout_s=10)
        try:
            ok = redlock.extend("test_tenant", doc, "wrong-token", timeout_s=60)
            assert ok is False
        finally:
            redlock.release("test_tenant", doc, token)


# ─── Wait (retry) ────────────────────────────────────────────────────────────

class TestWaitRetry:
    def test_acquire_with_wait_succeeds_after_release(self, redlock):
        """Si on attend, et que l'autre release entre temps, on obtient le lock."""
        doc = _rand_doc()
        token1 = redlock.acquire("test_tenant", doc, timeout_s=10)

        # Thread qui libère le lock après 0.3s
        def _release_later():
            time.sleep(0.3)
            redlock.release("test_tenant", doc, token1)

        t = threading.Thread(target=_release_later)
        t.start()

        # Attendre jusqu'à 2s
        t0 = time.time()
        token2 = redlock.acquire("test_tenant", doc, timeout_s=10, wait_s=2.0)
        elapsed = time.time() - t0
        assert token2 is not None
        assert token2 != token1
        assert 0.2 < elapsed < 2.0  # a attendu, mais pas timeout
        redlock.release("test_tenant", doc, token2)
        t.join()


# ─── Concurrent acquire (50 threads sur le même doc) ─────────────────────────

class TestConcurrentAcquire:
    def test_only_one_thread_gets_lock(self, redlock):
        """50 threads tentent acquire fail-fast : exactement 1 réussit."""
        doc = _rand_doc()
        successes = []
        failures = []
        barrier = threading.Barrier(50)

        def _try():
            barrier.wait()  # tous démarrent en même temps
            try:
                token = redlock.acquire("test_tenant", doc, timeout_s=10, wait_s=0)
                successes.append(token)
                # Hold le lock 0.1s pour empêcher les retardataires
                time.sleep(0.1)
                redlock.release("test_tenant", doc, token)
            except LockAcquireTimeout:
                failures.append(1)

        threads = [threading.Thread(target=_try) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1, f"expected 1 winner, got {len(successes)}"
        assert len(failures) == 49

    def test_serialization_with_wait(self, redlock):
        """5 threads avec wait=5s : tous obtiennent successivement le lock."""
        doc = _rand_doc()
        results = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(5)

        def _try(idx):
            barrier.wait()
            try:
                token = redlock.acquire(
                    "test_tenant", doc, timeout_s=2, wait_s=10.0
                )
                with results_lock:
                    results.append(idx)
                time.sleep(0.05)
                redlock.release("test_tenant", doc, token)
            except LockAcquireTimeout:
                pass

        threads = [threading.Thread(target=_try, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Tous les 5 ont fini par obtenir le lock (sérialisé)
        assert len(results) == 5, f"expected 5 serialized acquires, got {len(results)}"


# ─── get_holder_token ────────────────────────────────────────────────────────

class TestHolderTokenDiagnostic:
    def test_get_holder_returns_token(self, redlock):
        doc = _rand_doc()
        token = redlock.acquire("test_tenant", doc, timeout_s=10)
        try:
            holder = redlock.get_holder_token("test_tenant", doc)
            assert holder == token
        finally:
            redlock.release("test_tenant", doc, token)

    def test_get_holder_none_when_no_lock(self, redlock):
        assert redlock.get_holder_token("test_tenant", "nonexistent_doc") is None
