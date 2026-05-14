"""Tests ExecutionPlan + PlanStep (CH-52.5.3 / S4.3)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowbase.runtime_v5.agent.execution_plan import (
    PLAN_REQUIRED_SHAPES,
    ExecutionPlan,
    PlanStatus,
    PlanStep,
    StepStatus,
    is_plan_required,
    validate_plan_against_registry,
)


def _step(intent="find sections about X", tool="find_in", critical=True, optional=False) -> PlanStep:
    return PlanStep(
        intent=intent,
        tool=tool,
        args={"doc_id": "doc_x", "query": "X"},
        expected_evidence_shape="section hits matching query",
        critical=critical,
        optional=optional,
    )


# ─── PLAN_REQUIRED_SHAPES ────────────────────────────────────────────────────


class TestPlanRequiredShapes:
    def test_complex_shapes_required(self):
        assert is_plan_required("comparison")
        assert is_plan_required("multi_hop")
        assert is_plan_required("lifecycle")
        assert is_plan_required("causal")

    def test_simple_shapes_not_required(self):
        assert is_plan_required("factual") is False
        assert is_plan_required("listing") is False
        assert is_plan_required("contextual") is False

    def test_none_not_required(self):
        assert is_plan_required(None) is False
        assert is_plan_required("") is False

    def test_case_insensitive(self):
        assert is_plan_required("COMPARISON")
        assert is_plan_required("Multi_Hop")


# ─── PlanStep ────────────────────────────────────────────────────────────────


class TestPlanStep:
    def test_valid_step(self):
        s = _step()
        assert s.intent == "find sections about X"
        assert s.status == StepStatus.PENDING
        assert s.evidence_summary is None

    def test_intent_too_short_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(
                intent="x",  # < 5 chars
                tool="find_in",
                args={},
                expected_evidence_shape="evidence",
            )

    def test_tool_with_invalid_chars_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(
                intent="some intent",
                tool="bad tool name!",  # has space + punct
                args={},
                expected_evidence_shape="evidence",
            )

    def test_extra_field_rejected(self):
        """ConfigDict(extra='forbid')."""
        with pytest.raises(ValidationError):
            PlanStep(
                intent="x" * 10,
                tool="find_in",
                args={},
                expected_evidence_shape="evidence",
                garbage_field="oops",
            )

    def test_mark_succeeded(self):
        s = _step()
        s.mark_succeeded("found 3 sections matching")
        assert s.status == StepStatus.SUCCEEDED
        assert "found 3 sections" in s.evidence_summary

    def test_mark_failed(self):
        s = _step()
        s.mark_failed("tool returned error")
        assert s.status == StepStatus.FAILED
        assert "tool returned error" in s.error

    def test_mark_skipped(self):
        s = _step(optional=True)
        s.mark_skipped("non-critical, time budget low")
        assert s.status == StepStatus.SKIPPED
        assert "non-critical" in s.error  # reason stored in error field


# ─── ExecutionPlan ───────────────────────────────────────────────────────────


class TestExecutionPlan:
    def test_valid_plan(self):
        plan = ExecutionPlan(
            steps=[_step(), _step(tool="read")],
            max_iter_estimated=3,
            notes="approach: find then read",
        )
        assert plan.status == PlanStatus.DRAFT
        assert plan.current_step_idx == 0
        assert len(plan.steps) == 2

    def test_empty_steps_rejected(self):
        with pytest.raises(ValidationError):
            ExecutionPlan(steps=[], max_iter_estimated=3)

    def test_too_many_steps_rejected(self):
        with pytest.raises(ValidationError):
            ExecutionPlan(steps=[_step() for _ in range(21)], max_iter_estimated=3)

    def test_max_iter_clamped(self):
        with pytest.raises(ValidationError):
            ExecutionPlan(steps=[_step()], max_iter_estimated=99)  # > 12 hard cap
        with pytest.raises(ValidationError):
            ExecutionPlan(steps=[_step()], max_iter_estimated=0)  # < 1


# ─── Navigation ──────────────────────────────────────────────────────────────


class TestNavigation:
    def test_get_current_step_initial(self):
        plan = ExecutionPlan(
            steps=[_step(intent="step0 first" + "x"),
                   _step(intent="step1 second" + "x")],
            max_iter_estimated=2,
        )
        cur = plan.get_current_step()
        assert cur is not None
        assert "step0" in cur.intent

    def test_advance(self):
        plan = ExecutionPlan(
            steps=[_step(intent="step zero again"), _step(intent="step one again")],
            max_iter_estimated=2,
        )
        next_step = plan.advance()
        assert next_step is not None
        assert plan.current_step_idx == 1
        # advance past end → None
        next_step = plan.advance()
        assert next_step is None
        assert plan.is_complete()


# ─── Replan logic ────────────────────────────────────────────────────────────


class TestReplanLogic:
    def test_no_replan_if_all_succeeded(self):
        plan = ExecutionPlan(
            steps=[_step(), _step(tool="read")],
            max_iter_estimated=2,
        )
        for s in plan.steps:
            s.mark_succeeded("done")
        assert plan.needs_replan() is False

    def test_replan_needed_if_critical_failed(self):
        plan = ExecutionPlan(
            steps=[_step(critical=True), _step(tool="read")],
            max_iter_estimated=2,
        )
        plan.steps[0].mark_failed("tool error")
        assert plan.needs_replan() is True

    def test_no_replan_if_max_replans_used(self):
        plan = ExecutionPlan(
            steps=[_step(critical=True)],
            max_iter_estimated=2,
            max_replans=1,
        )
        plan.n_replans_used = 1
        plan.steps[0].mark_failed("error")
        assert plan.needs_replan() is False

    def test_no_replan_if_replanning_disabled(self):
        plan = ExecutionPlan(
            steps=[_step(critical=True)],
            max_iter_estimated=2,
            replanning_allowed=False,
        )
        plan.steps[0].mark_failed("error")
        assert plan.needs_replan() is False

    def test_no_replan_if_optional_step_failed(self):
        plan = ExecutionPlan(
            steps=[_step(critical=False, optional=True), _step(tool="read")],
            max_iter_estimated=2,
        )
        plan.steps[0].mark_failed("OK, was optional")
        assert plan.needs_replan() is False


# ─── all_critical_failed → abort ────────────────────────────────────────────


class TestAbort:
    def test_all_critical_failed(self):
        plan = ExecutionPlan(
            steps=[_step(critical=True), _step(tool="read", critical=True)],
            max_iter_estimated=2,
        )
        for s in plan.steps:
            s.mark_failed("error")
        assert plan.all_critical_failed() is True

    def test_partial_critical_failure_not_abort(self):
        plan = ExecutionPlan(
            steps=[_step(critical=True), _step(tool="read", critical=True)],
            max_iter_estimated=2,
        )
        plan.steps[0].mark_failed("error")
        plan.steps[1].mark_succeeded("OK")
        assert plan.all_critical_failed() is False

    def test_no_critical_no_abort(self):
        """Si aucun step n'est critique → all_critical_failed always False."""
        plan = ExecutionPlan(
            steps=[_step(critical=False, optional=True)],
            max_iter_estimated=2,
        )
        plan.steps[0].mark_failed("error")
        assert plan.all_critical_failed() is False


# ─── Finalize ────────────────────────────────────────────────────────────────


class TestFinalize:
    def test_finalize_completed(self):
        plan = ExecutionPlan(
            steps=[_step(), _step(tool="read")],
            max_iter_estimated=2,
        )
        for s in plan.steps:
            s.mark_succeeded("done")
        assert plan.finalize() == PlanStatus.COMPLETED

    def test_finalize_partial(self):
        plan = ExecutionPlan(
            steps=[_step(), _step(tool="read", critical=False, optional=True)],
            max_iter_estimated=2,
        )
        plan.steps[0].mark_succeeded("done")
        plan.steps[1].mark_skipped("time low")
        assert plan.finalize() == PlanStatus.PARTIAL

    def test_finalize_aborted(self):
        plan = ExecutionPlan(
            steps=[_step(critical=True)],
            max_iter_estimated=1,
        )
        plan.steps[0].mark_failed("error")
        assert plan.finalize() == PlanStatus.ABORTED


# ─── Counters ────────────────────────────────────────────────────────────────


class TestCounters:
    def test_n_succeeded_failed_skipped(self):
        plan = ExecutionPlan(
            steps=[_step(), _step(tool="read"), _step(tool="expand_context")],
            max_iter_estimated=3,
        )
        plan.steps[0].mark_succeeded("OK")
        plan.steps[1].mark_failed("err")
        plan.steps[2].mark_skipped("optional")
        assert plan.n_steps_succeeded() == 1
        assert plan.n_steps_failed() == 1
        assert plan.n_steps_skipped() == 1


# ─── Replan counter ─────────────────────────────────────────────────────────


class TestReplanCounter:
    def test_increment_replan(self):
        plan = ExecutionPlan(
            steps=[_step()],
            max_iter_estimated=2,
            max_replans=2,
        )
        plan.increment_replan()
        assert plan.n_replans_used == 1
        assert plan.status == PlanStatus.REPLANNED


# ─── Summary ─────────────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_compact(self):
        plan = ExecutionPlan(
            steps=[_step(), _step(tool="read")],
            max_iter_estimated=2,
        )
        plan.steps[0].mark_succeeded("OK")
        s = plan.summary()
        assert s["n_steps_total"] == 2
        assert s["n_steps_succeeded"] == 1
        assert s["current_step_idx"] == 0
        assert s["max_replans"] == 1


# ─── Validation against registry ────────────────────────────────────────────


class TestValidateAgainstRegistry:
    def test_all_tools_exist(self):
        from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
        from knowbase.runtime_v5.tools.registry import ToolRegistry
        reg = ToolRegistry()
        register_poc_tools(reg)
        plan = ExecutionPlan(
            steps=[_step(tool="find_in"), _step(tool="read")],
            max_iter_estimated=2,
        )
        errors = validate_plan_against_registry(plan, reg)
        assert errors == []

    def test_unknown_tool_flagged(self):
        from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
        from knowbase.runtime_v5.tools.registry import ToolRegistry
        reg = ToolRegistry()
        register_poc_tools(reg)
        plan = ExecutionPlan(
            steps=[_step(tool="nonexistent_tool")],
            max_iter_estimated=1,
        )
        errors = validate_plan_against_registry(plan, reg)
        assert len(errors) == 1
        assert "nonexistent_tool" in errors[0]
        assert "not in registry" in errors[0]

    def test_retired_tool_flagged(self):
        from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
        from knowbase.runtime_v5.tools.registry import ToolRegistry
        reg = ToolRegistry()
        register_poc_tools(reg)
        reg.retire("find_in", reason="testing")
        plan = ExecutionPlan(
            steps=[_step(tool="find_in")],
            max_iter_estimated=1,
        )
        errors = validate_plan_against_registry(plan, reg)
        assert len(errors) == 1
        assert "retired" in errors[0]
