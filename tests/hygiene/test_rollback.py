"""Tests rollback — best-effort borné."""

import pytest
from unittest.mock import MagicMock, call, patch

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
)
from knowbase.hygiene.rollback import HygieneRollback, RollbackResult, _guess_id_field


class TestGuessIdField:
    """Tests pour _guess_id_field."""

    @pytest.mark.parametrize("label,expected", [
        ("Entity", "entity_id"),
        ("CanonicalEntity", "canonical_entity_id"),
        ("ApplicabilityAxis", "axis_id"),
        ("Claim", "claim_id"),
        ("Facet", "facet_id"),
        ("WikiArticle", "slug"),
        ("UnknownLabel", "entity_id"),  # fallback
    ])
    def test_guess_id_field(self, label, expected):
        assert _guess_id_field(label) == expected


class TestRollbackResult:
    """Tests pour RollbackResult."""

    def test_default_values(self):
        result = RollbackResult()
        assert result.success is False
        assert result.relations_restored == 0
        assert result.partial is False

    def test_to_dict(self):
        result = RollbackResult()
        result.success = True
        result.relations_restored = 5
        result.relations_failed = 1
        result.partial = True
        result.failed_reasons = ["Voisin supprimé"]

        d = result.to_dict()
        assert d["success"] is True
        assert d["relations_restored"] == 5
        assert d["relations_failed"] == 1
        assert d["partial"] is True


class TestHygieneRollback:
    """Tests pour le rollback des actions d'hygiène."""

    def _make_action(self, **overrides):
        defaults = {
            "action_id": "hyg_test123",
            "action_type": HygieneActionType.SUPPRESS_ENTITY,
            "target_node_id": "e_001",
            "target_node_type": "Entity",
            "layer": 1,
            "confidence": 1.0,
            "reason": "Test",
            "rule_name": "test_rule",
            "batch_id": "batch_001",
            "scope": "tenant",
            "status": HygieneActionStatus.APPLIED,
            "tenant_id": "default",
            "before_state": {"node": {"entity_id": "e_001", "name": "Figure 1"}, "relations": []},
        }
        defaults.update(overrides)
        return HygieneAction(**defaults)

    @patch("knowbase.hygiene.rollback.HygieneActionPersister")
    def test_rollback_suppress_success(self, mock_persister_cls):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"found": True}
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        action = self._make_action()
        mock_persister = mock_persister_cls.return_value
        mock_persister.get_action.return_value = action
        mock_persister.update_status.return_value = True

        rollback = HygieneRollback(mock_driver)
        result = rollback.rollback_action("hyg_test123")

        assert result.success is True
        assert result.partial is False

    @patch("knowbase.hygiene.rollback.HygieneActionPersister")
    def test_rollback_not_applied_fails(self, mock_persister_cls):
        mock_driver = MagicMock()
        action = self._make_action(status=HygieneActionStatus.PROPOSED)
        mock_persister = mock_persister_cls.return_value
        mock_persister.get_action.return_value = action

        rollback = HygieneRollback(mock_driver)
        result = rollback.rollback_action("hyg_test123")

        assert result.success is False
        assert len(result.failed_reasons) > 0

    @patch("knowbase.hygiene.rollback.HygieneActionPersister")
    def test_rollback_not_found_fails(self, mock_persister_cls):
        mock_driver = MagicMock()
        mock_persister = mock_persister_cls.return_value
        mock_persister.get_action.return_value = None

        rollback = HygieneRollback(mock_driver)
        result = rollback.rollback_action("hyg_nonexistent")

        assert result.success is False
        assert "introuvable" in result.failed_reasons[0]

    @patch("knowbase.hygiene.rollback.HygieneActionPersister")
    def test_rollback_hard_delete_partial(self, mock_persister_cls):
        """Rollback HARD_DELETE avec relations partiellement restaurables."""
        mock_driver = MagicMock()
        mock_session = MagicMock()

        # Simulate: first call creates node, second call checks neighbor (exists),
        # third call checks neighbor (doesn't exist)
        call_count = {"n": 0}

        def mock_run(query, **kwargs):
            call_count["n"] += 1
            r = MagicMock()
            if "CREATE" in query:
                r.single.return_value = {"found": True}
            elif "RETURN other IS NOT NULL" in query:
                # First neighbor exists, second doesn't
                if "claim_001" in str(kwargs.get("other_id", "")):
                    r.single.return_value = {"exists": True}
                else:
                    r.single.return_value = {"exists": False}
            else:
                r.single.return_value = {"found": True}
            return r

        mock_session.run = mock_run
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        action = self._make_action(
            action_type=HygieneActionType.HARD_DELETE_ENTITY,
            before_state={
                "node": {"entity_id": "e_001", "name": "Old Entity"},
                "relations": [
                    {
                        "type": "ABOUT",
                        "direction": "incoming",
                        "other_id": "claim_001",
                        "other_label": "Claim",
                        "props": {},
                    },
                    {
                        "type": "ABOUT",
                        "direction": "incoming",
                        "other_id": "claim_deleted",
                        "other_label": "Claim",
                        "props": {},
                    },
                ],
            },
        )

        mock_persister = mock_persister_cls.return_value
        mock_persister.get_action.return_value = action
        mock_persister.update_status.return_value = True

        rollback = HygieneRollback(mock_driver)
        result = rollback.rollback_action("hyg_test123")

        assert result.success is True
        assert result.partial is True
        assert result.relations_restored == 1
        assert result.relations_failed == 1
