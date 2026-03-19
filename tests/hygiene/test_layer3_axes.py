"""Tests Layer 3 — Règles d'hygiène axes avancées (low-value, redundant, misnamed)."""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
)
from knowbase.hygiene.rules.layer3_axes import (
    DISTINCT_TEMPORAL_KEYS,
    LowValueAxisRule,
    MisnamedAxisRule,
    RedundantAxisRule,
    _get_semantic_family,
    _classify_value,
    _values_same_type,
    _is_generic_key,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_mock_driver(query_results_by_call):
    """Crée un mock Neo4j driver avec résultats séquentiels par appel.

    Args:
        query_results_by_call: liste de listes, chaque sous-liste est
            retournée par un appel successif à session.run().
            Si c'est une simple liste de dicts, elle est utilisée pour
            tous les appels.
    """
    mock_driver = MagicMock()
    mock_session = MagicMock()

    if query_results_by_call and isinstance(query_results_by_call[0], list):
        # Multiple calls → side_effect
        results = []
        for call_results in query_results_by_call:
            mock_result = MagicMock()
            mock_result.__iter__ = lambda self, cr=call_results: iter(cr)
            mock_result.single.return_value = (
                call_results[0] if call_results else None
            )
            results.append(mock_result)
        mock_session.run.side_effect = results
    else:
        # Single call → return_value
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(query_results_by_call)
        mock_result.single.return_value = (
            query_results_by_call[0] if query_results_by_call else None
        )
        mock_session.run.return_value = mock_result

    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver.session.return_value = mock_session

    return mock_driver


# ── TestHelperFunctions ─────────────────────────────────────────────────


class TestHelperFunctions:
    """Tests pour les fonctions utilitaires du module layer3_axes."""

    def test_classify_value_year(self):
        assert _classify_value("2020") == "year"

    def test_classify_value_text(self):
        assert _classify_value("abc") == "text"

    def test_classify_value_short_number(self):
        assert _classify_value("20") == "numeric"

    def test_get_family_temporal(self):
        assert _get_semantic_family("publication_year") == "temporal"

    def test_get_family_phase(self):
        assert _get_semantic_family("trial_phase") == "phase"

    def test_get_family_version(self):
        assert _get_semantic_family("release") == "version"

    def test_get_family_unknown(self):
        assert _get_semantic_family("region") is None

    def test_values_same_type_all_years(self):
        assert _values_same_type(["2019", "2020"]) is True

    def test_values_same_type_mixed(self):
        assert _values_same_type(["2019", "abc"]) is False

    def test_values_same_type_all_text(self):
        assert _values_same_type(["alpha", "beta"]) is True

    def test_values_same_type_empty(self):
        assert _values_same_type([]) is False

    def test_is_generic_key(self):
        assert _is_generic_key("date") is True
        assert _is_generic_key("publication_year") is False


# ── TestLowValueAxisRule ────────────────────────────────────────────────


class TestLowValueAxisRule:
    """Tests pour la détection d'axes à faible valeur de navigation."""

    def _run_rule(self, axes, total_axes=None):
        """Helper : patch _load_all_axes et _count_total_axes."""
        if total_axes is None:
            total_axes = len(axes)
        driver = MagicMock()
        rule = LowValueAxisRule()
        with patch("knowbase.hygiene.rules.layer3_axes._load_all_axes", return_value=axes), \
             patch("knowbase.hygiene.rules.layer3_axes._count_total_axes", return_value=total_axes):
            return rule.scan(
                neo4j_driver=driver, tenant_id="default",
                batch_id="test_batch", scope="tenant",
            )

    def test_detects_orphan_axis(self):
        axes = [
            {"axis_id": "ax_orphan", "axis_key": "date", "display_name": "Date",
             "known_values": ["2018"], "doc_count": 1, "source_doc_ids": ["doc1"]},
            {"axis_id": "ax_other", "axis_key": "publication_year", "display_name": "Year",
             "known_values": ["2019", "2020"], "doc_count": 15, "source_doc_ids": ["doc2"]},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 1
        assert actions[0].target_node_id == "ax_orphan"
        assert actions[0].action_type == HygieneActionType.SUPPRESS_AXIS
        assert actions[0].status == HygieneActionStatus.PROPOSED

    def test_preserves_specific_key(self):
        axes = [
            {"axis_id": "ax_specific", "axis_key": "trial_phase", "display_name": "Phase",
             "known_values": ["III"], "doc_count": 1, "source_doc_ids": ["doc1"]},
            {"axis_id": "ax_other", "axis_key": "year", "display_name": "Year",
             "known_values": ["2020"], "doc_count": 10, "source_doc_ids": ["doc2"]},
        ]
        actions = self._run_rule(axes)
        assert all(a.target_node_id != "ax_specific" for a in actions)

    def test_preserves_when_only_axis(self):
        axes = [
            {"axis_id": "ax_solo", "axis_key": "date", "display_name": "Date",
             "known_values": ["2018"], "doc_count": 1, "source_doc_ids": ["doc1"]},
        ]
        actions = self._run_rule(axes, total_axes=1)
        assert len(actions) == 0

    def test_preserves_multi_value(self):
        axes = [
            {"axis_id": "ax_multi", "axis_key": "status", "display_name": "Status",
             "known_values": ["a", "b", "c"], "doc_count": 1, "source_doc_ids": ["doc1"]},
            {"axis_id": "ax_other", "axis_key": "year", "display_name": "Year",
             "known_values": ["2020"], "doc_count": 10, "source_doc_ids": ["doc2"]},
        ]
        actions = self._run_rule(axes)
        assert all(a.target_node_id != "ax_multi" for a in actions)

    def test_reason_contains_low_navigation_value(self):
        axes = [
            {"axis_id": "ax_orphan", "axis_key": "type", "display_name": "Type",
             "known_values": ["report"], "doc_count": 1, "source_doc_ids": ["doc1"]},
            {"axis_id": "ax_other", "axis_key": "year", "display_name": "Year",
             "known_values": ["2020", "2021"], "doc_count": 20, "source_doc_ids": ["doc2"]},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 1
        reason_lower = actions[0].reason.lower()
        assert "navigation" in reason_lower or "low" in reason_lower or "faible" in reason_lower


# ── TestRedundantAxisRule ───────────────────────────────────────────────


class TestRedundantAxisRule:
    """Tests pour la détection d'axes redondants dans les familles sémantiques."""

    def _run_rule(self, axes):
        driver = MagicMock()
        rule = RedundantAxisRule()
        with patch("knowbase.hygiene.rules.layer3_axes._load_all_axes", return_value=axes):
            return rule.scan(
                neo4j_driver=driver, tenant_id="default",
                batch_id="test_batch", scope="tenant",
            )

    def test_detects_doc_year_redundant_with_publication_year(self):
        axes = [
            {"axis_id": "ax_small", "axis_key": "doc_year", "display_name": "Doc Year",
             "known_values": ["2018"], "doc_count": 1, "source_doc_ids": ["doc1"]},
            {"axis_id": "ax_large", "axis_key": "publication_year", "display_name": "Year",
             "known_values": ["2018", "2019", "2020", "2021"], "doc_count": 22, "source_doc_ids": ["doc1", "doc2"]},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 1
        assert actions[0].action_type == HygieneActionType.MERGE_AXIS
        assert actions[0].status == HygieneActionStatus.PROPOSED

    def test_no_merge_distinct_temporal_keys(self):
        axes = [
            {"axis_id": "ax_pub", "axis_key": "publication_year", "display_name": "Year",
             "known_values": ["2019", "2020"], "doc_count": 5, "source_doc_ids": []},
            {"axis_id": "ax_eff", "axis_key": "effective_year", "display_name": "Year",
             "known_values": ["2021"], "doc_count": 1, "source_doc_ids": []},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 0

    def test_no_merge_different_value_types(self):
        axes = [
            {"axis_id": "ax_years", "axis_key": "year", "display_name": "Year",
             "known_values": ["2019", "2020"], "doc_count": 10, "source_doc_ids": []},
            {"axis_id": "ax_dates", "axis_key": "date", "display_name": "Date",
             "known_values": ["January", "February"], "doc_count": 3, "source_doc_ids": []},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 0

    def test_no_merge_similar_doc_count(self):
        axes = [
            {"axis_id": "ax_1", "axis_key": "year", "display_name": "Year",
             "known_values": ["2020", "2021"], "doc_count": 10, "source_doc_ids": []},
            {"axis_id": "ax_2", "axis_key": "date", "display_name": "Date",
             "known_values": ["2020", "2021"], "doc_count": 5, "source_doc_ids": []},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 0

    def test_merge_target_is_larger_axis(self):
        axes = [
            {"axis_id": "ax_small", "axis_key": "year", "display_name": "Year",
             "known_values": ["2020"], "doc_count": 2, "source_doc_ids": ["doc1"]},
            {"axis_id": "ax_large", "axis_key": "temporal", "display_name": "Temporal",
             "known_values": ["2020", "2021"], "doc_count": 30, "source_doc_ids": ["doc1", "doc2"]},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 1
        assert actions[0].target_node_id == "ax_small"
        assert actions[0].after_state.get("merge_target_id") == "ax_large"

    def test_no_merge_cross_family(self):
        axes = [
            {"axis_id": "ax_ver", "axis_key": "version", "display_name": "Version",
             "known_values": ["1.0", "2.0"], "doc_count": 15, "source_doc_ids": []},
            {"axis_id": "ax_year", "axis_key": "year", "display_name": "Year",
             "known_values": ["2020"], "doc_count": 2, "source_doc_ids": []},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 0


# ── TestMisnamedAxisRule ────────────────────────────────────────────────


class TestMisnamedAxisRule:
    """Tests pour la détection d'axes mal nommés (pré-filtre + LLM)."""

    def _run_rule(self, axes, llm_response=None):
        driver = MagicMock()
        rule = MisnamedAxisRule()
        # Mock LLM pour retourner "incoherent" par défaut
        if llm_response is None:
            llm_response = '```json\n[{"axis_key": "test", "is_incoherent": true, "confidence": 0.8, "reason": "test"}]\n```'

        with patch("knowbase.hygiene.rules.layer3_axes._load_all_axes", return_value=axes), \
             patch("knowbase.hygiene.rules.layer3_axes._load_domain_summary", return_value="general"), \
             patch("knowbase.hygiene.rules.layer3_axes._call_llm", return_value=llm_response):
            return rule.scan(
                neo4j_driver=driver, tenant_id="default",
                batch_id="test_batch", scope="tenant",
            )

    def test_prefilter_detects_display_name_as_value(self):
        axes = [
            {"axis_id": "ax_misnamed", "axis_key": "date", "display_name": "19 Feb 2022",
             "known_values": ["yes", "no"], "doc_count": 3, "source_doc_ids": []},
        ]
        llm = '```json\n[{"axis_key": "date", "is_incoherent": true, "confidence": 0.9, "reason": "display_name is a value"}]\n```'
        actions = self._run_rule(axes, llm_response=llm)
        assert len(actions) >= 1
        assert actions[0].target_node_id == "ax_misnamed"
        assert actions[0].action_type == HygieneActionType.SUPPRESS_AXIS
        assert actions[0].status == HygieneActionStatus.PROPOSED

    def test_prefilter_skips_clean_axis(self):
        axes = [
            {"axis_id": "ax_clean", "axis_key": "publication_year", "display_name": "Publication Year",
             "known_values": ["2019", "2020", "2021"], "doc_count": 15, "source_doc_ids": []},
        ]
        actions = self._run_rule(axes)
        assert len(actions) == 0

    def test_heterogeneous_values_trigger_prefilter(self):
        axes = [
            {"axis_id": "ax_hetero", "axis_key": "category", "display_name": "Category",
             "known_values": ["2019", "Clinical Trial"], "doc_count": 5, "source_doc_ids": []},
        ]
        llm = '```json\n[{"axis_key": "category", "is_incoherent": true, "confidence": 0.8, "reason": "mixed types"}]\n```'
        actions = self._run_rule(axes, llm_response=llm)
        assert len(actions) >= 1
        assert actions[0].target_node_id == "ax_hetero"
