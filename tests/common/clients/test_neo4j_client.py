"""
Tests for Neo4j Client - src/knowbase/common/clients/neo4j_client.py

Tests cover:
- Client initialization and connection management
- Proto-KG concept creation and retrieval
- Published-KG promotion and retrieval
- Concept linking functionality
- Distributed lock mechanism (Redis integration)
- Tenant statistics
- Error handling and edge cases
- Singleton pattern

Author: Test Suite Generator
Date: 2025-12
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

# Check if neo4j is available
try:
    import neo4j
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not NEO4J_AVAILABLE,
    reason="neo4j package not installed"
)

if NEO4J_AVAILABLE:
    from knowbase.common.clients.neo4j_client import (
        Neo4jClient,
        get_neo4j_client,
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
def mock_redis_client() -> MagicMock:
    """Create a mock Redis client for distributed locks."""
    redis = MagicMock()
    redis.set.return_value = True
    redis.delete.return_value = 1
    return redis


@pytest.fixture
def client_with_mock_driver(
    mock_driver: MagicMock
) -> Generator[Neo4jClient, None, None]:
    """Create a Neo4jClient with a mocked driver."""
    with patch.object(GraphDatabase, "driver", return_value=mock_driver):
        client = Neo4jClient(
            uri="bolt://test:7687",
            user="test_user",
            password="test_pass",
            database="test_db"
        )
        yield client
        if client.driver:
            client.close()


@pytest.fixture
def client_with_redis(
    mock_driver: MagicMock,
    mock_redis_client: MagicMock
) -> Generator[Neo4jClient, None, None]:
    """Create a Neo4jClient with mocked driver and Redis."""
    with patch.object(GraphDatabase, "driver", return_value=mock_driver):
        client = Neo4jClient(
            uri="bolt://test:7687",
            user="test_user",
            password="test_pass",
            database="test_db",
            redis_client=mock_redis_client
        )
        yield client
        if client.driver:
            client.close()


@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None, None, None]:
    """Reset global singleton before and after each test."""
    import knowbase.common.clients.neo4j_client as module
    original = getattr(module, "_neo4j_client", None)
    module._neo4j_client = None
    yield
    module._neo4j_client = original


# ============================================
# Test Client Initialization
# ============================================

class TestNeo4jClientInit:
    """Tests for Neo4jClient initialization."""

    def test_init_with_default_params(self) -> None:
        """Client should accept default parameters."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.return_value = MagicMock()
            mock_gdb.return_value.verify_connectivity.return_value = None

            client = Neo4jClient()

            assert client.uri == "bolt://localhost:7687"
            assert client.user == "neo4j"
            assert client.database == "neo4j"

    def test_init_with_custom_params(self) -> None:
        """Client should accept custom parameters."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.return_value = MagicMock()
            mock_gdb.return_value.verify_connectivity.return_value = None

            client = Neo4jClient(
                uri="bolt://custom:7688",
                user="custom_user",
                password="custom_pass",
                database="custom_db"
            )

            assert client.uri == "bolt://custom:7688"
            assert client.user == "custom_user"
            assert client.database == "custom_db"

    def test_init_with_redis_client(
        self, mock_driver: MagicMock, mock_redis_client: MagicMock
    ) -> None:
        """Client should accept Redis client for distributed locks."""
        with patch.object(GraphDatabase, "driver", return_value=mock_driver):
            client = Neo4jClient(
                uri="bolt://test:7687",
                user="test",
                password="test",
                redis_client=mock_redis_client
            )

            assert client.redis_client is mock_redis_client

    def test_init_connection_failure_sets_driver_none(self) -> None:
        """Failed connection should set driver to None."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")

            client = Neo4jClient()

            assert client.driver is None

    def test_init_verifies_connectivity(self, mock_driver: MagicMock) -> None:
        """Init should verify connectivity."""
        with patch.object(GraphDatabase, "driver", return_value=mock_driver):
            Neo4jClient()

            mock_driver.verify_connectivity.assert_called_once()


# ============================================
# Test Connection Management
# ============================================

class TestConnectionManagement:
    """Tests for connection management methods."""

    def test_is_connected_returns_true_when_connected(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """is_connected should return True when driver connected."""
        assert client_with_mock_driver.is_connected() is True

    def test_is_connected_returns_false_when_driver_none(self) -> None:
        """is_connected should return False when driver is None."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            assert client.is_connected() is False

    def test_is_connected_returns_false_on_verify_failure(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """is_connected should return False if verify_connectivity fails."""
        mock_driver.verify_connectivity.side_effect = Exception("Lost connection")

        assert client_with_mock_driver.is_connected() is False

    def test_close_closes_driver(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """close should close the driver."""
        client_with_mock_driver.close()

        mock_driver.close.assert_called_once()


# ============================================
# Test Distributed Lock (Redis Integration)
# ============================================

class TestDistributedLock:
    """Tests for Redis distributed lock mechanism."""

    def test_acquire_lock_without_redis_returns_true(
        self, client_with_mock_driver: Neo4jClient
    ) -> None:
        """Without Redis, _acquire_lock should return True (graceful degradation)."""
        assert client_with_mock_driver.redis_client is None
        result = client_with_mock_driver._acquire_lock("test:lock", timeout_sec=5)
        assert result is True

    def test_acquire_lock_with_redis_success(
        self, client_with_redis: Neo4jClient, mock_redis_client: MagicMock
    ) -> None:
        """With Redis, successful lock acquisition returns True."""
        mock_redis_client.set.return_value = True

        result = client_with_redis._acquire_lock("test:lock", timeout_sec=5)

        assert result is True
        mock_redis_client.set.assert_called_once_with(
            "test:lock", "locked", nx=True, ex=5
        )

    def test_acquire_lock_with_redis_failure(
        self, client_with_redis: Neo4jClient, mock_redis_client: MagicMock
    ) -> None:
        """With Redis, failed lock acquisition returns False."""
        mock_redis_client.set.return_value = False  # Lock already held

        result = client_with_redis._acquire_lock("test:lock", timeout_sec=5)

        assert result is False

    def test_acquire_lock_redis_error_graceful_degradation(
        self, client_with_redis: Neo4jClient, mock_redis_client: MagicMock
    ) -> None:
        """Redis error should gracefully degrade (return True)."""
        mock_redis_client.set.side_effect = Exception("Redis unavailable")

        result = client_with_redis._acquire_lock("test:lock", timeout_sec=5)

        assert result is True  # Graceful degradation

    def test_release_lock_without_redis_noop(
        self, client_with_mock_driver: Neo4jClient
    ) -> None:
        """Without Redis, _release_lock should be a no-op."""
        # Should not raise
        client_with_mock_driver._release_lock("test:lock")

    def test_release_lock_with_redis(
        self, client_with_redis: Neo4jClient, mock_redis_client: MagicMock
    ) -> None:
        """With Redis, _release_lock should delete the key."""
        client_with_redis._release_lock("test:lock")

        mock_redis_client.delete.assert_called_once_with("test:lock")

    def test_release_lock_redis_error_handled(
        self, client_with_redis: Neo4jClient, mock_redis_client: MagicMock
    ) -> None:
        """Redis error during release should be handled gracefully."""
        mock_redis_client.delete.side_effect = Exception("Redis error")

        # Should not raise
        client_with_redis._release_lock("test:lock")


# ============================================
# Test Proto-KG Concept Creation
# ============================================

class TestProtoConceptCreation:
    """Tests for Proto-KG concept creation."""

    def test_create_proto_concept_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should return empty string when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.create_proto_concept(
                tenant_id="tenant1",
                concept_name="Test Concept",
                concept_type="Product",
                segment_id="seg1",
                document_id="doc1"
            )

            assert result == ""

    def test_create_proto_concept_success(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should create and return concept_id."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="SAP S/4HANA",
            concept_type="Product",
            segment_id="seg1",
            document_id="doc1",
            extraction_method="NER",
            confidence=0.95
        )

        assert result == "uuid-123"
        mock_session.run.assert_called_once()

    def test_create_proto_concept_normalizes_name(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should normalize concept name (lowercase, strip)."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="  SAP S/4HANA  ",
            concept_type="Product",
            segment_id="seg1",
            document_id="doc1"
        )

        # Verify normalized name is passed
        call_args = mock_session.run.call_args
        assert call_args is not None
        params = call_args.kwargs
        assert params["concept_name_normalized"] == "sap s/4hana"

    def test_create_proto_concept_with_metadata(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle metadata correctly."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        metadata = {"source": "slide-5", "page": 10}

        client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="Test",
            concept_type="Concept",
            segment_id="seg1",
            document_id="doc1",
            metadata=metadata
        )

        call_args = mock_session.run.call_args
        params = call_args.kwargs
        assert params["metadata_json"] == json.dumps(metadata)

    def test_create_proto_concept_with_chunk_ids(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle chunk_ids for cross-reference."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        chunk_ids = ["chunk-1", "chunk-2", "chunk-3"]

        client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="Test",
            concept_type="Concept",
            segment_id="seg1",
            document_id="doc1",
            chunk_ids=chunk_ids
        )

        call_args = mock_session.run.call_args
        params = call_args.kwargs
        assert params["chunk_ids"] == chunk_ids

    def test_create_proto_concept_error_handling(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle errors gracefully."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Database error")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="Test",
            concept_type="Concept",
            segment_id="seg1",
            document_id="doc1"
        )

        assert result == ""


# ============================================
# Test Proto-KG Concept Retrieval
# ============================================

class TestProtoConceptRetrieval:
    """Tests for Proto-KG concept retrieval."""

    def test_get_proto_concepts_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """get_proto_concepts should return empty list when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.get_proto_concepts(tenant_id="tenant1")

            assert result == []

    def test_get_proto_concepts_basic(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_proto_concepts should return list of concepts."""
        mock_session = MagicMock()
        mock_records = [
            {
                "concept_id": "uuid-1",
                "concept_name": "SAP S/4HANA",
                "concept_type": "Product",
                "segment_id": "seg1",
                "document_id": "doc1",
                "extraction_method": "NER",
                "confidence": 0.95,
                "metadata": {},
                "created_at": datetime.utcnow()
            },
            {
                "concept_id": "uuid-2",
                "concept_name": "SAP BTP",
                "concept_type": "Platform",
                "segment_id": "seg2",
                "document_id": "doc1",
                "extraction_method": "LLM",
                "confidence": 0.88,
                "metadata": {},
                "created_at": datetime.utcnow()
            }
        ]
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(mock_records)
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.get_proto_concepts(tenant_id="tenant1")

        assert len(result) == 2
        assert result[0]["concept_name"] == "SAP S/4HANA"
        assert result[1]["concept_name"] == "SAP BTP"

    def test_get_proto_concepts_with_filters(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_proto_concepts should apply filters correctly."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.get_proto_concepts(
            tenant_id="tenant1",
            segment_id="seg1",
            document_id="doc1",
            concept_type="Product"
        )

        call_args = mock_session.run.call_args
        query = call_args.args[0] if call_args.args else call_args.kwargs.get("query", "")

        # Verify filters are in query
        assert "segment_id" in str(call_args)
        assert "document_id" in str(call_args)
        assert "concept_type" in str(call_args)

    def test_get_proto_concepts_error_handling(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_proto_concepts should handle errors gracefully."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Query failed")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.get_proto_concepts(tenant_id="tenant1")

        assert result == []


# ============================================
# Test Find Canonical Concept
# ============================================

class TestFindCanonicalConcept:
    """Tests for find_canonical_concept method."""

    def test_find_canonical_concept_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """find_canonical_concept should return None when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.find_canonical_concept(
                tenant_id="tenant1",
                canonical_name="SAP S/4HANA"
            )

            assert result is None

    def test_find_canonical_concept_found(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """find_canonical_concept should return canonical_id when found."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"canonical_id": "canonical-uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.find_canonical_concept(
            tenant_id="tenant1",
            canonical_name="SAP S/4HANA"
        )

        assert result == "canonical-uuid-123"

    def test_find_canonical_concept_not_found(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """find_canonical_concept should return None when not found."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.find_canonical_concept(
            tenant_id="tenant1",
            canonical_name="NonExistent"
        )

        assert result is None

    def test_find_canonical_concept_error_handling(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """find_canonical_concept should handle errors gracefully."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Query failed")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.find_canonical_concept(
            tenant_id="tenant1",
            canonical_name="Test"
        )

        assert result is None


# ============================================
# Test Promote to Published
# ============================================

class TestPromoteToPublished:
    """Tests for promote_to_published method."""

    def test_promote_to_published_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """promote_to_published should return empty string when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.promote_to_published(
                tenant_id="tenant1",
                proto_concept_id="proto-uuid",
                canonical_name="SAP S/4HANA",
                unified_definition="Enterprise resource planning solution"
            )

            assert result == ""

    def test_promote_to_published_creates_new_canonical(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """promote_to_published should create new CanonicalConcept."""
        mock_session = MagicMock()

        # Mock find_canonical_concept returning None (no existing)
        find_result = MagicMock()
        find_result.single.return_value = None

        # Mock create result
        create_result = MagicMock()
        create_result.single.return_value = {
            "canonical_id": "canonical-uuid-new",
            "canonical_name": "SAP S/4HANA",
            "surface_form": "SAP S/4 HANA",
            "chunk_count": 5,
            "document_count": 1
        }

        mock_session.run.side_effect = [find_result, create_result]
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="SAP S/4HANA",
            unified_definition="ERP solution",
            quality_score=0.92,
            surface_form="SAP S/4 HANA",
            chunk_ids=["chunk-1", "chunk-2"]
        )

        assert result == "canonical-uuid-new"

    def test_promote_to_published_deduplication_links_existing(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """promote_to_published with deduplication should link to existing."""
        mock_session = MagicMock()

        # Mock find_canonical_concept returning existing
        find_result = MagicMock()
        find_result.single.return_value = {"canonical_id": "existing-canonical-id"}

        # Mock aggregate/link result
        link_result = MagicMock()
        link_result.single.return_value = {
            "canonical_id": "existing-canonical-id",
            "canonical_name": "SAP S/4HANA",
            "chunk_count": 10,
            "document_count": 2
        }

        mock_session.run.side_effect = [find_result, link_result]
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid-2",
            canonical_name="SAP S/4HANA",
            unified_definition="ERP solution",
            deduplicate=True
        )

        assert result == "existing-canonical-id"

    def test_promote_to_published_without_deduplication(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """promote_to_published without deduplication always creates new."""
        mock_session = MagicMock()

        # Mock create result (skips find step)
        create_result = MagicMock()
        create_result.single.return_value = {
            "canonical_id": "canonical-uuid-new",
            "canonical_name": "SAP S/4HANA",
            "surface_form": None,
            "chunk_count": 0,
            "document_count": 1
        }

        mock_session.run.return_value = create_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="SAP S/4HANA",
            unified_definition="ERP solution",
            deduplicate=False
        )

        assert result == "canonical-uuid-new"

    def test_promote_to_published_with_decision_trace(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """promote_to_published should store decision trace JSON."""
        mock_session = MagicMock()

        find_result = MagicMock()
        find_result.single.return_value = None

        create_result = MagicMock()
        create_result.single.return_value = {
            "canonical_id": "canonical-uuid",
            "canonical_name": "Test",
            "surface_form": None,
            "chunk_count": 0,
            "document_count": 1
        }

        mock_session.run.side_effect = [find_result, create_result]
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        decision_trace = json.dumps({"method": "LLM", "confidence": 0.95})

        client_with_mock_driver.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="Test",
            unified_definition="Test definition",
            decision_trace_json=decision_trace
        )

        # Verify decision_trace_json is passed to query
        call_args = mock_session.run.call_args_list[-1]
        params = call_args.kwargs
        assert params.get("decision_trace_json") == decision_trace

    def test_promote_to_published_uses_distributed_lock(
        self, client_with_redis: Neo4jClient,
        mock_driver: MagicMock,
        mock_redis_client: MagicMock
    ) -> None:
        """promote_to_published should use distributed lock with Redis."""
        mock_session = MagicMock()

        find_result = MagicMock()
        find_result.single.return_value = None

        create_result = MagicMock()
        create_result.single.return_value = {
            "canonical_id": "canonical-uuid",
            "canonical_name": "Test",
            "surface_form": None,
            "chunk_count": 0,
            "document_count": 1
        }

        mock_session.run.side_effect = [find_result, create_result]
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_redis.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="Test Concept",
            unified_definition="Test definition"
        )

        # Verify lock was acquired and released
        mock_redis_client.set.assert_called()
        mock_redis_client.delete.assert_called()

    def test_promote_to_published_error_handling(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """promote_to_published should handle errors gracefully."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Database error")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="Test",
            unified_definition="Test",
            deduplicate=False
        )

        assert result == ""


# ============================================
# Test Get Published Concepts
# ============================================

class TestGetPublishedConcepts:
    """Tests for get_published_concepts method."""

    def test_get_published_concepts_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """get_published_concepts should return empty list when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.get_published_concepts(tenant_id="tenant1")

            assert result == []

    def test_get_published_concepts_basic(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_published_concepts should return list of canonical concepts."""
        mock_session = MagicMock()
        mock_records = [
            {
                "canonical_id": "canonical-1",
                "canonical_name": "SAP S/4HANA",
                "concept_type": "Product",
                "unified_definition": "ERP solution",
                "quality_score": 0.95,
                "metadata": {},
                "promoted_at": datetime.utcnow()
            },
            {
                "canonical_id": "canonical-2",
                "canonical_name": "SAP BTP",
                "concept_type": "Platform",
                "unified_definition": "Business Technology Platform",
                "quality_score": 0.88,
                "metadata": {},
                "promoted_at": datetime.utcnow()
            }
        ]
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(mock_records)
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.get_published_concepts(tenant_id="tenant1")

        assert len(result) == 2
        assert result[0]["canonical_name"] == "SAP S/4HANA"
        assert result[0]["quality_score"] == 0.95

    def test_get_published_concepts_with_min_quality_score(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_published_concepts should filter by min_quality_score."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.get_published_concepts(
            tenant_id="tenant1",
            min_quality_score=0.8
        )

        call_args = mock_session.run.call_args
        params = call_args.kwargs if call_args.kwargs else {}
        assert params.get("min_quality_score") == 0.8

    def test_get_published_concepts_with_concept_type(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_published_concepts should filter by concept_type."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.get_published_concepts(
            tenant_id="tenant1",
            concept_type="Product"
        )

        call_args = mock_session.run.call_args
        query = call_args.args[0] if call_args.args else ""
        assert "concept_type" in str(call_args)


# ============================================
# Test Concept Linking
# ============================================

class TestConceptLinking:
    """Tests for create_concept_link method."""

    def test_create_concept_link_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """create_concept_link should return False when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.create_concept_link(
                tenant_id="tenant1",
                source_concept_id="src-uuid",
                target_concept_id="tgt-uuid"
            )

            assert result is False

    def test_create_concept_link_success(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_concept_link should return True on success."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"rel": MagicMock()}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.create_concept_link(
            tenant_id="tenant1",
            source_concept_id="src-uuid",
            target_concept_id="tgt-uuid",
            relationship_type="RELATED_TO",
            weight=0.8
        )

        assert result is True

    def test_create_concept_link_with_metadata(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_concept_link should handle metadata correctly."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"rel": MagicMock()}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        metadata = {"source": "extraction", "confidence": 0.9}

        result = client_with_mock_driver.create_concept_link(
            tenant_id="tenant1",
            source_concept_id="src-uuid",
            target_concept_id="tgt-uuid",
            metadata=metadata
        )

        assert result is True
        call_args = mock_session.run.call_args
        params = call_args.kwargs if call_args.kwargs else call_args[1]
        assert "metadata_source" in params
        assert "metadata_confidence" in params

    def test_create_concept_link_concepts_not_found(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_concept_link should return False if concepts not found."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.create_concept_link(
            tenant_id="tenant1",
            source_concept_id="nonexistent-src",
            target_concept_id="nonexistent-tgt"
        )

        assert result is False

    def test_create_concept_link_custom_relationship_type(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_concept_link should use custom relationship type."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"rel": MagicMock()}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        client_with_mock_driver.create_concept_link(
            tenant_id="tenant1",
            source_concept_id="src-uuid",
            target_concept_id="tgt-uuid",
            relationship_type="DEPENDS_ON"
        )

        call_args = mock_session.run.call_args
        query = call_args.args[0] if call_args.args else ""
        assert "DEPENDS_ON" in query


# ============================================
# Test Tenant Statistics
# ============================================

class TestTenantStats:
    """Tests for get_tenant_stats method."""

    def test_get_tenant_stats_when_not_connected(
        self, mock_driver: MagicMock
    ) -> None:
        """get_tenant_stats should return zeros when not connected."""
        with patch.object(GraphDatabase, "driver") as mock_gdb:
            mock_gdb.side_effect = Exception("Connection failed")
            client = Neo4jClient()

            result = client.get_tenant_stats(tenant_id="tenant1")

            assert result == {
                "proto_count": 0,
                "published_count": 0,
                "links_count": 0
            }

    def test_get_tenant_stats_success(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_tenant_stats should return correct statistics."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "proto_count": 150,
            "published_count": 45,
            "links_count": 120
        }
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.get_tenant_stats(tenant_id="tenant1")

        assert result["proto_count"] == 150
        assert result["published_count"] == 45
        assert result["links_count"] == 120

    def test_get_tenant_stats_empty_result(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_tenant_stats should handle empty result."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.get_tenant_stats(tenant_id="tenant1")

        assert result == {
            "proto_count": 0,
            "published_count": 0,
            "links_count": 0
        }

    def test_get_tenant_stats_error_handling(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """get_tenant_stats should handle errors gracefully."""
        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Query failed")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.get_tenant_stats(tenant_id="tenant1")

        assert result == {
            "proto_count": 0,
            "published_count": 0,
            "links_count": 0
        }


# ============================================
# Test Singleton Pattern
# ============================================

class TestSingletonPattern:
    """Tests for get_neo4j_client singleton function."""

    def test_get_neo4j_client_creates_singleton(
        self, mock_driver: MagicMock
    ) -> None:
        """get_neo4j_client should create and return singleton."""
        with patch.object(GraphDatabase, "driver", return_value=mock_driver):
            with patch("knowbase.common.clients.neo4j_client.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    redis_host="localhost",
                    redis_port=6379
                )
                with patch("redis.Redis") as mock_redis:
                    mock_redis.return_value.ping.side_effect = Exception("No Redis")

                    client1 = get_neo4j_client()
                    client2 = get_neo4j_client()

                    assert client1 is client2


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_tenant_id(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """Methods should handle empty tenant_id."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        # Should not raise
        result = client_with_mock_driver.get_proto_concepts(tenant_id="")
        assert result == []

    def test_special_characters_in_concept_name(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle special characters."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        # Concept name with special characters
        result = client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="SAP S/4HANA® (Cloud Edition)",
            concept_type="Product",
            segment_id="seg1",
            document_id="doc1"
        )

        assert result == "uuid-123"

    def test_unicode_in_concept_name(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle unicode characters."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        # Concept name with unicode
        result = client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="Gestion des données",
            concept_type="Concept",
            segment_id="seg1",
            document_id="doc1"
        )

        assert result == "uuid-123"

    def test_very_long_definition(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """promote_to_published should handle very long definitions."""
        mock_session = MagicMock()

        find_result = MagicMock()
        find_result.single.return_value = None

        create_result = MagicMock()
        create_result.single.return_value = {
            "canonical_id": "canonical-uuid",
            "canonical_name": "Test",
            "surface_form": None,
            "chunk_count": 0,
            "document_count": 1
        }

        mock_session.run.side_effect = [find_result, create_result]
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        long_definition = "x" * 10000  # Very long definition

        result = client_with_mock_driver.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="Test",
            unified_definition=long_definition
        )

        assert result == "canonical-uuid"

    def test_empty_chunk_ids_list(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle empty chunk_ids list."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="Test",
            concept_type="Concept",
            segment_id="seg1",
            document_id="doc1",
            chunk_ids=[]
        )

        assert result == "uuid-123"

    def test_none_metadata(
        self, client_with_mock_driver: Neo4jClient, mock_driver: MagicMock
    ) -> None:
        """create_proto_concept should handle None metadata."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"concept_id": "uuid-123"}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_mock_driver.create_proto_concept(
            tenant_id="tenant1",
            concept_name="Test",
            concept_type="Concept",
            segment_id="seg1",
            document_id="doc1",
            metadata=None
        )

        assert result == "uuid-123"
        call_args = mock_session.run.call_args
        params = call_args.kwargs
        assert params["metadata_json"] == "{}"


# ============================================
# Test Concurrent Access Scenarios
# ============================================

class TestConcurrentAccess:
    """Tests for concurrent access scenarios."""

    def test_lock_contention_scenario(
        self, client_with_redis: Neo4jClient,
        mock_driver: MagicMock,
        mock_redis_client: MagicMock
    ) -> None:
        """Test behavior when lock is already held."""
        mock_session = MagicMock()

        # First call: lock fails (already held)
        mock_redis_client.set.return_value = False

        # After retry/wait, find existing concept
        find_result = MagicMock()
        find_result.single.return_value = {"canonical_id": "existing-id"}
        mock_session.run.return_value = find_result

        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("time.sleep"):
            result = client_with_redis.promote_to_published(
                tenant_id="tenant1",
                proto_concept_id="proto-uuid",
                canonical_name="SAP S/4HANA",
                unified_definition="ERP solution"
            )

        # Should find and return existing concept after lock wait
        assert result == "existing-id"

    def test_lock_released_on_error(
        self, client_with_redis: Neo4jClient,
        mock_driver: MagicMock,
        mock_redis_client: MagicMock
    ) -> None:
        """Lock should be released even on error."""
        mock_session = MagicMock()

        # Lock acquired successfully
        mock_redis_client.set.return_value = True

        # But query fails
        mock_session.run.side_effect = Exception("Database error")
        mock_driver.session.return_value.__enter__ = lambda self: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = client_with_redis.promote_to_published(
            tenant_id="tenant1",
            proto_concept_id="proto-uuid",
            canonical_name="Test",
            unified_definition="Test",
            deduplicate=False
        )

        # Lock should be released
        mock_redis_client.delete.assert_called()
        assert result == ""
