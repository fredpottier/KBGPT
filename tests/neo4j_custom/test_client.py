"""
Tests for Neo4j Custom Client - src/knowbase/neo4j_custom/client.py

Tests cover:
- Client initialization
- Connection management (connect, close, context manager)
- Query execution (read and write)
- Retry logic and error handling
- Health check functionality
- Singleton pattern
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Generator

import pytest

# Check if neo4j is available
try:
    import neo4j
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not NEO4J_AVAILABLE,
    reason="neo4j package not installed"
)

if NEO4J_AVAILABLE:
    from knowbase.neo4j_custom.client import (
        Neo4jCustomClient,
        Neo4jConnectionError,
        Neo4jQueryError,
        get_neo4j_client,
        close_neo4j_client,
    )


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def mock_driver() -> MagicMock:
    """Create a mock Neo4j driver."""
    driver = MagicMock()
    driver.verify_connectivity.return_value = None
    return driver


@pytest.fixture
def mock_session() -> MagicMock:
    """Create a mock Neo4j session."""
    session = MagicMock()
    return session


@pytest.fixture
def client_with_mock_driver(mock_driver: MagicMock) -> Generator[Neo4jCustomClient, None, None]:
    """Create a client with a mocked driver."""
    with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
        mock_gdb.driver.return_value = mock_driver
        client = Neo4jCustomClient(
            uri="bolt://test:7687",
            user="test_user",
            password="test_pass"
        )
        yield client


@pytest.fixture(autouse=True)
def reset_global_client() -> Generator[None, None, None]:
    """Reset global client before and after each test."""
    import knowbase.neo4j_custom.client as client_module
    original = client_module._global_client
    client_module._global_client = None
    yield
    client_module._global_client = original


# ============================================
# Test Exceptions
# ============================================

class TestExceptions:
    """Tests for custom exceptions."""

    def test_neo4j_connection_error_is_exception(self) -> None:
        """Neo4jConnectionError should be an Exception."""
        assert issubclass(Neo4jConnectionError, Exception)

    def test_neo4j_query_error_is_exception(self) -> None:
        """Neo4jQueryError should be an Exception."""
        assert issubclass(Neo4jQueryError, Exception)

    def test_connection_error_message(self) -> None:
        """Connection error should preserve message."""
        error = Neo4jConnectionError("Connection failed")
        assert str(error) == "Connection failed"

    def test_query_error_message(self) -> None:
        """Query error should preserve message."""
        error = Neo4jQueryError("Query failed")
        assert str(error) == "Query failed"


# ============================================
# Test Client Initialization
# ============================================

class TestClientInit:
    """Tests for client initialization."""

    def test_init_with_explicit_params(self) -> None:
        """Client should accept explicit parameters."""
        client = Neo4jCustomClient(
            uri="bolt://custom:7687",
            user="custom_user",
            password="custom_pass",
            database="custom_db"
        )

        assert client.uri == "bolt://custom:7687"
        assert client.user == "custom_user"
        assert client.password == "custom_pass"
        assert client.database == "custom_db"

    def test_init_with_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client should use environment variables as defaults."""
        monkeypatch.setenv("NEO4J_URI", "bolt://env:7687")
        monkeypatch.setenv("NEO4J_USER", "env_user")
        monkeypatch.setenv("NEO4J_PASSWORD", "env_pass")

        client = Neo4jCustomClient()

        assert client.uri == "bolt://env:7687"
        assert client.user == "env_user"
        assert client.password == "env_pass"

    def test_init_default_values(self) -> None:
        """Client should have sensible defaults."""
        client = Neo4jCustomClient()

        assert "localhost" in client.uri or "NEO4J_URI" in os.environ
        assert client.database == "neo4j"
        assert client.max_retry_attempts == 3

    def test_init_custom_config(self) -> None:
        """Client should accept custom configuration."""
        client = Neo4jCustomClient(
            max_connection_lifetime=7200,
            max_connection_pool_size=100,
            connection_timeout=60.0,
            max_retry_attempts=5
        )

        assert client.max_retry_attempts == 5
        assert client._driver_config["max_connection_lifetime"] == 7200
        assert client._driver_config["max_connection_pool_size"] == 100
        assert client._driver_config["connection_timeout"] == 60.0

    def test_init_driver_is_none(self) -> None:
        """Driver should be None initially (lazy connect)."""
        client = Neo4jCustomClient()
        assert client._driver is None


# ============================================
# Test Connection Management
# ============================================

class TestConnectionManagement:
    """Tests for connect and close methods."""

    def test_connect_creates_driver(self, mock_driver: MagicMock) -> None:
        """connect() should create and verify driver."""
        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jCustomClient()
            client.connect()

            mock_gdb.driver.assert_called_once()
            mock_driver.verify_connectivity.assert_called_once()
            assert client._driver is not None

    def test_connect_already_connected_warns(
        self, client_with_mock_driver: Neo4jCustomClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """connect() when already connected should warn."""
        client_with_mock_driver.connect()
        client_with_mock_driver.connect()  # Second call

        assert "already connected" in caplog.text.lower()

    def test_connect_retries_on_failure(self, mock_driver: MagicMock) -> None:
        """connect() should retry on ServiceUnavailable."""
        from neo4j.exceptions import ServiceUnavailable

        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            with patch("time.sleep"):  # Skip actual sleep
                # Fail twice, then succeed
                mock_driver.verify_connectivity.side_effect = [
                    ServiceUnavailable("Unavailable"),
                    ServiceUnavailable("Still unavailable"),
                    None  # Success on third try
                ]
                mock_gdb.driver.return_value = mock_driver

                client = Neo4jCustomClient(max_retry_attempts=3)
                client.connect()

                assert mock_driver.verify_connectivity.call_count == 3

    def test_connect_raises_after_max_retries(self, mock_driver: MagicMock) -> None:
        """connect() should raise Neo4jConnectionError after max retries."""
        from neo4j.exceptions import ServiceUnavailable

        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            with patch("time.sleep"):
                mock_driver.verify_connectivity.side_effect = ServiceUnavailable("Unavailable")
                mock_gdb.driver.return_value = mock_driver

                client = Neo4jCustomClient(max_retry_attempts=2)

                with pytest.raises(Neo4jConnectionError) as exc_info:
                    client.connect()

                assert "2 attempts" in str(exc_info.value)

    def test_close_closes_driver(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """close() should close driver and set to None."""
        client_with_mock_driver.connect()
        client_with_mock_driver.close()

        mock_driver.close.assert_called_once()
        assert client_with_mock_driver._driver is None

    def test_close_without_connection_is_noop(self) -> None:
        """close() without connection should not error."""
        client = Neo4jCustomClient()
        client.close()  # Should not raise


# ============================================
# Test Context Manager
# ============================================

class TestContextManager:
    """Tests for context manager protocol."""

    def test_context_manager_connects_and_closes(self, mock_driver: MagicMock) -> None:
        """Context manager should connect on enter and close on exit."""
        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver

            with Neo4jCustomClient() as client:
                assert client._driver is not None

            mock_driver.close.assert_called_once()

    def test_context_manager_closes_on_exception(self, mock_driver: MagicMock) -> None:
        """Context manager should close even on exception."""
        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver

            try:
                with Neo4jCustomClient() as client:
                    raise ValueError("Test error")
            except ValueError:
                pass

            mock_driver.close.assert_called_once()


# ============================================
# Test Driver Property
# ============================================

class TestDriverProperty:
    """Tests for driver property with lazy connect."""

    def test_driver_property_lazy_connects(self, mock_driver: MagicMock) -> None:
        """driver property should connect lazily."""
        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver

            client = Neo4jCustomClient()
            assert client._driver is None

            _ = client.driver

            assert client._driver is not None
            mock_driver.verify_connectivity.assert_called_once()

    def test_driver_property_returns_same_instance(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """driver property should return same driver instance."""
        client_with_mock_driver.connect()

        driver1 = client_with_mock_driver.driver
        driver2 = client_with_mock_driver.driver

        assert driver1 is driver2


# ============================================
# Test Session Context Manager
# ============================================

class TestSessionContextManager:
    """Tests for session() context manager."""

    def test_session_creates_and_closes_session(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """session() should create session and close it."""
        mock_session = MagicMock()
        mock_driver.session.return_value = mock_session

        client_with_mock_driver.connect()

        with client_with_mock_driver.session() as session:
            assert session is mock_session

        mock_session.close.assert_called_once()

    def test_session_uses_default_database(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """session() should use default database."""
        client_with_mock_driver.connect()

        with client_with_mock_driver.session():
            pass

        mock_driver.session.assert_called_with(database="neo4j")

    def test_session_accepts_custom_database(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """session() should accept custom database."""
        client_with_mock_driver.connect()

        with client_with_mock_driver.session(database="custom_db"):
            pass

        mock_driver.session.assert_called_with(database="custom_db")


# ============================================
# Test Query Execution
# ============================================

class TestExecuteQuery:
    """Tests for execute_query method."""

    def test_execute_query_returns_records(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """execute_query should return list of dicts."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25}
        ])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        records = client_with_mock_driver.execute_query("MATCH (n) RETURN n")

        assert len(records) == 2
        assert records[0]["name"] == "Alice"

    def test_execute_query_passes_parameters(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """execute_query should pass parameters to session.run."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        client_with_mock_driver.execute_query(
            "MATCH (n {name: $name}) RETURN n",
            parameters={"name": "Alice"}
        )

        mock_session.run.assert_called_with(
            "MATCH (n {name: $name}) RETURN n",
            {"name": "Alice"}
        )

    def test_execute_query_raises_on_transient_error(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """execute_query should raise Neo4jQueryError on TransientError."""
        from neo4j.exceptions import TransientError

        mock_session = MagicMock()
        mock_session.run.side_effect = TransientError("Transient")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()

        with pytest.raises(Neo4jQueryError) as exc_info:
            client_with_mock_driver.execute_query("MATCH (n) RETURN n")

        assert "Transient" in str(exc_info.value)

    def test_execute_query_raises_on_generic_error(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """execute_query should raise Neo4jQueryError on any exception."""
        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("Something went wrong")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()

        with pytest.raises(Neo4jQueryError) as exc_info:
            client_with_mock_driver.execute_query("MATCH (n) RETURN n")

        assert "Query failed" in str(exc_info.value)


# ============================================
# Test Write Query Execution
# ============================================

class TestExecuteWriteQuery:
    """Tests for execute_write_query method."""

    def test_execute_write_query_uses_write_transaction(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """execute_write_query should use execute_write."""
        mock_session = MagicMock()
        mock_session.execute_write.return_value = [{"id": 1}]
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        result = client_with_mock_driver.execute_write_query(
            "CREATE (n:Test {name: $name}) RETURN id(n)",
            parameters={"name": "Test"}
        )

        mock_session.execute_write.assert_called_once()
        assert result == [{"id": 1}]

    def test_execute_write_query_raises_on_error(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """execute_write_query should raise Neo4jQueryError on error."""
        mock_session = MagicMock()
        mock_session.execute_write.side_effect = RuntimeError("Write failed")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()

        with pytest.raises(Neo4jQueryError) as exc_info:
            client_with_mock_driver.execute_write_query("CREATE (n) RETURN n")

        assert "Write query failed" in str(exc_info.value)


# ============================================
# Test Connectivity Verification
# ============================================

class TestVerifyConnectivity:
    """Tests for verify_connectivity method."""

    def test_verify_connectivity_returns_true_when_connected(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """verify_connectivity should return True when connected."""
        client_with_mock_driver.connect()
        result = client_with_mock_driver.verify_connectivity()
        assert result is True

    def test_verify_connectivity_returns_false_on_error(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """verify_connectivity should return False on error."""
        client_with_mock_driver.connect()
        mock_driver.verify_connectivity.side_effect = RuntimeError("Failed")

        result = client_with_mock_driver.verify_connectivity()
        assert result is False


# ============================================
# Test Server Info
# ============================================

class TestGetServerInfo:
    """Tests for get_server_info method."""

    def test_get_server_info_returns_dict(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """get_server_info should return server info dict."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            "name": "Neo4j Kernel",
            "versions": ["5.0.0"],
            "edition": "community"
        }[key]
        mock_result.single.return_value = mock_record
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        info = client_with_mock_driver.get_server_info()

        assert info["name"] == "Neo4j Kernel"
        assert info["versions"] == ["5.0.0"]
        assert info["edition"] == "community"

    def test_get_server_info_returns_empty_on_error(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """get_server_info should return empty dict on error."""
        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("Failed")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        info = client_with_mock_driver.get_server_info()

        assert info == {}


# ============================================
# Test Health Check
# ============================================

class TestHealthCheck:
    """Tests for health_check method."""

    def test_health_check_healthy(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """health_check should return healthy status."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"count": 100}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        health = client_with_mock_driver.health_check()

        assert health["status"] == "healthy"
        assert health["node_count"] == 100
        assert health["latency_ms"] is not None
        assert health["error"] is None

    def test_health_check_unhealthy(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """health_check should return unhealthy on error."""
        mock_session = MagicMock()
        mock_session.run.side_effect = RuntimeError("Database unavailable")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        health = client_with_mock_driver.health_check()

        assert health["status"] == "unhealthy"
        assert health["error"] is not None
        assert "unavailable" in health["error"].lower()


# ============================================
# Test Singleton Functions
# ============================================

class TestSingletonFunctions:
    """Tests for get_neo4j_client and close_neo4j_client."""

    def test_get_neo4j_client_creates_singleton(self, mock_driver: MagicMock) -> None:
        """get_neo4j_client should create and return singleton."""
        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver

            client1 = get_neo4j_client()
            client2 = get_neo4j_client()

            assert client1 is client2

    def test_close_neo4j_client_closes_singleton(self, mock_driver: MagicMock) -> None:
        """close_neo4j_client should close and clear singleton."""
        import knowbase.neo4j_custom.client as client_module

        with patch("knowbase.neo4j_custom.client.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver

            client = get_neo4j_client()
            close_neo4j_client()

            mock_driver.close.assert_called_once()
            assert client_module._global_client is None

    def test_close_neo4j_client_noop_when_none(self) -> None:
        """close_neo4j_client should be noop when no client."""
        import knowbase.neo4j_custom.client as client_module

        client_module._global_client = None
        close_neo4j_client()  # Should not raise


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_query_result(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """Query returning no results should return empty list."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        result = client_with_mock_driver.execute_query("MATCH (n:NonExistent) RETURN n")

        assert result == []

    def test_query_with_none_parameters(
        self, client_with_mock_driver: Neo4jCustomClient, mock_driver: MagicMock
    ) -> None:
        """Query with None parameters should use empty dict."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.connect()
        client_with_mock_driver.execute_query("MATCH (n) RETURN n", parameters=None)

        mock_session.run.assert_called_with("MATCH (n) RETURN n", {})
