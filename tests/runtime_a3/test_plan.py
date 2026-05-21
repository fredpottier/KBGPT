"""Tests unitaires du module Plan — runtime_a3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.2 + §4.

Stratégie :
    - Pas de mock — le Planner est 100% déterministe (aucun LLM, aucune I/O)
    - Couvrir : mapping kind→tool exhaustif, paramètres Cypher, unmappable, fallback Qdrant
    - Vérifier domain-agnostic : aucune logique corpus-spécifique
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from knowbase.runtime_a3.plan import (
    KIND_TO_TOOL,
    TOOL_TIMEOUTS,
    Planner,
    plan,
)
from knowbase.runtime_a3.schemas import (
    ParseInput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    SubGoalKind,
    ToolCall,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_parse_input(
    question: str = "test question",
    tenant_id: str = "default",
    as_of_date: datetime | None = None,
) -> ParseInput:
    return ParseInput(
        question=question,
        tenant_id=tenant_id,
        as_of_date=as_of_date,
    )


def _make_parse_output(
    sub_goals: list[SubGoal] | None = None,
    raw_question: str = "test question",
) -> ParseOutput:
    return ParseOutput(
        sub_goals=sub_goals if sub_goals is not None else [],
        entities=[],
        language="en",
        raw_question=raw_question,
        parse_confidence=0.85,
        parse_warnings=[],
        schema_version="a3.0",
    )


# ============================================================================
# Mapping fixe (vérification table de correspondance)
# ============================================================================


class TestMappingTable:
    def test_kind_to_tool_exhaustive(self):
        """Tous les SubGoalKind doivent avoir un mapping."""
        expected_kinds = {
            "fact_lookup", "definition_lookup", "list_enumeration",
            "lifecycle_trace", "contradiction_check", "comparison",
        }
        assert set(KIND_TO_TOOL.keys()) == expected_kinds

    def test_tool_timeouts_cover_all_tools(self):
        tools_used = set(KIND_TO_TOOL.values()) | {"qdrant_sections"}
        for tool in tools_used:
            assert tool in TOOL_TIMEOUTS, f"Tool {tool} missing timeout"
            assert TOOL_TIMEOUTS[tool] > 0


# ============================================================================
# Builders — kg_claims (fact_lookup, definition_lookup)
# ============================================================================


class TestKgClaims:
    def test_fact_lookup_full_params(self):
        as_of = datetime(2026, 5, 21, tzinfo=timezone.utc)
        po = _make_parse_output(sub_goals=[
            SubGoal(
                kind="fact_lookup",
                subject_canonical="product alpha",
                predicate_hint="max_users",
                expected_value_kind="number",
            )
        ])
        result = plan(_make_parse_input(as_of_date=as_of), po)
        assert len(result.tool_calls) == 1
        assert result.unmappable_sub_goals == []
        tc = result.tool_calls[0]
        assert tc.tool == "kg_claims"
        assert tc.sub_goal_idx == 0
        assert tc.params["subject"] == "product alpha"
        assert tc.params["predicate"] == "max_users"
        assert tc.params["tenant_id"] == "default"
        assert tc.params["as_of"] == as_of.date().isoformat()

    def test_definition_lookup_same_tool(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="definition_lookup", subject_canonical="entity_x")
        ])
        result = plan(_make_parse_input(), po)
        assert result.tool_calls[0].tool == "kg_claims"

    def test_fact_lookup_no_subject_unmappable(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical=None, predicate_hint="something")
        ])
        result = plan(_make_parse_input(), po)
        # Fallback qdrant_sections doit être ajouté car tous unmappable
        assert 0 in result.unmappable_sub_goals
        # Et un fallback qdrant_sections doit avoir été ajouté
        assert any(tc.tool == "qdrant_sections" for tc in result.tool_calls)
        assert any("missing_subject_for_kg_claims" in w for w in result.plan_warnings)

    def test_predicate_hint_can_be_none(self):
        """kg_claims tolère predicate=None — le tool fait `$predicate IS NULL OR ...`."""
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="x", predicate_hint=None)
        ])
        result = plan(_make_parse_input(), po)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].params["predicate"] is None


# ============================================================================
# kg_claims_list (list_enumeration)
# ============================================================================


class TestKgClaimsList:
    def test_list_with_subject_and_predicate(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(
                kind="list_enumeration",
                subject_canonical="entity_x",
                predicate_hint="contains",
            )
        ])
        result = plan(_make_parse_input(), po)
        tc = result.tool_calls[0]
        assert tc.tool == "kg_claims_list"
        assert tc.params["subject_filter"] == "entity_x"
        assert tc.params["predicate"] == "contains"

    def test_list_with_only_predicate(self):
        """ADR §4.2 permet subject_filter=NULL si predicate présent."""
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="list_enumeration", subject_canonical=None, predicate_hint="status")
        ])
        result = plan(_make_parse_input(), po)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].params["subject_filter"] is None
        assert result.tool_calls[0].params["predicate"] == "status"

    def test_list_with_only_subject(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="list_enumeration", subject_canonical="X", predicate_hint=None)
        ])
        result = plan(_make_parse_input(), po)
        assert len(result.tool_calls) == 1

    def test_list_no_subject_no_predicate_unmappable(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="list_enumeration", subject_canonical=None, predicate_hint=None)
        ])
        result = plan(_make_parse_input(), po)
        assert 0 in result.unmappable_sub_goals


# ============================================================================
# lifecycle_query
# ============================================================================


class TestLifecycleQuery:
    def test_lifecycle_with_subject(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(
                kind="lifecycle_trace",
                subject_canonical="module_y",
                time_filter="evolution",
            )
        ])
        result = plan(_make_parse_input(), po)
        tc = result.tool_calls[0]
        assert tc.tool == "lifecycle_query"
        assert tc.params["subject"] == "module_y"
        # PAS de as_of dans lifecycle (cf §4.3)
        assert "as_of" not in tc.params

    def test_lifecycle_without_subject_unmappable(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="lifecycle_trace", subject_canonical=None)
        ])
        result = plan(_make_parse_input(), po)
        assert 0 in result.unmappable_sub_goals


# ============================================================================
# contradiction_surface
# ============================================================================


class TestContradictionSurface:
    def test_contradiction_with_subject(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="contradiction_check", subject_canonical="entity_x")
        ])
        result = plan(_make_parse_input(), po)
        tc = result.tool_calls[0]
        assert tc.tool == "contradiction_surface"
        assert tc.params["subject"] == "entity_x"

    def test_contradiction_no_subject_unmappable(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="contradiction_check", subject_canonical=None)
        ])
        result = plan(_make_parse_input(), po)
        assert 0 in result.unmappable_sub_goals


# ============================================================================
# comparison
# ============================================================================


class TestComparison:
    def test_comparison_two_subgoals_two_calls(self):
        """Le cas standard : 2 sub_goals comparison → 2 ToolCall kg_claims."""
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="comparison", subject_canonical="A", predicate_hint="features"),
            SubGoal(kind="comparison", subject_canonical="B", predicate_hint="features"),
        ])
        result = plan(_make_parse_input(), po)
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].sub_goal_idx == 0
        assert result.tool_calls[1].sub_goal_idx == 1
        # Convention v1.0: comparison décomposé en kg_claims (diff fait en Evaluate/Synthesize)
        assert result.tool_calls[0].tool == "kg_claims"
        assert result.tool_calls[1].tool == "kg_claims"

    def test_comparison_no_subject_unmappable(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="comparison", subject_canonical=None)
        ])
        result = plan(_make_parse_input(), po)
        assert 0 in result.unmappable_sub_goals


# ============================================================================
# as_of resolution
# ============================================================================


class TestAsOfResolution:
    def test_explicit_as_of_used(self):
        # Note: as_of est sérialisé en date pure (YYYY-MM-DD) pour Cypher date(),
        # cf execute.py CYPHER_KG_CLAIMS qui fait date(c.valid_from) <= date($as_of)
        custom = datetime(2025, 1, 1, tzinfo=timezone.utc)
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="x")
        ])
        result = plan(_make_parse_input(as_of_date=custom), po)
        assert result.tool_calls[0].params["as_of"] == custom.date().isoformat()

    def test_default_as_of_is_now(self):
        from datetime import date
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="x")
        ])
        before = datetime.now(timezone.utc).date()
        result = plan(_make_parse_input(), po)
        after = datetime.now(timezone.utc).date()
        as_of_str = result.tool_calls[0].params["as_of"]
        as_of = date.fromisoformat(as_of_str)
        assert before <= as_of <= after


# ============================================================================
# Cas multi-sub-goals
# ============================================================================


class TestMultiSubGoals:
    def test_mixed_mappable_and_unmappable(self):
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="x"),       # OK
            SubGoal(kind="fact_lookup", subject_canonical=None),      # KO
            SubGoal(kind="lifecycle_trace", subject_canonical="y"),   # OK
        ])
        result = plan(_make_parse_input(), po)
        assert len(result.tool_calls) == 2
        assert result.unmappable_sub_goals == [1]
        assert result.tool_calls[0].sub_goal_idx == 0
        assert result.tool_calls[1].sub_goal_idx == 2

    def test_5_sub_goals_max(self):
        """Pydantic limite à 5 sub_goals — vérifie que le Planner gère bien."""
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical=f"entity_{i}")
            for i in range(5)
        ])
        result = plan(_make_parse_input(), po)
        assert len(result.tool_calls) == 5
        for i, tc in enumerate(result.tool_calls):
            assert tc.sub_goal_idx == i


# ============================================================================
# Fallback Qdrant — cas extrême (tous sub_goals unmappable)
# ============================================================================


class TestFallbackQdrant:
    def test_all_unmappable_triggers_qdrant_fallback(self):
        po = _make_parse_output(
            sub_goals=[
                SubGoal(kind="fact_lookup", subject_canonical=None),  # KO
                SubGoal(kind="contradiction_check", subject_canonical=None),  # KO
            ],
            raw_question="What is something?",
        )
        result = plan(_make_parse_input(question="What is something?"), po)
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.tool == "qdrant_sections"
        assert tc.params["query"] == "What is something?"
        assert tc.params["tenant_id"] == "default"
        assert "all_sub_goals_unmappable_qdrant_fallback_added" in result.plan_warnings

    def test_empty_subgoals_no_fallback(self):
        """Si Parse a retourné 0 sub_goal (out_of_scope), Plan ne doit PAS ajouter
        de fallback Qdrant — l'Evaluate décidera INSUFFICIENT_EVIDENCE directement."""
        po = _make_parse_output(sub_goals=[])
        result = plan(_make_parse_input(), po)
        assert result.tool_calls == []
        assert result.unmappable_sub_goals == []


# ============================================================================
# Schema validation
# ============================================================================


class TestSchemaValidation:
    def test_planoutput_schema_version(self):
        po = _make_parse_output(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="x")])
        result = plan(_make_parse_input(), po)
        assert result.schema_version == "a3.0"

    def test_toolcall_timeout_bounded(self):
        po = _make_parse_output(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="x")])
        result = plan(_make_parse_input(), po)
        for tc in result.tool_calls:
            assert 0 < tc.timeout_s <= 60.0

    def test_toolcall_extra_forbidden(self):
        with pytest.raises(Exception):
            ToolCall(
                sub_goal_idx=0,
                tool="kg_claims",
                params={},
                extra_field="forbidden",  # type: ignore
            )


# ============================================================================
# Determinism — same input → same output
# ============================================================================


class TestDeterminism:
    def test_same_input_same_output(self):
        fixed_as_of = datetime(2026, 5, 21, tzinfo=timezone.utc)
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="x", predicate_hint="p"),
            SubGoal(kind="lifecycle_trace", subject_canonical="y"),
        ])
        r1 = plan(_make_parse_input(as_of_date=fixed_as_of), po)
        r2 = plan(_make_parse_input(as_of_date=fixed_as_of), po)
        # Comparaison via model_dump pour égalité structurelle
        assert r1.model_dump() == r2.model_dump()


# ============================================================================
# Domain-agnostic charter
# ============================================================================


class TestDomainAgnostic:
    def test_plan_module_no_corpus_tokens(self):
        """Source plan.py ne contient AUCUN token corpus-spécifique."""
        from pathlib import Path
        import inspect
        from knowbase.runtime_a3 import plan as plan_module

        src_path = Path(inspect.getfile(plan_module))
        src = src_path.read_text(encoding="utf-8").lower()
        forbidden = ["sap", "s4hana", "s/4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs", "etops",
                     "icd-10", "icd10", "rcp", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in src, f"Corpus-specific token '{token}' found in plan.py"
