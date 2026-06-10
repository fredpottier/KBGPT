"""Tests du corpus actif global (Redis) — chantier CH_CORPUS_SWITCH."""

from __future__ import annotations

import pytest

import knowbase.common.active_corpus as ac


class FakeRedis:
    def __init__(self, initial=None):
        self.store = {}
        if initial is not None:
            self.store[ac.ACTIVE_CORPUS_KEY] = initial

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


class FakeRedisClient:
    def __init__(self, client):
        self.client = client


def _patch_rc(monkeypatch, client):
    monkeypatch.setattr(ac, "_get_redis_client", lambda: FakeRedisClient(client))


def test_get_default_when_unset(monkeypatch):
    _patch_rc(monkeypatch, FakeRedis())
    assert ac.get_active_corpus() == "default"


def test_get_returns_stored(monkeypatch):
    _patch_rc(monkeypatch, FakeRedis(initial="medical"))
    assert ac.get_active_corpus() == "medical"


def test_set_then_get(monkeypatch):
    fake = FakeRedis()
    _patch_rc(monkeypatch, fake)
    ac.set_active_corpus("aero")
    assert fake.store[ac.ACTIVE_CORPUS_KEY] == "aero"
    assert ac.get_active_corpus() == "aero"


def test_set_strips_and_rejects_empty(monkeypatch):
    _patch_rc(monkeypatch, FakeRedis())
    with pytest.raises(ValueError):
        ac.set_active_corpus("   ")


def test_get_fail_soft_on_error(monkeypatch):
    def boom():
        raise RuntimeError("redis down")
    monkeypatch.setattr(ac, "_get_redis_client", boom)
    # lecture ne doit jamais lever → fallback default
    assert ac.get_active_corpus() == "default"


def test_set_raises_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(ac, "_get_redis_client", lambda: FakeRedisClient(None))
    with pytest.raises(RuntimeError):
        ac.set_active_corpus("medical")


def test_set_decodes_bytes(monkeypatch):
    # decode_responses=True dans le vrai client, mais on couvre le cas bytes
    fake = FakeRedis(initial=b"clinical")
    _patch_rc(monkeypatch, fake)
    assert ac.get_active_corpus() == "clinical"
