"""
Tests for ResilientRedisClient - src/knowbase/common/redis_client_resilient.py

Tests cover:
- Redis retry decorator with exponential backoff
- ResilientRedisClient initialization
- All Redis operations with retry behavior
- Error handling and connection failures
- Context manager functionality
- Factory function
"""
from __future__ import annotations

import sys
import time
from typing import Generator
from unittest.mock import MagicMock, patch, call

import pytest


# Create mock exceptions that inherit from Exception for testing
class MockRedisConnectionError(Exception):
    """Mock Redis connection error for testing."""
    pass


class MockRedisTimeoutError(Exception):
    """Mock Redis timeout error for testing."""
    pass


# Create the mock redis module with proper exceptions
mock_redis = MagicMock()
mock_redis.ConnectionError = MockRedisConnectionError
mock_redis.TimeoutError = MockRedisTimeoutError
mock_redis.Redis = MagicMock()

# Patch at module level
sys.modules['redis'] = mock_redis

from knowbase.common.redis_client_resilient import (
    RedisConnectionError,
    redis_retry,
    ResilientRedisClient,
    create_resilient_redis_client,
)


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Create a mock Redis client."""
    return MagicMock()


@pytest.fixture
def resilient_client(mock_redis_client: MagicMock) -> ResilientRedisClient:
    """Create a ResilientRedisClient with mocked underlying client."""
    with patch('redis.Redis') as mock_redis_cls:
        mock_redis_cls.from_url.return_value = mock_redis_client
        client = ResilientRedisClient(
            redis_url="redis://localhost:6379/0",
            max_retries=3,
            base_delay=0.01,  # Fast delays for tests
        )
        return client


# ============================================
# Test RedisConnectionError
# ============================================

class TestRedisConnectionError:
    """Tests for RedisConnectionError exception."""

    def test_is_exception_subclass(self) -> None:
        """RedisConnectionError should be an Exception."""
        assert issubclass(RedisConnectionError, Exception)

    def test_message_preserved(self) -> None:
        """Error message should be preserved."""
        error = RedisConnectionError("Connection failed")
        assert str(error) == "Connection failed"

    def test_can_be_raised_and_caught(self) -> None:
        """Error can be raised and caught."""
        with pytest.raises(RedisConnectionError) as exc_info:
            raise RedisConnectionError("Test error")
        assert "Test error" in str(exc_info.value)


# ============================================
# Test redis_retry Decorator
# ============================================

class TestRedisRetryDecorator:
    """Tests for redis_retry decorator."""

    def test_successful_operation_no_retry(self) -> None:
        """Successful operation should not retry."""
        call_count = 0

        @redis_retry(max_retries=3, base_delay=0.01)
        def successful_operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_operation()

        assert result == "success"
        assert call_count == 1

    def test_retry_on_connection_error(self) -> None:
        """Should retry on ConnectionError."""
        call_count = 0

        @redis_retry(max_retries=2, base_delay=0.01)
        def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise MockRedisConnectionError("Connection lost")
            return "success"

        result = flaky_operation()

        assert result == "success"
        assert call_count == 3  # 1 initial + 2 retries

    def test_retry_on_timeout_error(self) -> None:
        """Should retry on TimeoutError."""
        call_count = 0

        @redis_retry(max_retries=2, base_delay=0.01)
        def timeout_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise MockRedisTimeoutError("Operation timed out")
            return "success"

        result = timeout_operation()

        assert result == "success"
        assert call_count == 2

    def test_no_retry_on_other_exceptions(self) -> None:
        """Should not retry on non-connection exceptions."""
        call_count = 0

        @redis_retry(max_retries=3, base_delay=0.01)
        def other_error_operation():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not a connection error")

        with pytest.raises(ValueError):
            other_error_operation()

        assert call_count == 1  # No retries

    def test_raises_redis_connection_error_after_max_retries(self) -> None:
        """Should raise RedisConnectionError after all retries fail."""
        call_count = 0

        @redis_retry(max_retries=2, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise MockRedisConnectionError("Always fails")

        with pytest.raises(RedisConnectionError) as exc_info:
            always_fails()

        assert call_count == 3  # 1 initial + 2 retries
        assert "3 attempts" in str(exc_info.value)

    def test_exponential_backoff_delays(self) -> None:
        """Should use exponential backoff between retries."""
        delays = []

        def mock_sleep(duration):
            delays.append(duration)

        call_count = 0

        @redis_retry(max_retries=3, base_delay=1.0, max_delay=10.0, exponential_base=2.0)
        def failing_operation():
            nonlocal call_count
            call_count += 1
            raise MockRedisConnectionError("Fail")

        with patch('knowbase.common.redis_client_resilient.time.sleep', mock_sleep):
            with pytest.raises(RedisConnectionError):
                failing_operation()

        # Expected delays: 1.0, 2.0, 4.0
        assert len(delays) == 3
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)
        assert delays[2] == pytest.approx(4.0)

    def test_max_delay_cap(self) -> None:
        """Delay should be capped at max_delay."""
        delays = []

        def mock_sleep(duration):
            delays.append(duration)

        @redis_retry(max_retries=5, base_delay=1.0, max_delay=3.0, exponential_base=2.0)
        def failing_operation():
            raise MockRedisConnectionError("Fail")

        with patch('knowbase.common.redis_client_resilient.time.sleep', mock_sleep):
            with pytest.raises(RedisConnectionError):
                failing_operation()

        # Delays: 1.0, 2.0, 3.0 (capped), 3.0 (capped), 3.0 (capped)
        assert all(d <= 3.0 for d in delays)

    def test_preserves_function_return_value(self) -> None:
        """Should preserve the original return value."""
        @redis_retry(max_retries=2, base_delay=0.01)
        def return_dict():
            return {"key": "value", "count": 42}

        result = return_dict()

        assert result == {"key": "value", "count": 42}

    def test_preserves_function_arguments(self) -> None:
        """Should pass arguments to decorated function."""
        @redis_retry(max_retries=2, base_delay=0.01)
        def with_args(a: int, b: str, multiply: bool = False):
            return f"{a}-{b}-{multiply}"

        result = with_args(1, "test", multiply=True)

        assert result == "1-test-True"


# ============================================
# Test ResilientRedisClient Initialization
# ============================================

class TestResilientRedisClientInit:
    """Tests for ResilientRedisClient initialization."""

    def test_init_creates_redis_client(self) -> None:
        """Should create underlying Redis client."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_client = MagicMock()
            mock_redis_cls.from_url.return_value = mock_client

            client = ResilientRedisClient(
                redis_url="redis://localhost:6379/0",
                max_retries=5,
                base_delay=2.0,
            )

            mock_redis_cls.from_url.assert_called_once()
            call_kwargs = mock_redis_cls.from_url.call_args[1]
            assert call_kwargs['decode_responses'] is True
            assert call_kwargs['retry_on_timeout'] is True

    def test_init_with_custom_timeouts(self) -> None:
        """Should configure custom timeouts."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_client = MagicMock()
            mock_redis_cls.from_url.return_value = mock_client

            ResilientRedisClient(
                redis_url="redis://localhost:6379/0",
                socket_connect_timeout=10,
                socket_timeout=15,
            )

            call_kwargs = mock_redis_cls.from_url.call_args[1]
            assert call_kwargs['socket_connect_timeout'] == 10
            assert call_kwargs['socket_timeout'] == 15

    def test_stores_configuration(self) -> None:
        """Should store configuration values."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()

            client = ResilientRedisClient(
                redis_url="redis://test:6379/1",
                max_retries=7,
                base_delay=3.0,
            )

            assert client.redis_url == "redis://test:6379/1"
            assert client.max_retries == 7
            assert client.base_delay == 3.0


# ============================================
# Test Redis Operations
# ============================================

class TestResilientRedisClientOperations:
    """Tests for Redis operations with retry."""

    def test_get_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test get operation."""
        mock_redis_client.get.return_value = "value"

        result = resilient_client.get("key")

        assert result == "value"
        mock_redis_client.get.assert_called_once_with("key")

    def test_set_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test set operation."""
        mock_redis_client.set.return_value = True

        result = resilient_client.set("key", "value", ex=3600, nx=True)

        assert result is True
        mock_redis_client.set.assert_called_once_with("key", "value", ex=3600, nx=True)

    def test_setex_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test setex operation."""
        mock_redis_client.setex.return_value = True

        result = resilient_client.setex("key", 3600, "value")

        assert result is True
        mock_redis_client.setex.assert_called_once_with("key", 3600, "value")

    def test_delete_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test delete operation."""
        mock_redis_client.delete.return_value = 2

        result = resilient_client.delete("key1", "key2")

        assert result == 2
        mock_redis_client.delete.assert_called_once_with("key1", "key2")

    def test_exists_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test exists operation."""
        mock_redis_client.exists.return_value = 1

        result = resilient_client.exists("key")

        assert result == 1
        mock_redis_client.exists.assert_called_once_with("key")

    def test_expire_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test expire operation."""
        mock_redis_client.expire.return_value = True

        result = resilient_client.expire("key", 3600)

        assert result is True
        mock_redis_client.expire.assert_called_once_with("key", 3600)

    def test_ttl_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test ttl operation."""
        mock_redis_client.ttl.return_value = 3600

        result = resilient_client.ttl("key")

        assert result == 3600
        mock_redis_client.ttl.assert_called_once_with("key")

    def test_keys_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test keys operation."""
        mock_redis_client.keys.return_value = ["key1", "key2"]

        result = resilient_client.keys("key*")

        assert result == ["key1", "key2"]
        mock_redis_client.keys.assert_called_once_with("key*")

    def test_ping_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test ping operation."""
        mock_redis_client.ping.return_value = True

        result = resilient_client.ping()

        assert result is True
        mock_redis_client.ping.assert_called_once()

    def test_flushdb_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test flushdb operation."""
        mock_redis_client.flushdb.return_value = True

        result = resilient_client.flushdb()

        assert result is True
        mock_redis_client.flushdb.assert_called_once()


# ============================================
# Test Hash Operations
# ============================================

class TestResilientRedisClientHashOperations:
    """Tests for Redis hash operations."""

    def test_hset_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test hset operation."""
        mock_redis_client.hset.return_value = 1

        result = resilient_client.hset("hash", "field", "value")

        assert result == 1
        mock_redis_client.hset.assert_called_once_with("hash", "field", "value")

    def test_hget_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test hget operation."""
        mock_redis_client.hget.return_value = "value"

        result = resilient_client.hget("hash", "field")

        assert result == "value"
        mock_redis_client.hget.assert_called_once_with("hash", "field")

    def test_hgetall_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test hgetall operation."""
        mock_redis_client.hgetall.return_value = {"field1": "value1", "field2": "value2"}

        result = resilient_client.hgetall("hash")

        assert result == {"field1": "value1", "field2": "value2"}
        mock_redis_client.hgetall.assert_called_once_with("hash")

    def test_hdel_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test hdel operation."""
        mock_redis_client.hdel.return_value = 2

        result = resilient_client.hdel("hash", "field1", "field2")

        assert result == 2
        mock_redis_client.hdel.assert_called_once_with("hash", "field1", "field2")


# ============================================
# Test List Operations
# ============================================

class TestResilientRedisClientListOperations:
    """Tests for Redis list operations."""

    def test_lpush_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test lpush operation."""
        mock_redis_client.lpush.return_value = 3

        result = resilient_client.lpush("list", "v1", "v2", "v3")

        assert result == 3
        mock_redis_client.lpush.assert_called_once_with("list", "v1", "v2", "v3")

    def test_rpush_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test rpush operation."""
        mock_redis_client.rpush.return_value = 2

        result = resilient_client.rpush("list", "v1", "v2")

        assert result == 2
        mock_redis_client.rpush.assert_called_once_with("list", "v1", "v2")

    def test_lrange_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test lrange operation."""
        mock_redis_client.lrange.return_value = ["v1", "v2", "v3"]

        result = resilient_client.lrange("list", 0, -1)

        assert result == ["v1", "v2", "v3"]
        mock_redis_client.lrange.assert_called_once_with("list", 0, -1)

    def test_llen_operation(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Test llen operation."""
        mock_redis_client.llen.return_value = 5

        result = resilient_client.llen("list")

        assert result == 5
        mock_redis_client.llen.assert_called_once_with("list")


# ============================================
# Test Context Manager
# ============================================

class TestResilientRedisClientContextManager:
    """Tests for context manager functionality."""

    def test_context_manager_enter(self) -> None:
        """Context manager should return self on enter."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()

            client = ResilientRedisClient(redis_url="redis://localhost:6379/0")

            with client as ctx:
                assert ctx is client

    def test_context_manager_closes_on_exit(self) -> None:
        """Context manager should close client on exit."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_client = MagicMock()
            mock_redis_cls.from_url.return_value = mock_client

            with ResilientRedisClient(redis_url="redis://localhost:6379/0"):
                pass

            mock_client.close.assert_called_once()

    def test_close_method(self) -> None:
        """Close method should close underlying client."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_client = MagicMock()
            mock_redis_cls.from_url.return_value = mock_client

            client = ResilientRedisClient(redis_url="redis://localhost:6379/0")
            client.close()

            mock_client.close.assert_called_once()

    def test_close_handles_error(self) -> None:
        """Close should handle errors gracefully."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_client = MagicMock()
            mock_client.close.side_effect = Exception("Close error")
            mock_redis_cls.from_url.return_value = mock_client

            client = ResilientRedisClient(redis_url="redis://localhost:6379/0")

            # Should not raise
            client.close()


# ============================================
# Test Factory Function
# ============================================

class TestCreateResilientRedisClient:
    """Tests for create_resilient_redis_client factory function."""

    def test_creates_client_with_defaults(self) -> None:
        """Should create client with default values."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()

            client = create_resilient_redis_client()

            assert client.redis_url == "redis://redis:6379/0"
            assert client.max_retries == 3

    def test_creates_client_with_custom_url(self) -> None:
        """Should create client with custom URL."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()

            client = create_resilient_redis_client(
                redis_url="redis://custom:6380/1"
            )

            assert client.redis_url == "redis://custom:6380/1"

    def test_creates_client_with_custom_retries(self) -> None:
        """Should create client with custom retry count."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()

            client = create_resilient_redis_client(max_retries=10)

            assert client.max_retries == 10

    def test_passes_kwargs_to_client(self) -> None:
        """Should pass additional kwargs to client."""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()

            client = create_resilient_redis_client(
                redis_url="redis://localhost:6379/0",
                base_delay=5.0,
                socket_timeout=30,
            )

            assert client.base_delay == 5.0


# ============================================
# Test Error Handling
# ============================================

class TestResilientRedisClientErrorHandling:
    """Tests for error handling scenarios."""

    def test_operation_retries_on_connection_error(self) -> None:
        """Operations should retry on connection errors."""
        mock_client = MagicMock()
        call_count = 0

        def get_with_failures(key):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise MockRedisConnectionError("Connection lost")
            return "value"

        mock_client.get.side_effect = get_with_failures
        mock_redis.Redis.from_url.return_value = mock_client

        with patch('knowbase.common.redis_client_resilient.time.sleep'):  # Speed up test
            client = ResilientRedisClient(
                redis_url="redis://localhost:6379/0",
                max_retries=3,
                base_delay=0.01,
            )
            result = client.get("key")

        assert result == "value"
        assert call_count == 3

    def test_get_returns_none_for_missing_key(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Get should return None for missing keys."""
        mock_redis_client.get.return_value = None

        result = resilient_client.get("nonexistent")

        assert result is None


# ============================================
# Test Edge Cases
# ============================================

class TestResilientRedisClientEdgeCases:
    """Tests for edge cases."""

    def test_empty_key_list_delete(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Delete with no keys should work."""
        mock_redis_client.delete.return_value = 0

        result = resilient_client.delete()

        assert result == 0

    def test_keys_with_wildcard_pattern(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Keys should work with wildcard patterns."""
        mock_redis_client.keys.return_value = ["prefix:1", "prefix:2"]

        result = resilient_client.keys("prefix:*")

        assert result == ["prefix:1", "prefix:2"]
        mock_redis_client.keys.assert_called_with("prefix:*")

    def test_default_keys_pattern(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Keys without pattern should use default wildcard."""
        mock_redis_client.keys.return_value = []

        resilient_client.keys()

        mock_redis_client.keys.assert_called_with("*")

    def test_set_with_none_expiry(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Set with None expiry should work."""
        mock_redis_client.set.return_value = True

        result = resilient_client.set("key", "value", ex=None)

        assert result is True
        mock_redis_client.set.assert_called_with("key", "value", ex=None, nx=False)

    def test_multiple_exists_keys(
        self, resilient_client: ResilientRedisClient, mock_redis_client: MagicMock
    ) -> None:
        """Exists with multiple keys should return count."""
        mock_redis_client.exists.return_value = 2

        result = resilient_client.exists("key1", "key2", "key3")

        assert result == 2
        mock_redis_client.exists.assert_called_once_with("key1", "key2", "key3")
