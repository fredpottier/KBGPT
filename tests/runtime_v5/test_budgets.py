"""Tests BudgetTracker + ShapeBudget (CH-52.5.2 / S4.2)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.agent.budgets import (
    BudgetExceeded,
    BudgetTracker,
    DEFAULT_SHAPE_BUDGET,
    HARD_CAP_ITER,
    HARD_CAP_OUTPUT_TOKENS,
    HARD_CAP_RETRIEVED_CHARS,
    HARD_CAP_TOOL_CALLS,
    SHAPE_BUDGETS,
    ShapeBudget,
    get_shape_budget,
)


# ─── ShapeBudget mapping ─────────────────────────────────────────────────────


class TestShapeBudgetMapping:
    def test_factual_smallest(self):
        b = get_shape_budget("factual")
        assert b.max_iterations == 3
        assert b.max_tool_calls == 8

    def test_multi_hop_larger(self):
        b = get_shape_budget("multi_hop")
        assert b.max_iterations == 8
        assert b.max_tool_calls == 25

    def test_unknown_shape_returns_default(self):
        b = get_shape_budget("invented_shape")
        assert b == DEFAULT_SHAPE_BUDGET

    def test_none_returns_default(self):
        assert get_shape_budget(None) == DEFAULT_SHAPE_BUDGET

    def test_all_shapes_under_hard_caps(self):
        """Tous les budgets per-shape doivent rester sous les hard caps absolus."""
        for shape, b in SHAPE_BUDGETS.items():
            assert b.max_iterations <= HARD_CAP_ITER, f"{shape}: iter > hard cap"
            assert b.max_tool_calls <= HARD_CAP_TOOL_CALLS, f"{shape}: tool_calls > hard cap"
            assert b.max_retrieved_chars <= HARD_CAP_RETRIEVED_CHARS, f"{shape}: chars > hard cap"
            assert b.max_output_tokens <= HARD_CAP_OUTPUT_TOKENS, f"{shape}: tokens > hard cap"

    def test_case_insensitive(self):
        assert get_shape_budget("FACTUAL") == get_shape_budget("factual")


# ─── BudgetTracker init ──────────────────────────────────────────────────────


class TestInit:
    def test_init_with_shape(self):
        t = BudgetTracker(shape="factual")
        assert t.soft_caps.max_iterations == 3
        assert t.iterations == 0
        assert t.tool_calls == 0

    def test_init_with_override(self):
        t = BudgetTracker(shape="factual", override_max_iterations=10)
        assert t.soft_caps.max_iterations == 10

    def test_override_clamped_to_hard_cap(self):
        t = BudgetTracker(shape="factual", override_max_iterations=999)
        assert t.soft_caps.max_iterations == HARD_CAP_ITER

    def test_init_no_shape_uses_default(self):
        t = BudgetTracker(shape=None)
        assert t.soft_caps == DEFAULT_SHAPE_BUDGET


# ─── Increment counters ─────────────────────────────────────────────────────


class TestCounters:
    def test_increment_iteration(self):
        t = BudgetTracker(shape="multi_hop")
        t.increment_iteration()
        t.increment_iteration()
        assert t.iterations == 2

    def test_increment_tool_call(self):
        t = BudgetTracker()
        for _ in range(5):
            t.increment_tool_call()
        assert t.tool_calls == 5

    def test_add_retrieved_chars(self):
        t = BudgetTracker()
        t.add_retrieved_chars(1000)
        t.add_retrieved_chars(500)
        assert t.retrieved_chars == 1500

    def test_add_retrieved_chars_negative_ignored(self):
        t = BudgetTracker()
        t.add_retrieved_chars(-100)
        assert t.retrieved_chars == 0

    def test_add_output_tokens(self):
        t = BudgetTracker()
        t.add_output_tokens(100)
        assert t.output_tokens == 100


# ─── Soft caps detection ────────────────────────────────────────────────────


class TestSoftCaps:
    def test_no_exceeded_initial(self):
        t = BudgetTracker(shape="multi_hop")
        exceeded, name = t.check_soft_caps()
        assert exceeded is False
        assert name is None

    def test_iterations_exceeded(self):
        t = BudgetTracker(shape="factual")  # max=3
        for _ in range(3):
            t.increment_iteration()
        exceeded, name = t.check_soft_caps()
        assert exceeded is True
        assert name == "max_iterations"

    def test_tool_calls_exceeded(self):
        t = BudgetTracker(shape="factual")  # max=8
        for _ in range(8):
            t.increment_tool_call()
        exceeded, name = t.check_soft_caps()
        assert exceeded is True
        assert name == "max_tool_calls"

    def test_retrieved_chars_exceeded(self):
        t = BudgetTracker(shape="factual")  # max=20k
        t.add_retrieved_chars(20_000)
        exceeded, name = t.check_soft_caps()
        assert exceeded is True
        assert name == "max_retrieved_chars"

    def test_output_tokens_exceeded(self):
        t = BudgetTracker(shape="factual")  # max=3k
        t.add_output_tokens(3_000)
        exceeded, name = t.check_soft_caps()
        assert exceeded is True
        assert name == "max_output_tokens"

    def test_one_axis_does_not_cover_another(self):
        """Si seul retrieved_chars explose, on n'a pas iterations exhausted."""
        t = BudgetTracker(shape="multi_hop")
        t.add_retrieved_chars(100_000)  # explose chars
        # iterations encore à 0
        exceeded, name = t.check_soft_caps()
        assert exceeded is True
        assert name == "max_retrieved_chars"


# ─── Hard caps enforce ──────────────────────────────────────────────────────


class TestHardCaps:
    def test_hard_caps_not_triggered_at_soft_threshold(self):
        t = BudgetTracker(shape="factual")
        t.iterations = 3  # = soft cap
        # No hard cap exceeded
        exceeded, _ = t.check_hard_caps()
        assert exceeded is False

    def test_hard_cap_iterations_raises(self):
        t = BudgetTracker()
        t.iterations = HARD_CAP_ITER + 1
        with pytest.raises(BudgetExceeded) as exc:
            t.enforce_hard_caps()
        assert exc.value.budget_name == "max_iterations"

    def test_hard_cap_tool_calls_raises(self):
        t = BudgetTracker()
        t.tool_calls = HARD_CAP_TOOL_CALLS + 1
        with pytest.raises(BudgetExceeded) as exc:
            t.enforce_hard_caps()
        assert exc.value.budget_name == "max_tool_calls"

    def test_hard_cap_chars_raises(self):
        t = BudgetTracker()
        t.retrieved_chars = HARD_CAP_RETRIEVED_CHARS + 1
        with pytest.raises(BudgetExceeded) as exc:
            t.enforce_hard_caps()
        assert exc.value.budget_name == "max_retrieved_chars"

    def test_hard_cap_tokens_raises(self):
        t = BudgetTracker()
        t.output_tokens = HARD_CAP_OUTPUT_TOKENS + 1
        with pytest.raises(BudgetExceeded) as exc:
            t.enforce_hard_caps()
        assert exc.value.budget_name == "max_output_tokens"


# ─── Degraded structure extension ───────────────────────────────────────────


class TestDegradedStructureExtension:
    def test_extends_max_iter(self):
        t = BudgetTracker(shape="factual")  # 3 iter default
        t.extend_for_degraded_structure(extra_iter=2)
        assert t.soft_caps.max_iterations == 5

    def test_extension_clamped_to_hard_cap(self):
        t = BudgetTracker(shape="multi_hop")  # 8 iter default
        t.extend_for_degraded_structure(extra_iter=10)  # would be 18
        assert t.soft_caps.max_iterations == HARD_CAP_ITER  # 12

    def test_other_axes_unchanged(self):
        t = BudgetTracker(shape="multi_hop")
        orig_tool_calls = t.soft_caps.max_tool_calls
        orig_chars = t.soft_caps.max_retrieved_chars
        t.extend_for_degraded_structure()
        assert t.soft_caps.max_tool_calls == orig_tool_calls
        assert t.soft_caps.max_retrieved_chars == orig_chars


# ─── Snapshot ────────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_structure(self):
        t = BudgetTracker(shape="multi_hop")
        t.increment_iteration()
        t.add_retrieved_chars(5000)
        snap = t.snapshot()
        assert snap["shape"] == "multi_hop"
        assert snap["counters"]["iterations"] == 1
        assert snap["counters"]["retrieved_chars"] == 5000
        assert "soft_caps" in snap and "hard_caps" in snap
        assert "utilization_soft" in snap
        assert 0 <= snap["utilization_soft"]["iterations"] <= 1

    def test_utilization_soft_at_1_when_exceeded(self):
        t = BudgetTracker(shape="factual")
        for _ in range(3):
            t.increment_iteration()
        snap = t.snapshot()
        assert snap["utilization_soft"]["iterations"] == 1.0


# ─── BudgetExceeded exception ───────────────────────────────────────────────


class TestBudgetExceededException:
    def test_attributes(self):
        try:
            raise BudgetExceeded("max_iterations", 13, 12)
        except BudgetExceeded as e:
            assert e.budget_name == "max_iterations"
            assert e.current == 13
            assert e.cap == 12
            assert "13" in str(e)
            assert "12" in str(e)
