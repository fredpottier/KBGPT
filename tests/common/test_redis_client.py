"""
Tests unitaires pour RedisClient.

Tests coverage:
- Initialisation et connexion
- get_budget_key() format
- get_budget_consumed()
- increment_budget() avec atomic operations
- decrement_budget() pour refund
- get_budget_stats()
- reset_budget()
- Graceful degradation (Redis unavailable)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from knowbase.common.clients.redis_client import RedisClient, get_redis_client


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_redis():
    """Mock Redis client pour tests."""
    mock = MagicMock()
    mock.ping.return_value = True
    return mock


@pytest.fixture
def redis_client(mock_redis):
    """RedisClient avec Redis mocké."""
    with patch('knowbase.common.clients.redis_client.redis.Redis', return_value=mock_redis):
        client = RedisClient(host="localhost", port=6379, db=0)
        return client


# ============================================================================
# Tests Initialisation
# ============================================================================

def test_redis_client_init_success(mock_redis):
    """Test initialisation RedisClient avec succès."""
    with patch('knowbase.common.clients.redis_client.redis.Redis', return_value=mock_redis):
        client = RedisClient(host="localhost", port=6379, db=0)

        assert client.host == "localhost"
        assert client.port == 6379
        assert client.db == 0
        assert client.client is not None
        mock_redis.ping.assert_called_once()


def test_redis_client_init_connection_error():
    """Test initialisation RedisClient avec connexion échouée."""
    import redis as redis_lib

    mock = MagicMock()
    mock.ping.side_effect = redis_lib.ConnectionError("Connection refused")

    with patch('knowbase.common.clients.redis_client.redis.Redis', return_value=mock):
        client = RedisClient(host="invalid", port=9999, db=0)

        assert client.client is None


def test_is_connected_true(redis_client, mock_redis):
    """Test is_connected() retourne True si Redis connecté."""
    mock_redis.ping.return_value = True

    assert redis_client.is_connected() is True


def test_is_connected_false_no_client():
    """Test is_connected() retourne False si client None."""
    client = RedisClient.__new__(RedisClient)
    client.client = None

    assert client.is_connected() is False


def test_is_connected_false_ping_fails(redis_client, mock_redis):
    """Test is_connected() retourne False si ping échoue."""
    mock_redis.ping.side_effect = Exception("Connection lost")

    assert redis_client.is_connected() is False


# ============================================================================
# Tests get_budget_key()
# ============================================================================

def test_get_budget_key_default_date(redis_client):
    """Test get_budget_key() avec date par défaut (aujourd'hui)."""
    with patch('knowbase.common.clients.redis_client.datetime') as mock_datetime:
        mock_datetime.utcnow.return_value = datetime(2025, 10, 15, 12, 0, 0)

        key = redis_client.get_budget_key("tenant_123", "SMALL")

        assert key == "budget:tenant:tenant_123:SMALL:2025-10-15"


def test_get_budget_key_custom_date(redis_client):
    """Test get_budget_key() avec date spécifique."""
    custom_date = datetime(2025, 12, 25, 10, 30, 0)

    key = redis_client.get_budget_key("tenant_abc", "BIG", date=custom_date)

    assert key == "budget:tenant:tenant_abc:BIG:2025-12-25"


def test_get_budget_cost_key(redis_client):
    """Test get_budget_cost_key() format."""
    with patch('knowbase.common.clients.redis_client.datetime') as mock_datetime:
        mock_datetime.utcnow.return_value = datetime(2025, 10, 15, 12, 0, 0)

        cost_key = redis_client.get_budget_cost_key("tenant_123", "VISION")

        assert cost_key == "budget:tenant:tenant_123:VISION:2025-10-15:cost"


# ============================================================================
# Tests get_budget_consumed()
# ============================================================================

def test_get_budget_consumed_success(redis_client, mock_redis):
    """Test get_budget_consumed() avec valeur existante."""
    mock_redis.get.return_value = "42"

    consumed = redis_client.get_budget_consumed("tenant_123", "SMALL")

    assert consumed == 42
    mock_redis.get.assert_called_once()


def test_get_budget_consumed_key_not_exists(redis_client, mock_redis):
    """Test get_budget_consumed() avec clé inexistante (retourne 0)."""
    mock_redis.get.return_value = None

    consumed = redis_client.get_budget_consumed("tenant_123", "SMALL")

    assert consumed == 0


def test_get_budget_consumed_not_connected(redis_client):
    """Test get_budget_consumed() quand Redis non connecté."""
    redis_client.client = None

    consumed = redis_client.get_budget_consumed("tenant_123", "SMALL")

    assert consumed == 0


def test_get_budget_consumed_error(redis_client, mock_redis):
    """Test get_budget_consumed() avec erreur Redis."""
    mock_redis.get.side_effect = Exception("Redis error")

    consumed = redis_client.get_budget_consumed("tenant_123", "SMALL")

    assert consumed == 0


# ============================================================================
# Tests increment_budget()
# ============================================================================

def test_increment_budget_success(redis_client, mock_redis):
    """Test increment_budget() avec succès."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = [50, True, 1.234, True]  # INCRBY, EXPIRE, INCRBYFLOAT, EXPIRE
    mock_redis.pipeline.return_value = mock_pipeline

    new_value = redis_client.increment_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=5,
        cost=1.234
    )

    assert new_value == 50
    mock_pipeline.incrby.assert_called_once()
    mock_pipeline.expire.assert_called()
    mock_pipeline.incrbyfloat.assert_called_once_with(
        "budget:tenant:tenant_123:SMALL:2025-10-15:cost",
        1.234
    )


def test_increment_budget_no_cost(redis_client, mock_redis):
    """Test increment_budget() sans cost (cost=0)."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = [10, True]  # INCRBY, EXPIRE
    mock_redis.pipeline.return_value = mock_pipeline

    new_value = redis_client.increment_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=1,
        cost=0.0
    )

    assert new_value == 10
    mock_pipeline.incrby.assert_called_once()
    mock_pipeline.incrbyfloat.assert_not_called()


def test_increment_budget_not_connected(redis_client):
    """Test increment_budget() quand Redis non connecté."""
    redis_client.client = None

    new_value = redis_client.increment_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=5,
        cost=1.0
    )

    assert new_value == 0


def test_increment_budget_error(redis_client, mock_redis):
    """Test increment_budget() avec erreur Redis."""
    mock_redis.pipeline.side_effect = Exception("Pipeline error")

    new_value = redis_client.increment_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=5,
        cost=1.0
    )

    assert new_value == 0


# ============================================================================
# Tests decrement_budget()
# ============================================================================

def test_decrement_budget_success(redis_client, mock_redis):
    """Test decrement_budget() (refund) avec succès."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = [40, 0.5]  # DECRBY, INCRBYFLOAT (négatif)
    mock_redis.pipeline.return_value = mock_pipeline

    new_value = redis_client.decrement_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=3,
        cost=0.5
    )

    assert new_value == 40
    mock_pipeline.decrby.assert_called_once()
    mock_pipeline.incrbyfloat.assert_called_once_with(
        "budget:tenant:tenant_123:SMALL:2025-10-15:cost",
        -0.5
    )


def test_decrement_budget_no_cost(redis_client, mock_redis):
    """Test decrement_budget() sans cost (cost=0)."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = [35]  # DECRBY
    mock_redis.pipeline.return_value = mock_pipeline

    new_value = redis_client.decrement_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=2,
        cost=0.0
    )

    assert new_value == 35
    mock_pipeline.decrby.assert_called_once()
    mock_pipeline.incrbyfloat.assert_not_called()


def test_decrement_budget_not_connected(redis_client):
    """Test decrement_budget() quand Redis non connecté."""
    redis_client.client = None

    new_value = redis_client.decrement_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=2,
        cost=0.5
    )

    assert new_value == 0


def test_decrement_budget_error(redis_client, mock_redis):
    """Test decrement_budget() avec erreur Redis."""
    mock_redis.pipeline.side_effect = Exception("Pipeline error")

    new_value = redis_client.decrement_budget(
        tenant_id="tenant_123",
        model_tier="SMALL",
        calls=2,
        cost=0.5
    )

    assert new_value == 0


# ============================================================================
# Tests get_budget_stats()
# ============================================================================

def test_get_budget_stats_success(redis_client, mock_redis):
    """Test get_budget_stats() avec succès."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = ["150", "12.345"]  # calls, cost
    mock_redis.pipeline.return_value = mock_pipeline

    stats = redis_client.get_budget_stats("tenant_123", "SMALL")

    assert stats == {"calls": 150, "cost": 12.345}
    mock_pipeline.get.assert_called()


def test_get_budget_stats_no_data(redis_client, mock_redis):
    """Test get_budget_stats() sans données (clés inexistantes)."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = [None, None]
    mock_redis.pipeline.return_value = mock_pipeline

    stats = redis_client.get_budget_stats("tenant_123", "SMALL")

    assert stats == {"calls": 0, "cost": 0.0}


def test_get_budget_stats_not_connected(redis_client):
    """Test get_budget_stats() quand Redis non connecté."""
    redis_client.client = None

    stats = redis_client.get_budget_stats("tenant_123", "SMALL")

    assert stats == {"calls": 0, "cost": 0.0}


def test_get_budget_stats_error(redis_client, mock_redis):
    """Test get_budget_stats() avec erreur Redis."""
    mock_redis.pipeline.side_effect = Exception("Pipeline error")

    stats = redis_client.get_budget_stats("tenant_123", "SMALL")

    assert stats == {"calls": 0, "cost": 0.0}


# ============================================================================
# Tests reset_budget()
# ============================================================================

def test_reset_budget_success(redis_client, mock_redis):
    """Test reset_budget() avec succès."""
    mock_pipeline = MagicMock()
    mock_pipeline.execute.return_value = [1, 1]  # DELETE count
    mock_redis.pipeline.return_value = mock_pipeline

    result = redis_client.reset_budget("tenant_123", "SMALL")

    assert result is True
    mock_pipeline.delete.assert_called()


def test_reset_budget_not_connected(redis_client):
    """Test reset_budget() quand Redis non connecté."""
    redis_client.client = None

    result = redis_client.reset_budget("tenant_123", "SMALL")

    assert result is False


def test_reset_budget_error(redis_client, mock_redis):
    """Test reset_budget() avec erreur Redis."""
    mock_redis.pipeline.side_effect = Exception("Pipeline error")

    result = redis_client.reset_budget("tenant_123", "SMALL")

    assert result is False


# ============================================================================
# Tests get_redis_client() Singleton
# ============================================================================

def test_get_redis_client_singleton():
    """Test get_redis_client() retourne singleton."""
    with patch('knowbase.common.clients.redis_client.RedisClient') as MockRedisClient:
        mock_instance = MagicMock()
        MockRedisClient.return_value = mock_instance

        # Reset singleton
        import knowbase.common.clients.redis_client as redis_module
        redis_module._redis_client = None

        # Premier appel crée instance
        client1 = get_redis_client(host="localhost", port=6379, db=0)

        # Deuxième appel retourne même instance
        client2 = get_redis_client(host="localhost", port=6379, db=0)

        assert client1 is client2
        MockRedisClient.assert_called_once()


# ============================================================================
# Tests Intégration Budget Manager
# ============================================================================

def test_budget_key_format_consistency():
    """Test cohérence format clés entre tenant_id/tier/date."""
    with patch('knowbase.common.clients.redis_client.redis.Redis') as MockRedis:
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        MockRedis.return_value = mock_redis

        client = RedisClient(host="localhost", port=6379, db=0)

        # Test différents tiers
        key_small = client.get_budget_key("default", "SMALL", datetime(2025, 10, 15))
        key_big = client.get_budget_key("default", "BIG", datetime(2025, 10, 15))
        key_vision = client.get_budget_key("default", "VISION", datetime(2025, 10, 15))

        assert key_small == "budget:tenant:default:SMALL:2025-10-15"
        assert key_big == "budget:tenant:default:BIG:2025-10-15"
        assert key_vision == "budget:tenant:default:VISION:2025-10-15"


def test_atomic_increment_pipeline():
    """Test que increment_budget() utilise pipeline pour atomicité."""
    with patch('knowbase.common.clients.redis_client.redis.Redis') as MockRedis:
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_pipeline = MagicMock()
        mock_pipeline.execute.return_value = [100, True, 5.0, True]
        mock_redis.pipeline.return_value = mock_pipeline
        MockRedis.return_value = mock_redis

        client = RedisClient(host="localhost", port=6379, db=0)

        new_value = client.increment_budget("tenant_123", "SMALL", calls=10, cost=5.0)

        # Vérifier pipeline utilisé
        mock_redis.pipeline.assert_called_once()
        mock_pipeline.execute.assert_called_once()
        assert new_value == 100
