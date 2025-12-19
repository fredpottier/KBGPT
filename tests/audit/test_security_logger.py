"""Unit tests for security_logger module.

This module contains tests for the security audit logging functionality.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Generator
from unittest.mock import patch, MagicMock

import pytest

# Mock redis module to avoid import errors
sys.modules['redis'] = MagicMock()

from knowbase.audit.security_logger import log_security_event


class TestLogSecurityEvent:
    """Tests for the log_security_event function."""

    @pytest.fixture
    def mock_logger(self) -> Generator[MagicMock, None, None]:
        """Mock the security audit logger."""
        with patch("knowbase.audit.security_logger.logger") as mock:
            yield mock

    def test_log_basic_event(self, mock_logger: MagicMock) -> None:
        """Test logging a basic security event."""
        log_security_event(
            event_type="merge",
            action="canonicalization.merge",
        )

        mock_logger.info.assert_called_once()
        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["event_type"] == "merge"
        assert event["action"] == "canonicalization.merge"
        assert event["status"] == "success"
        assert event["user_id"] == "anonymous"

    def test_log_event_with_user(self, mock_logger: MagicMock) -> None:
        """Test logging event with user ID."""
        log_security_event(
            event_type="undo",
            action="canonicalization.undo",
            user_id="admin@example.com",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["user_id"] == "admin@example.com"

    def test_log_event_with_resource(self, mock_logger: MagicMock) -> None:
        """Test logging event with resource ID."""
        log_security_event(
            event_type="delete",
            action="entity.delete",
            resource_id="entity_123",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["resource_id"] == "entity_123"

    def test_log_event_with_status(self, mock_logger: MagicMock) -> None:
        """Test logging event with custom status."""
        log_security_event(
            event_type="access_denied",
            action="admin.panel.access",
            status="denied",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["status"] == "denied"

    def test_log_event_with_metadata(self, mock_logger: MagicMock) -> None:
        """Test logging event with metadata."""
        metadata = {
            "candidates": ["cand_1", "cand_2"],
            "confidence": 0.95,
        }
        log_security_event(
            event_type="merge",
            action="canonicalization.merge",
            metadata=metadata,
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["metadata"] == metadata
        assert event["metadata"]["candidates"] == ["cand_1", "cand_2"]
        assert event["metadata"]["confidence"] == 0.95

    def test_log_event_with_ip_address(self, mock_logger: MagicMock) -> None:
        """Test logging event with IP address."""
        log_security_event(
            event_type="login",
            action="auth.login",
            ip_address="192.168.1.100",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["ip_address"] == "192.168.1.100"

    def test_log_event_timestamp_format(self, mock_logger: MagicMock) -> None:
        """Test that timestamp is in ISO format."""
        log_security_event(
            event_type="test",
            action="test.action",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        # Should be parseable as ISO datetime
        timestamp = datetime.fromisoformat(event["timestamp"])
        assert isinstance(timestamp, datetime)

    def test_log_event_full_example(self, mock_logger: MagicMock) -> None:
        """Test logging a complete security event with all fields."""
        log_security_event(
            event_type="bootstrap",
            action="ontology.bootstrap",
            user_id="system@osmose.ai",
            resource_id="ontology_v2",
            status="success",
            metadata={
                "types_added": 15,
                "source": "yaml_config",
            },
            ip_address="10.0.0.1",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["event_type"] == "bootstrap"
        assert event["action"] == "ontology.bootstrap"
        assert event["user_id"] == "system@osmose.ai"
        assert event["resource_id"] == "ontology_v2"
        assert event["status"] == "success"
        assert event["ip_address"] == "10.0.0.1"
        assert event["metadata"]["types_added"] == 15

    def test_log_event_empty_metadata(self, mock_logger: MagicMock) -> None:
        """Test that empty metadata defaults to empty dict."""
        log_security_event(
            event_type="test",
            action="test.action",
            metadata=None,
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)

        assert event["metadata"] == {}

    def test_log_event_different_types(self, mock_logger: MagicMock) -> None:
        """Test logging various event types."""
        event_types = [
            ("merge", "canonicalization.merge"),
            ("undo", "canonicalization.undo"),
            ("bootstrap", "ontology.bootstrap"),
            ("access_denied", "admin.unauthorized"),
            ("rate_limit", "api.rate_exceeded"),
            ("lock_timeout", "concurrent.lock_failed"),
        ]

        for event_type, action in event_types:
            log_security_event(event_type=event_type, action=action)

            logged_json = mock_logger.info.call_args[0][0]
            event = json.loads(logged_json)

            assert event["event_type"] == event_type
            assert event["action"] == action


class TestLogSecurityEventStatuses:
    """Tests for different status values in security events."""

    @pytest.fixture
    def mock_logger(self) -> Generator[MagicMock, None, None]:
        """Mock the security audit logger."""
        with patch("knowbase.audit.security_logger.logger") as mock:
            yield mock

    def test_status_success(self, mock_logger: MagicMock) -> None:
        """Test success status."""
        log_security_event(
            event_type="operation",
            action="some.operation",
            status="success",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["status"] == "success"

    def test_status_failed(self, mock_logger: MagicMock) -> None:
        """Test failed status."""
        log_security_event(
            event_type="operation",
            action="some.operation",
            status="failed",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["status"] == "failed"

    def test_status_denied(self, mock_logger: MagicMock) -> None:
        """Test denied status."""
        log_security_event(
            event_type="access",
            action="resource.access",
            status="denied",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["status"] == "denied"


class TestLogSecurityEventEdgeCases:
    """Edge case tests for security event logging."""

    @pytest.fixture
    def mock_logger(self) -> Generator[MagicMock, None, None]:
        """Mock the security audit logger."""
        with patch("knowbase.audit.security_logger.logger") as mock:
            yield mock

    def test_unicode_in_metadata(self, mock_logger: MagicMock) -> None:
        """Test handling unicode characters in metadata."""
        log_security_event(
            event_type="test",
            action="test.unicode",
            metadata={"message": "Café résumé 日本語"},
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["metadata"]["message"] == "Café résumé 日本語"

    def test_special_characters_in_action(self, mock_logger: MagicMock) -> None:
        """Test handling special characters in action."""
        log_security_event(
            event_type="test",
            action="namespace/sub-action.v2_final",
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["action"] == "namespace/sub-action.v2_final"

    def test_nested_metadata(self, mock_logger: MagicMock) -> None:
        """Test handling nested metadata structures."""
        log_security_event(
            event_type="complex",
            action="complex.action",
            metadata={
                "level1": {
                    "level2": {
                        "value": [1, 2, 3],
                    },
                },
                "list": ["a", "b", "c"],
            },
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["metadata"]["level1"]["level2"]["value"] == [1, 2, 3]
        assert event["metadata"]["list"] == ["a", "b", "c"]

    def test_long_resource_id(self, mock_logger: MagicMock) -> None:
        """Test handling long resource IDs."""
        long_id = "x" * 500
        log_security_event(
            event_type="test",
            action="test.long_id",
            resource_id=long_id,
        )

        logged_json = mock_logger.info.call_args[0][0]
        event = json.loads(logged_json)
        assert event["resource_id"] == long_id
        assert len(event["resource_id"]) == 500
