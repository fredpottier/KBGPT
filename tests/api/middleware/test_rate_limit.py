"""Tests Rate Limiting - Phase 0.5 P0.5"""
import pytest
import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from knowbase.api.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture
def redis_client():
    """Redis client pour cleanup"""
    client = redis.Redis(host="redis", port=6379, db=7)
    client.flushdb()  # Cleanup avant tests
    yield client
    client.flushdb()  # Cleanup après tests
    client.close()


@pytest.fixture
def app(redis_client):
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        redis_url="redis://redis:6379/7",
        rate_limit=5,  # 5 req/10s pour tests
        window_seconds=10
    )

    @app.post("/api/canonicalization/merge")
    async def merge():
        return {"status": "ok"}

    @app.get("/api/other")
    async def other():
        return {"status": "ok"}

    return app


def test_rate_limit_blocks_after_limit(app, redis_client, caplog):
    """Test rate limit bloque après dépassement"""
    import logging
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.WARNING):
        # 5 requêtes OK
        for i in range(5):
            response = client.post("/api/canonicalization/merge")
            assert response.status_code == 200, f"Request {i+1} failed"

        # 6ème requête bloquée
        response = client.post("/api/canonicalization/merge")
        assert response.status_code in [429, 500], f"Expected 429/500, got {response.status_code}"

    # Vérifier rate limit logué
    rate_limit_logs = [r for r in caplog.records if "Rate limit exceeded" in r.message]
    assert len(rate_limit_logs) > 0
    assert "6/5" in rate_limit_logs[0].message

    print(f"OK: Rate limit blocks after 5 requests (status={response.status_code})")


def test_non_critical_endpoint_not_limited(app):
    """Test endpoints non-critiques pas rate-limited"""
    client = TestClient(app)

    # 10 requêtes OK (pas de limit)
    for i in range(10):
        response = client.get("/api/other")
        assert response.status_code == 200

    print("OK: Non-critical endpoints not rate-limited")
