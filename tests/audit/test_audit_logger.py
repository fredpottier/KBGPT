"""Unit tests for AuditLogger.

This module contains comprehensive tests for the audit logging system,
covering merge operations, undo functionality, and quarantine management.
"""

import json
import sys
from datetime import datetime, timedelta
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# Mock redis module before importing audit_logger
mock_redis = MagicMock()
sys.modules['redis'] = mock_redis

from knowbase.audit.audit_logger import AuditLogger, MergeAuditEntry


class TestMergeAuditEntry:
    """Tests for the MergeAuditEntry dataclass."""

    def test_create_minimal_entry(self) -> None:
        """Test creating a MergeAuditEntry with minimal fields."""
        entry = MergeAuditEntry(
            merge_id="merge_abc123",
            canonical_entity_id="entity_001",
            candidate_ids=["cand_1", "cand_2"],
            user_id="user@example.com",
            executed_at="2025-12-02T10:00:00",
            operation="merge",
        )

        assert entry.merge_id == "merge_abc123"
        assert entry.canonical_entity_id == "entity_001"
        assert entry.candidate_ids == ["cand_1", "cand_2"]
        assert entry.user_id == "user@example.com"
        assert entry.operation == "merge"
        assert entry.reason is None
        assert entry.merge_status == "quarantine"

    def test_create_full_entry(self) -> None:
        """Test creating a MergeAuditEntry with all fields."""
        version_meta = {"version": 1, "schema": "v2"}
        entry = MergeAuditEntry(
            merge_id="merge_def456",
            canonical_entity_id="entity_002",
            candidate_ids=["cand_3", "cand_4", "cand_5"],
            user_id="admin@example.com",
            executed_at="2025-12-02T11:00:00",
            operation="undo_merge",
            reason="Incorrect merge",
            idempotency_key="idem_xyz",
            version_metadata=version_meta,
            merge_status="approved",
            quarantine_until="2025-12-03T11:00:00",
        )

        assert entry.merge_id == "merge_def456"
        assert entry.reason == "Incorrect merge"
        assert entry.idempotency_key == "idem_xyz"
        assert entry.version_metadata == version_meta
        assert entry.merge_status == "approved"
        assert entry.quarantine_until == "2025-12-03T11:00:00"

    def test_to_dict(self) -> None:
        """Test converting entry to dictionary."""
        entry = MergeAuditEntry(
            merge_id="merge_test",
            canonical_entity_id="entity_test",
            candidate_ids=["c1", "c2"],
            user_id="test_user",
            executed_at="2025-12-02T12:00:00",
            operation="merge",
        )

        result = entry.to_dict()

        assert isinstance(result, dict)
        assert result["merge_id"] == "merge_test"
        assert result["canonical_entity_id"] == "entity_test"
        assert result["candidate_ids"] == ["c1", "c2"]
        assert result["operation"] == "merge"

    def test_from_dict(self) -> None:
        """Test creating entry from dictionary."""
        data = {
            "merge_id": "merge_from_dict",
            "canonical_entity_id": "entity_dict",
            "candidate_ids": ["d1", "d2"],
            "user_id": "dict_user",
            "executed_at": "2025-12-02T13:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }

        entry = MergeAuditEntry.from_dict(data)

        assert entry.merge_id == "merge_from_dict"
        assert entry.canonical_entity_id == "entity_dict"
        assert entry.candidate_ids == ["d1", "d2"]

    def test_roundtrip_dict_conversion(self) -> None:
        """Test that to_dict and from_dict are inverse operations."""
        original = MergeAuditEntry(
            merge_id="merge_roundtrip",
            canonical_entity_id="entity_rt",
            candidate_ids=["rt1", "rt2", "rt3"],
            user_id="rt_user",
            executed_at="2025-12-02T14:00:00",
            operation="merge",
            reason="Test reason",
            idempotency_key="idem_rt",
            version_metadata={"key": "value"},
            merge_status="approved",
            quarantine_until="2025-12-03T14:00:00",
        )

        reconstructed = MergeAuditEntry.from_dict(original.to_dict())

        assert reconstructed.merge_id == original.merge_id
        assert reconstructed.canonical_entity_id == original.canonical_entity_id
        assert reconstructed.candidate_ids == original.candidate_ids
        assert reconstructed.reason == original.reason
        assert reconstructed.version_metadata == original.version_metadata


class TestAuditLoggerGenerateMergeId:
    """Tests for merge ID generation."""

    @pytest.fixture
    def audit_logger(self) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis = MagicMock()
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_generate_merge_id_format(self, audit_logger: AuditLogger) -> None:
        """Test that generated merge ID has correct format."""
        merge_id = audit_logger.generate_merge_id(
            "entity_001",
            "2025-12-02T10:00:00"
        )

        assert merge_id.startswith("merge_")
        assert len(merge_id) == len("merge_") + 16  # prefix + 16 char hash

    def test_generate_merge_id_deterministic(self, audit_logger: AuditLogger) -> None:
        """Test that same inputs produce same merge ID."""
        merge_id_1 = audit_logger.generate_merge_id(
            "entity_001",
            "2025-12-02T10:00:00"
        )
        merge_id_2 = audit_logger.generate_merge_id(
            "entity_001",
            "2025-12-02T10:00:00"
        )

        assert merge_id_1 == merge_id_2

    def test_generate_merge_id_different_inputs(
        self, audit_logger: AuditLogger
    ) -> None:
        """Test that different inputs produce different merge IDs."""
        merge_id_1 = audit_logger.generate_merge_id(
            "entity_001",
            "2025-12-02T10:00:00"
        )
        merge_id_2 = audit_logger.generate_merge_id(
            "entity_002",
            "2025-12-02T10:00:00"
        )
        merge_id_3 = audit_logger.generate_merge_id(
            "entity_001",
            "2025-12-02T11:00:00"
        )

        assert merge_id_1 != merge_id_2
        assert merge_id_1 != merge_id_3
        assert merge_id_2 != merge_id_3


class TestAuditLoggerLogMerge:
    """Tests for logging merge operations."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_log_merge_basic(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test basic merge logging."""
        merge_id = audit_logger.log_merge(
            canonical_entity_id="entity_001",
            candidate_ids=["cand_1", "cand_2"],
            user_id="user@example.com",
        )

        assert merge_id.startswith("merge_")
        mock_redis.setex.assert_called_once()

        call_args = mock_redis.setex.call_args
        assert call_args[0][0].startswith("audit:merge:")
        assert call_args[0][1] == 30 * 24 * 60 * 60  # 30 days TTL

    def test_log_merge_with_idempotency_key(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test merge logging with idempotency key."""
        audit_logger.log_merge(
            canonical_entity_id="entity_001",
            candidate_ids=["cand_1"],
            user_id="user@example.com",
            idempotency_key="idem_123",
        )

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["idempotency_key"] == "idem_123"

    def test_log_merge_with_version_metadata(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test merge logging with version metadata."""
        version_meta = {"version": 2, "schema": "v3"}
        audit_logger.log_merge(
            canonical_entity_id="entity_001",
            candidate_ids=["cand_1"],
            user_id="user@example.com",
            version_metadata=version_meta,
        )

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["version_metadata"] == version_meta

    def test_log_merge_sets_quarantine_status(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that merge is logged with quarantine status."""
        audit_logger.log_merge(
            canonical_entity_id="entity_001",
            candidate_ids=["cand_1"],
            user_id="user@example.com",
        )

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["merge_status"] == "quarantine"
        assert stored_data["quarantine_until"] is not None

    def test_log_merge_redis_error_returns_merge_id(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that merge ID is returned even if Redis fails."""
        mock_redis.setex.side_effect = Exception("Redis connection error")

        merge_id = audit_logger.log_merge(
            canonical_entity_id="entity_001",
            candidate_ids=["cand_1"],
            user_id="user@example.com",
        )

        # Should still return a merge ID even if storage fails
        assert merge_id.startswith("merge_")


class TestAuditLoggerLogUndo:
    """Tests for logging undo operations."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_log_undo_with_existing_merge(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test logging undo when original merge exists."""
        original_entry = MergeAuditEntry(
            merge_id="merge_original",
            canonical_entity_id="entity_001",
            candidate_ids=["c1", "c2"],
            user_id="original_user",
            executed_at="2025-12-01T10:00:00",
            operation="merge",
        )
        mock_redis.get.return_value = json.dumps(original_entry.to_dict())

        undo_id = audit_logger.log_undo(
            merge_id="merge_original",
            reason="User requested undo",
            user_id="undo_user@example.com",
        )

        assert undo_id.startswith("undo_merge_original_")
        mock_redis.setex.assert_called_once()

    def test_log_undo_without_existing_merge(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test logging undo when original merge not found."""
        mock_redis.get.return_value = None

        undo_id = audit_logger.log_undo(
            merge_id="merge_nonexistent",
            reason="Test undo",
            user_id="user@example.com",
        )

        # Should still create undo entry
        assert undo_id.startswith("undo_")

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["canonical_entity_id"] == "unknown"
        assert stored_data["candidate_ids"] == []

    def test_log_undo_stores_reason(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that undo reason is stored."""
        mock_redis.get.return_value = None

        audit_logger.log_undo(
            merge_id="merge_test",
            reason="Incorrect canonicalization",
            user_id="user@example.com",
        )

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["reason"] == "Incorrect canonicalization"
        assert stored_data["operation"] == "undo_merge"


class TestAuditLoggerGetMergeEntry:
    """Tests for retrieving merge entries."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_get_merge_entry_found(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test getting an existing merge entry."""
        entry_data = {
            "merge_id": "merge_found",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1", "c2"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-02T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": "2025-12-03T10:00:00",
        }
        mock_redis.get.return_value = json.dumps(entry_data)

        result = audit_logger.get_merge_entry("merge_found")

        assert result is not None
        assert result.merge_id == "merge_found"
        assert result.canonical_entity_id == "entity_001"
        mock_redis.get.assert_called_with("audit:merge:merge_found")

    def test_get_merge_entry_not_found(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test getting a non-existent merge entry."""
        mock_redis.get.return_value = None

        result = audit_logger.get_merge_entry("merge_nonexistent")

        assert result is None

    def test_get_merge_entry_redis_error(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test handling Redis error when getting entry."""
        mock_redis.get.side_effect = Exception("Redis error")

        result = audit_logger.get_merge_entry("merge_error")

        assert result is None


class TestAuditLoggerIsUndoAllowed:
    """Tests for undo permission checking."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_is_undo_allowed_recent_merge(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that undo is allowed for recent merge."""
        recent_timestamp = (datetime.utcnow() - timedelta(days=1)).isoformat()
        entry_data = {
            "merge_id": "merge_recent",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": recent_timestamp,
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }
        mock_redis.get.return_value = json.dumps(entry_data)

        allowed, reason = audit_logger.is_undo_allowed("merge_recent")

        assert allowed is True
        assert reason is None

    def test_is_undo_allowed_old_merge(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that undo is not allowed for old merge."""
        old_timestamp = (datetime.utcnow() - timedelta(days=10)).isoformat()
        entry_data = {
            "merge_id": "merge_old",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": old_timestamp,
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }
        mock_redis.get.return_value = json.dumps(entry_data)

        allowed, reason = audit_logger.is_undo_allowed("merge_old")

        assert allowed is False
        assert "trop ancien" in reason

    def test_is_undo_allowed_not_found(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that undo is not allowed for non-existent merge."""
        mock_redis.get.return_value = None

        allowed, reason = audit_logger.is_undo_allowed("merge_nonexistent")

        assert allowed is False
        assert "introuvable" in reason

    def test_is_undo_allowed_custom_max_age(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test undo allowed check with custom max age."""
        timestamp = (datetime.utcnow() - timedelta(days=5)).isoformat()
        entry_data = {
            "merge_id": "merge_custom",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": timestamp,
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }
        mock_redis.get.return_value = json.dumps(entry_data)

        # With default max_age=7, should be allowed
        allowed, _ = audit_logger.is_undo_allowed("merge_custom")
        assert allowed is True

        # With max_age=3, should not be allowed
        allowed, reason = audit_logger.is_undo_allowed("merge_custom", max_age_days=3)
        assert allowed is False


class TestAuditLoggerGetMergeHistory:
    """Tests for retrieving merge history."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_get_merge_history_empty(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test getting history when no merges exist."""
        mock_redis.scan_iter.return_value = iter([])

        result = audit_logger.get_merge_history("entity_001")

        assert result == []

    def test_get_merge_history_with_entries(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test getting history with matching entries."""
        entry1 = {
            "merge_id": "merge_1",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-02T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }
        entry2 = {
            "merge_id": "merge_2",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c2"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-02T11:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "approved",
            "quarantine_until": None,
        }

        mock_redis.scan_iter.return_value = iter([
            "audit:merge:merge_1",
            "audit:merge:merge_2",
        ])
        mock_redis.get.side_effect = [
            json.dumps(entry1),
            json.dumps(entry2),
        ]

        result = audit_logger.get_merge_history("entity_001")

        assert len(result) == 2
        # Should be sorted by date desc
        assert result[0].merge_id == "merge_2"
        assert result[1].merge_id == "merge_1"

    def test_get_merge_history_limit(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that history respects limit parameter."""
        entries = []
        for i in range(15):
            entries.append({
                "merge_id": f"merge_{i}",
                "canonical_entity_id": "entity_001",
                "candidate_ids": [f"c{i}"],
                "user_id": "user@example.com",
                "executed_at": f"2025-12-0{(i % 9) + 1}T10:00:00",
                "operation": "merge",
                "reason": None,
                "idempotency_key": None,
                "version_metadata": None,
                "merge_status": "quarantine",
                "quarantine_until": None,
            })

        mock_redis.scan_iter.return_value = iter([
            f"audit:merge:merge_{i}" for i in range(15)
        ])
        mock_redis.get.side_effect = [json.dumps(e) for e in entries]

        result = audit_logger.get_merge_history("entity_001", limit=5)

        assert len(result) == 5


class TestAuditLoggerUpdateMergeStatus:
    """Tests for updating merge status."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_update_merge_status_success(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test successful status update."""
        entry_data = {
            "merge_id": "merge_update",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-02T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }
        mock_redis.get.return_value = json.dumps(entry_data)

        result = audit_logger.update_merge_status("merge_update", "approved")

        assert result is True
        mock_redis.setex.assert_called_once()

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["merge_status"] == "approved"

    def test_update_merge_status_not_found(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test status update for non-existent merge."""
        mock_redis.get.return_value = None

        result = audit_logger.update_merge_status("merge_nonexistent", "approved")

        assert result is False

    def test_update_merge_status_redis_error(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test handling Redis error during update."""
        entry_data = {
            "merge_id": "merge_error",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-02T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": None,
        }
        mock_redis.get.return_value = json.dumps(entry_data)
        mock_redis.setex.side_effect = Exception("Redis error")

        result = audit_logger.update_merge_status("merge_error", "approved")

        assert result is False


class TestAuditLoggerGetQuarantineReadyMerges:
    """Tests for retrieving quarantine-ready merges."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_redis: MagicMock) -> AuditLogger:
        """Create AuditLogger with mocked Redis."""
        with patch("knowbase.audit.audit_logger.redis.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = mock_redis
            logger = AuditLogger(redis_url="redis://localhost:6379/3")
            return logger

    def test_get_quarantine_ready_merges_empty(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test when no merges are ready."""
        mock_redis.scan_iter.return_value = iter([])

        result = audit_logger.get_quarantine_ready_merges()

        assert result == []

    def test_get_quarantine_ready_merges_with_ready_entries(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test finding merges ready to exit quarantine."""
        past_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        future_time = (datetime.utcnow() + timedelta(hours=2)).isoformat()

        entry_ready = {
            "merge_id": "merge_ready",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-01T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": past_time,
        }
        entry_not_ready = {
            "merge_id": "merge_not_ready",
            "canonical_entity_id": "entity_002",
            "candidate_ids": ["c2"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-02T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "quarantine",
            "quarantine_until": future_time,
        }

        mock_redis.scan_iter.return_value = iter([
            "audit:merge:merge_ready",
            "audit:merge:merge_not_ready",
        ])
        mock_redis.get.side_effect = [
            json.dumps(entry_ready),
            json.dumps(entry_not_ready),
        ]

        result = audit_logger.get_quarantine_ready_merges()

        assert len(result) == 1
        assert result[0].merge_id == "merge_ready"

    def test_get_quarantine_ready_excludes_approved(
        self, audit_logger: AuditLogger, mock_redis: MagicMock
    ) -> None:
        """Test that already approved merges are excluded."""
        past_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()

        entry_approved = {
            "merge_id": "merge_approved",
            "canonical_entity_id": "entity_001",
            "candidate_ids": ["c1"],
            "user_id": "user@example.com",
            "executed_at": "2025-12-01T10:00:00",
            "operation": "merge",
            "reason": None,
            "idempotency_key": None,
            "version_metadata": None,
            "merge_status": "approved",  # Already approved
            "quarantine_until": past_time,
        }

        mock_redis.scan_iter.return_value = iter(["audit:merge:merge_approved"])
        mock_redis.get.return_value = json.dumps(entry_approved)

        result = audit_logger.get_quarantine_ready_merges()

        assert len(result) == 0
