"""Tests Layer 1 — Règles haute précision domain-agnostic."""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
    HygieneRunResult,
    HygieneRunScope,
)
from knowbase.hygiene.rules.layer1_entities import (
    STRUCTURAL_ENTITY_PATTERN,
    DomainStoplistRule,
    InvalidEntityNameRule,
    StructuralEntityRule,
)
from knowbase.hygiene.rules.layer1_axes import (
    ConservativeAxisMergeRule,
    _all_temporal_values,
    _are_keys_similar,
    _normalize_axis_key,
)


# ── Structural Entity Pattern Tests ──────────────────────────────────────

class TestStructuralEntityPattern:
    """Tests pour la regex de détection d'entités structurelles."""

    @pytest.mark.parametrize("name", [
        "Figure 1",
        "Figure 2a",
        "Table 3",
        "Table S1",
        "Appendix A",
        "Appendix B.2",
        "Supplementary Table 1",
        "Supplement S3",
        "Exhibit 4",
        "Annexe A",
        "Tableau 5",
        "Chart 1",
        "Diagram 2",
    ])
    def test_structural_entity_detected(self, name):
        assert STRUCTURAL_ENTITY_PATTERN.match(name) is not None

    @pytest.mark.parametrize("name", [
        "SAP S/4HANA",
        "Machine Learning",
        "Figure skating",       # "skating" is not a number/letter ID
        "Table tennis",         # "tennis" is not a number/letter ID
        "Appendicitis",
        "Supplementary income", # Not "Supplementary Table/Figure X"
        "Clinical Trial Phase 3",
        "FDA Approval",
        "Table of Contents",    # "of" is not a number/letter ID
    ])
    def test_non_structural_entity_not_detected(self, name):
        assert STRUCTURAL_ENTITY_PATTERN.match(name) is None


# ── Structural Entity Rule Tests ─────────────────────────────────────────

class TestStructuralEntityRule:
    """Tests pour la règle de suppression d'entités structurelles."""

    def _make_mock_driver(self, entities):
        """Crée un mock Neo4j driver avec des entités données."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(entities)

        mock_session.run.return_value = mock_result
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        return mock_driver

    def test_scan_detects_structural_entities(self):
        entities = [
            {"entity_id": "e_001", "name": "Figure 1", "normalized_name": "figure 1"},
            {"entity_id": "e_002", "name": "SAP S/4HANA", "normalized_name": "sap s/4hana"},
            {"entity_id": "e_003", "name": "Table 3", "normalized_name": "table 3"},
        ]
        driver = self._make_mock_driver(entities)
        rule = StructuralEntityRule()

        actions = rule.scan(
            neo4j_driver=driver,
            tenant_id="default",
            batch_id="test_batch",
            scope="tenant",
        )

        assert len(actions) == 2
        assert all(a.action_type == HygieneActionType.SUPPRESS_ENTITY for a in actions)
        assert all(a.status == HygieneActionStatus.APPLIED for a in actions)
        assert all(a.confidence == 1.0 for a in actions)

        target_ids = {a.target_node_id for a in actions}
        assert "e_001" in target_ids
        assert "e_003" in target_ids
        assert "e_002" not in target_ids

    def test_scan_empty_returns_no_actions(self):
        driver = self._make_mock_driver([])
        rule = StructuralEntityRule()

        actions = rule.scan(
            neo4j_driver=driver,
            tenant_id="default",
            batch_id="test_batch",
            scope="tenant",
        )

        assert len(actions) == 0


# ── Axis Key Similarity Tests ────────────────────────────────────────────

class TestAxisKeySimilarity:
    """Tests pour la similarité de clés d'axes."""

    def test_normalize_axis_key(self):
        assert _normalize_axis_key("publication_year") == "publication_year"
        assert _normalize_axis_key("Publication-Year") == "publication_year"
        assert _normalize_axis_key("PUBLICATION  YEAR") == "publication_year"

    @pytest.mark.parametrize("key1,key2,expected", [
        ("year", "year", True),
        ("publication_year", "publication_year", True),
        ("year", "publication_year", True),  # prefix
        ("date", "publication_date", True),  # prefix
        ("study_year", "baseline_year", False),  # different semantics
    ])
    def test_are_keys_similar(self, key1, key2, expected):
        assert _are_keys_similar(key1, key2) == expected

    @pytest.mark.parametrize("values,expected", [
        (["2020", "2021", "2022"], True),
        (["2020-01", "2021-02"], True),
        (["2020-01-15", "2021-02-20"], True),
        (["alpha", "beta"], False),
        (["2020", "alpha"], False),
        ([], False),
    ])
    def test_all_temporal_values(self, values, expected):
        assert _all_temporal_values(values) == expected


# ── Conservative Axis Merge Tests ────────────────────────────────────────

class TestConservativeAxisMergeRule:
    """Tests pour la fusion conservatrice d'axes."""

    def _make_mock_driver(self, axes):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(axes)

        mock_session.run.return_value = mock_result
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        return mock_driver

    def test_merges_similar_temporal_axes(self):
        axes = [
            {"axis_id": "ax_1", "axis_key": "year", "values": ["2020", "2021"]},
            {"axis_id": "ax_2", "axis_key": "publication_year", "values": ["2019"]},
        ]
        driver = self._make_mock_driver(axes)
        rule = ConservativeAxisMergeRule()

        actions = rule.scan(
            neo4j_driver=driver,
            tenant_id="default",
            batch_id="test_batch",
            scope="tenant",
        )

        assert len(actions) == 1
        assert actions[0].action_type == HygieneActionType.MERGE_AXIS
        assert actions[0].status == HygieneActionStatus.PROPOSED  # MERGE = toujours PROPOSED

    def test_no_merge_different_semantic_keys(self):
        axes = [
            {"axis_id": "ax_1", "axis_key": "publication_year", "values": ["2020"]},
            {"axis_id": "ax_2", "axis_key": "effective_year", "values": ["2021"]},
        ]
        driver = self._make_mock_driver(axes)
        rule = ConservativeAxisMergeRule()

        actions = rule.scan(
            neo4j_driver=driver,
            tenant_id="default",
            batch_id="test_batch",
            scope="tenant",
        )

        assert len(actions) == 0

    def test_no_merge_non_temporal_values(self):
        axes = [
            {"axis_id": "ax_1", "axis_key": "product", "values": ["SAP", "Oracle"]},
            {"axis_id": "ax_2", "axis_key": "product_name", "values": ["Salesforce"]},
        ]
        driver = self._make_mock_driver(axes)
        rule = ConservativeAxisMergeRule()

        actions = rule.scan(
            neo4j_driver=driver,
            tenant_id="default",
            batch_id="test_batch",
            scope="tenant",
        )

        assert len(actions) == 0


# ── HygieneAction Model Tests ───────────────────────────────────────────

class TestHygieneActionModel:
    """Tests pour le modèle HygieneAction."""

    def test_create_action(self):
        action = HygieneAction(
            action_type=HygieneActionType.SUPPRESS_ENTITY,
            target_node_id="e_001",
            target_node_type="Entity",
            layer=1,
            confidence=1.0,
            reason="Test",
            rule_name="test_rule",
            batch_id="batch_001",
            scope="tenant",
            tenant_id="default",
        )
        assert action.action_id.startswith("hyg_")
        assert action.status == HygieneActionStatus.APPLIED

    def test_to_neo4j_and_back(self):
        action = HygieneAction(
            action_type=HygieneActionType.SUPPRESS_ENTITY,
            target_node_id="e_001",
            target_node_type="Entity",
            layer=1,
            confidence=0.95,
            reason="Test roundtrip",
            rule_name="test_rule",
            batch_id="batch_001",
            scope="tenant",
            status=HygieneActionStatus.PROPOSED,
            before_state={"node": {"name": "Figure 1"}, "relations": []},
            tenant_id="default",
        )

        props = action.to_neo4j_properties()
        restored = HygieneAction.from_neo4j_record(props)

        assert restored.action_id == action.action_id
        assert restored.action_type == action.action_type
        assert restored.confidence == action.confidence
        assert restored.before_state == action.before_state
        assert restored.status == HygieneActionStatus.PROPOSED

    def test_action_type_vs_status_independence(self):
        """action_type et status sont deux dimensions distinctes."""
        action = HygieneAction(
            action_type=HygieneActionType.MERGE_CANONICAL,
            target_node_id="ce_001",
            target_node_type="CanonicalEntity",
            layer=2,
            confidence=0.8,
            reason="Fusion sémantique",
            rule_name="canonical_dedup",
            batch_id="batch_001",
            scope="tenant",
            status=HygieneActionStatus.PROPOSED,
            tenant_id="default",
        )
        assert action.action_type == HygieneActionType.MERGE_CANONICAL
        assert action.status == HygieneActionStatus.PROPOSED

    def test_run_result(self):
        result = HygieneRunResult(batch_id="test")
        assert result.total_actions == 0
        assert result.applied == 0
        assert result.proposed == 0
