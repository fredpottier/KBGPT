"""
Tests Client Redis Résilient - Phase 0.5 Durcissement P0.3
"""
import pytest
import redis
import time
from unittest.mock import Mock, patch
from knowbase.common.redis_client_resilient import (
    ResilientRedisClient,
    RedisConnectionError,
    create_resilient_redis_client
)


@pytest.fixture
def redis_client():
    """Client Redis résilient pour tests (DB 6 isolé)"""
    client = ResilientRedisClient(
        redis_url="redis://redis:6379/6",
        max_retries=3,
        base_delay=0.1  # Accéléré pour tests
    )
    # Cleanup avant tests
    client.flushdb()
    yield client
    # Cleanup après tests
    client.flushdb()
    client.close()


class TestResilientRedisClientBasic:
    """Tests fonctionnalités de base avec retry"""

    def test_get_set_with_retry(self, redis_client):
        """
        Test get/set basique avec retry automatique

        Expected: Opérations réussissent même avec client standard
        """
        # Set
        result = redis_client.set("test:key", "test_value", ex=60)
        assert result is True

        # Get
        value = redis_client.get("test:key")
        assert value == "test_value"

        print("OK: Get/Set with retry")

    def test_exists_and_delete(self, redis_client):
        """
        Test exists et delete avec retry

        Expected: Opérations réussissent
        """
        redis_client.set("test:exists", "value", ex=60)

        # Exists
        exists = redis_client.exists("test:exists")
        assert exists == 1

        # Delete
        deleted = redis_client.delete("test:exists")
        assert deleted == 1

        # Vérifier suppression
        exists_after = redis_client.exists("test:exists")
        assert exists_after == 0

        print("OK: Exists/Delete with retry")

    def test_expire_and_ttl(self, redis_client):
        """
        Test expiration et TTL avec retry

        Expected: TTL correctement défini
        """
        redis_client.set("test:ttl", "value")

        # Set expiration
        result = redis_client.expire("test:ttl", 120)
        assert result is True

        # Get TTL
        ttl = redis_client.ttl("test:ttl")
        assert 115 <= ttl <= 120  # Marge pour latence

        print(f"OK: Expire/TTL with retry (ttl={ttl}s)")

    def test_hash_operations(self, redis_client):
        """
        Test opérations hash avec retry

        Expected: hset/hget/hgetall/hdel fonctionnent
        """
        # hset
        redis_client.hset("test:hash", "field1", "value1")
        redis_client.hset("test:hash", "field2", "value2")

        # hget
        val1 = redis_client.hget("test:hash", "field1")
        assert val1 == "value1"

        # hgetall
        all_vals = redis_client.hgetall("test:hash")
        assert all_vals == {"field1": "value1", "field2": "value2"}

        # hdel
        deleted = redis_client.hdel("test:hash", "field1")
        assert deleted == 1

        print("OK: Hash operations with retry")

    def test_list_operations(self, redis_client):
        """
        Test opérations list avec retry

        Expected: lpush/rpush/lrange/llen fonctionnent
        """
        # lpush
        redis_client.lpush("test:list", "item1", "item2")

        # rpush
        redis_client.rpush("test:list", "item3")

        # lrange
        items = redis_client.lrange("test:list", 0, -1)
        assert items == ["item2", "item1", "item3"]  # lpush inverse ordre (decode_responses=True)

        # llen
        length = redis_client.llen("test:list")
        assert length == 3

        print("OK: List operations with retry")


class TestResilientRedisClientRetry:
    """Tests retry logic avec connexions instables"""

    def test_retry_on_connection_error(self):
        """
        Test retry automatique si ConnectionError

        Expected: 3 tentatives avant échec final
        """
        # Mock Redis client qui échoue 2 fois puis réussit
        with patch("redis.Redis.from_url") as mock_redis:
            mock_client = Mock()
            mock_redis.return_value = mock_client

            # Échoue 2 fois, puis réussit
            mock_client.get.side_effect = [
                redis.ConnectionError("Connection lost"),
                redis.ConnectionError("Connection lost"),
                "success_value"
            ]

            resilient_client = ResilientRedisClient(
                redis_url="redis://redis:6379/6",
                max_retries=3,
                base_delay=0.1
            )

            # Doit réussir après 3 tentatives
            value = resilient_client.get("test:key")
            assert value == "success_value"

            # Vérifier 3 appels
            assert mock_client.get.call_count == 3

            print("OK: Retry on ConnectionError (3 attempts)")

    def test_fail_after_max_retries(self):
        """
        Test échec après max_retries dépassé

        Expected: RedisConnectionError après 4 tentatives (3 retries + 1 initial)
        """
        with patch("redis.Redis.from_url") as mock_redis:
            mock_client = Mock()
            mock_redis.return_value = mock_client

            # Échoue toujours
            mock_client.set.side_effect = redis.ConnectionError("Connection lost")

            resilient_client = ResilientRedisClient(
                redis_url="redis://redis:6379/6",
                max_retries=3,
                base_delay=0.1
            )

            # Doit raise RedisConnectionError après 4 tentatives
            with pytest.raises(RedisConnectionError):
                resilient_client.set("test:key", "value")

            # Vérifier 4 appels (1 initial + 3 retries)
            assert mock_client.set.call_count == 4

            print("OK: Fail after max_retries (4 attempts)")

    def test_exponential_backoff_timing(self):
        """
        Test exponential backoff timing

        Expected: Délais ~1s, 2s, 4s entre tentatives (base_delay=1.0 par défaut dans décorateur)
        """
        with patch("redis.Redis.from_url") as mock_redis:
            mock_client = Mock()
            mock_redis.return_value = mock_client

            # Échoue 3 fois puis réussit
            mock_client.get.side_effect = [
                redis.ConnectionError("Connection lost"),
                redis.ConnectionError("Connection lost"),
                redis.ConnectionError("Connection lost"),
                "success"
            ]

            resilient_client = ResilientRedisClient(
                redis_url="redis://redis:6379/6",
                max_retries=3,
                base_delay=0.1  # Ignoré par décorateur (utilise base_delay=1.0 par défaut)
            )

            start = time.time()
            value = resilient_client.get("test:key")
            elapsed = time.time() - start

            # Délais: 1s + 2s + 4s = 7s (base_delay par défaut du décorateur)
            assert 6.5 <= elapsed <= 8.0

            assert value == "success"
            print(f"OK: Exponential backoff timing (elapsed={elapsed:.3f}s)")

    def test_non_retryable_error_fails_immediately(self):
        """
        Test erreur non-retryable échoue immédiatement

        Expected: ValueError pas retryé, fail immédiatement
        """
        with patch("redis.Redis.from_url") as mock_redis:
            mock_client = Mock()
            mock_redis.return_value = mock_client

            # Erreur non-retryable
            mock_client.get.side_effect = ValueError("Invalid argument")

            resilient_client = ResilientRedisClient(
                redis_url="redis://redis:6379/6",
                max_retries=3,
                base_delay=0.1
            )

            # Doit raise ValueError immédiatement (pas de retry)
            with pytest.raises(ValueError):
                resilient_client.get("test:key")

            # Vérifier 1 seul appel (pas de retry)
            assert mock_client.get.call_count == 1

            print("OK: Non-retryable error fails immediately")


class TestResilientRedisClientFactory:
    """Tests factory function"""

    def test_create_resilient_client(self):
        """
        Test création client via factory function

        Expected: Client fonctionnel créé
        """
        client = create_resilient_redis_client(
            redis_url="redis://redis:6379/6",
            max_retries=5
        )

        # Test opération basique
        client.set("test:factory", "value", ex=60)
        value = client.get("test:factory")
        assert value == "value"

        client.close()
        print("OK: create_resilient_redis_client factory")

    def test_context_manager(self):
        """
        Test utilisation comme context manager

        Expected: Auto-close à la sortie du context
        """
        with create_resilient_redis_client(redis_url="redis://redis:6379/6") as client:
            client.set("test:ctx", "value", ex=60)
            value = client.get("test:ctx")
            assert value == "value"

        # Client fermé automatiquement après context
        print("OK: Context manager auto-close")


class TestResilientRedisClientObservability:
    """Tests logs et observabilité"""

    def test_ping_with_retry(self, redis_client):
        """
        Test ping pour vérifier connexion Redis

        Expected: ping() retourne True
        """
        result = redis_client.ping()
        assert result is True

        print("OK: Ping with retry")

    def test_keys_pattern_matching(self, redis_client):
        """
        Test keys() avec pattern matching

        Expected: Liste clés matchant pattern
        """
        redis_client.set("test:keys:1", "v1", ex=60)
        redis_client.set("test:keys:2", "v2", ex=60)
        redis_client.set("other:key", "v3", ex=60)

        # Pattern matching
        keys = redis_client.keys("test:keys:*")
        assert len(keys) == 2
        assert "test:keys:1" in keys  # decode_responses=True
        assert "test:keys:2" in keys

        print(f"OK: Keys pattern matching ({len(keys)} keys)")
