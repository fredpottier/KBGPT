"""Tests IdempotencyStore (CH-52.6.3 / S5.3)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.api.admission import FakeTimeProvider
from knowbase.runtime_v5.api.idempotency import (
    EntryStatus,
    IdempotencyConflict,
    IdempotencyStore,
    InMemoryIdempotencyBackend,
    compute_request_hash,
)


@pytest.fixture
def fake_time():
    return FakeTimeProvider(start=1000.0)


@pytest.fixture
def store(fake_time):
    backend = InMemoryIdempotencyBackend(time_provider=fake_time)
    return IdempotencyStore(backend=backend, ttl_s=10)  # short TTL for tests


# ─── compute_request_hash ────────────────────────────────────────────────────


class TestRequestHash:
    def test_identical_payloads_same_hash(self):
        a = {"question": "X", "doc_ids": ["a", "b"]}
        b = {"question": "X", "doc_ids": ["a", "b"]}
        assert compute_request_hash(a) == compute_request_hash(b)

    def test_key_order_invariant(self):
        a = {"a": 1, "b": 2}
        b = {"b": 2, "a": 1}
        assert compute_request_hash(a) == compute_request_hash(b)

    def test_different_payloads_differ(self):
        a = {"question": "X"}
        b = {"question": "Y"}
        assert compute_request_hash(a) != compute_request_hash(b)


# ─── check_or_reserve ───────────────────────────────────────────────────────


class TestCheckOrReserve:
    def test_first_call_returns_new(self, store):
        is_new, entry = store.check_or_reserve(
            tenant_id="t1", idempotency_key="abc",
            request_payload={"q": "X"}, request_id="req_1",
        )
        assert is_new is True
        assert entry is not None
        assert entry.status == EntryStatus.PENDING

    def test_same_request_returns_existing(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        is_new, entry = store.check_or_reserve(
            "t1", "abc", {"q": "X"}, "req_2",
        )
        assert is_new is False
        assert entry.status == EntryStatus.PENDING
        # request_id reste le 1er
        assert entry.request_id == "req_1"

    def test_different_request_same_key_raises_conflict(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        with pytest.raises(IdempotencyConflict) as exc:
            store.check_or_reserve("t1", "abc", {"q": "Y"}, "req_2")
        assert exc.value.key == "abc"

    def test_no_key_bypasses_idempotency(self, store):
        is_new, entry = store.check_or_reserve(
            "t1", "", {"q": "X"}, "req_1",
        )
        # No idempotency_key → no caching, always new
        assert is_new is True
        assert entry is None

    def test_different_tenants_isolated(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        # Même key mais tenant différent → autre slot
        is_new, _ = store.check_or_reserve("t2", "abc", {"q": "X"}, "req_2")
        assert is_new is True


# ─── save_completed ──────────────────────────────────────────────────────────


class TestSaveCompleted:
    def test_save_then_get_cached(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        store.save_completed("t1", "abc", {"answer": "42"})
        cached = store.get_cached_response("t1", "abc")
        assert cached == {"answer": "42"}

    def test_subsequent_check_returns_completed(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        store.save_completed("t1", "abc", {"answer": "42"})
        is_new, entry = store.check_or_reserve("t1", "abc", {"q": "X"}, "req_2")
        assert is_new is False
        assert entry.status == EntryStatus.COMPLETED
        assert entry.response_json is not None

    def test_save_without_reserve_warns(self, store):
        # Should not raise but warn
        store.save_completed("t1", "abc", {"answer": "X"})


# ─── save_failed ─────────────────────────────────────────────────────────────


class TestSaveFailed:
    def test_save_failed(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        store.save_failed("t1", "abc", {"error": {"type": "agent_timeout"}})
        # Subsequent call : entry has status=FAILED
        _, entry = store.check_or_reserve("t1", "abc", {"q": "X"}, "req_2")
        assert entry.status == EntryStatus.FAILED


# ─── get_cached_response ────────────────────────────────────────────────────


class TestGetCachedResponse:
    def test_none_if_no_entry(self, store):
        assert store.get_cached_response("t1", "nonexistent") is None

    def test_none_if_pending(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        # PENDING → pas cached
        assert store.get_cached_response("t1", "abc") is None

    def test_returns_completed_payload(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        store.save_completed("t1", "abc", {"answer": "X", "citations": []})
        cached = store.get_cached_response("t1", "abc")
        assert cached["answer"] == "X"
        assert cached["citations"] == []


# ─── TTL expiry ──────────────────────────────────────────────────────────────


class TestTTL:
    def test_entry_expires(self, store, fake_time):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        fake_time.advance(11.0)  # > TTL=10
        # Get backend → expired
        backend_get = store.backend.get(store._key("t1", "abc"))
        assert backend_get is None

    def test_expired_then_new_reserve_ok(self, store, fake_time):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        fake_time.advance(11.0)
        # New request, different payload, even same key → OK (expired)
        is_new, _ = store.check_or_reserve("t1", "abc", {"q": "Y"}, "req_2")
        assert is_new is True


# ─── Delete ──────────────────────────────────────────────────────────────────


class TestDelete:
    def test_delete_existing(self, store):
        store.check_or_reserve("t1", "abc", {"q": "X"}, "req_1")
        assert store.delete("t1", "abc") is True

    def test_delete_nonexistent(self, store):
        assert store.delete("t1", "no_key") is False
