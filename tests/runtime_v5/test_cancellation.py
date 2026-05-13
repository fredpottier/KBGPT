"""Tests CancellationToken async (CH-52.5.4 / S4.4)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from knowbase.runtime_v5.agent.cancellation import (
    NULL_TOKEN,
    CancellationRequested,
    CancellationToken,
)


# ─── Sync ────────────────────────────────────────────────────────────────────


class TestSyncCancellation:
    def test_initial_not_cancelled(self):
        t = CancellationToken()
        assert t.is_cancelled() is False
        t.check()  # no raise

    def test_cancel_then_check_raises(self):
        t = CancellationToken()
        t.cancel(reason="user disconnect", source="user")
        with pytest.raises(CancellationRequested) as exc:
            t.check()
        assert exc.value.reason == "user disconnect"
        assert exc.value.source == "user"

    def test_cancel_idempotent(self):
        t = CancellationToken()
        t.cancel(reason="first")
        t.cancel(reason="second")
        # First reason stays
        assert t.reason == "first"

    def test_raise_if_cancelled_alias(self):
        t = CancellationToken()
        t.cancel("test")
        with pytest.raises(CancellationRequested):
            t.raise_if_cancelled()


# ─── Timeout ─────────────────────────────────────────────────────────────────


class TestTimeout:
    def test_no_auto_cancel_before_timeout(self):
        t = CancellationToken(timeout_s=10.0)
        assert t.is_cancelled() is False

    def test_auto_cancel_after_timeout(self):
        t = CancellationToken(timeout_s=0.05)
        time.sleep(0.1)
        assert t.is_cancelled() is True
        assert t.source == "timeout"
        assert "timeout after" in t.reason

    def test_no_timeout_means_no_auto_cancel(self):
        t = CancellationToken(timeout_s=None)
        time.sleep(0.05)
        assert t.is_cancelled() is False


# ─── Elapsed / time tracking ─────────────────────────────────────────────────


class TestElapsed:
    def test_elapsed_increases(self):
        t = CancellationToken()
        e1 = t.elapsed_s()
        time.sleep(0.02)
        e2 = t.elapsed_s()
        assert e2 > e1

    def test_time_since_cancelled_none_initially(self):
        t = CancellationToken()
        assert t.time_since_cancelled_s() is None

    def test_time_since_cancelled_after_cancel(self):
        t = CancellationToken()
        t.cancel()
        time.sleep(0.02)
        delta = t.time_since_cancelled_s()
        assert delta is not None and delta >= 0.02


# ─── Async ───────────────────────────────────────────────────────────────────


class TestAsyncCancellation:
    @pytest.mark.asyncio
    async def test_async_check_no_cancel(self):
        t = CancellationToken()
        await t.check_async()  # no raise

    @pytest.mark.asyncio
    async def test_async_check_cancelled_raises(self):
        t = CancellationToken()
        t.cancel(reason="async test")
        with pytest.raises(CancellationRequested):
            await t.check_async()

    @pytest.mark.asyncio
    async def test_external_cancel_visible_via_async_check(self):
        """Cancel depuis un autre thread/coroutine doit être visible."""
        t = CancellationToken()

        async def _cancel_after_delay():
            await asyncio.sleep(0.03)
            t.cancel(reason="from coroutine", source="external")

        async def _worker():
            for _ in range(20):
                await t.check_async()
                await asyncio.sleep(0.01)

        # Run both : cancel happens during worker
        with pytest.raises(CancellationRequested) as exc:
            await asyncio.gather(_worker(), _cancel_after_delay())
        assert exc.value.source == "external"


# ─── Thread-safety ───────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_cancel_from_another_thread(self):
        t = CancellationToken()
        results = {"raised": False}

        def _worker():
            try:
                for _ in range(50):
                    t.check()
                    time.sleep(0.005)
            except CancellationRequested:
                results["raised"] = True

        def _canceller():
            time.sleep(0.03)
            t.cancel(reason="from thread")

        wt = threading.Thread(target=_worker)
        ct = threading.Thread(target=_canceller)
        wt.start(); ct.start()
        wt.join(timeout=2); ct.join(timeout=2)
        assert results["raised"] is True


# ─── Snapshot ────────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_not_cancelled(self):
        t = CancellationToken(timeout_s=10.0)
        snap = t.snapshot()
        assert snap["cancelled"] is False
        assert snap["timeout_s"] == 10.0
        assert snap["time_since_cancelled_s"] is None

    def test_snapshot_cancelled(self):
        t = CancellationToken()
        t.cancel(reason="snapshot test", source="user")
        snap = t.snapshot()
        assert snap["cancelled"] is True
        assert snap["reason"] == "snapshot test"
        assert snap["source"] == "user"
        assert snap["time_since_cancelled_s"] is not None


# ─── NULL_TOKEN sentinel ─────────────────────────────────────────────────────


class TestNullToken:
    def test_null_token_never_cancelled(self):
        assert NULL_TOKEN.is_cancelled() is False
        NULL_TOKEN.check()  # no raise
        NULL_TOKEN.cancel(reason="ignored")  # cancel is recorded but is_cancelled returns False
        assert NULL_TOKEN.is_cancelled() is False  # null overrides

    @pytest.mark.asyncio
    async def test_null_token_async_check_no_raise(self):
        await NULL_TOKEN.check_async()
