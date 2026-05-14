"""Tests ToolCallSanitizer (CH-52.4.3)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import ToolRegistry
from knowbase.runtime_v5.tools.sanitizer import (
    ToolCallError,
    ToolCallSanitizer,
)


@pytest.fixture
def registry():
    r = ToolRegistry()
    register_poc_tools(r)
    return r


@pytest.fixture
def sanitizer(registry):
    return ToolCallSanitizer(registry)


# ─── Happy path ──────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_valid_call_passes_through(self, sanitizer):
        result = sanitizer.sanitize("outline", {"doc_id": "doc_x"})
        assert result.spec.name == "outline"
        assert result.args == {"doc_id": "doc_x"}
        assert not result.report.has_repairs()

    def test_valid_call_with_defaults_omitted(self, sanitizer):
        result = sanitizer.sanitize("outline", {"doc_id": "doc_x", "max_sections": 50})
        assert result.args == {"doc_id": "doc_x", "max_sections": 50}

    def test_all_required_present(self, sanitizer):
        result = sanitizer.sanitize(
            "read",
            {"doc_id": "doc_x", "section_path_or_numbering": "/3/3.1"},
        )
        assert result.args["doc_id"] == "doc_x"


# ─── Repair : strip extra keys ───────────────────────────────────────────────


class TestStripExtraKeys:
    def test_extra_key_stripped(self, sanitizer):
        result = sanitizer.sanitize(
            "outline",
            {"doc_id": "doc_x", "garbage_key": "ignore me", "another_extra": 42},
        )
        assert "garbage_key" not in result.args
        assert "another_extra" not in result.args
        assert "garbage_key" in result.report.stripped_extra_keys
        assert "another_extra" in result.report.stripped_extra_keys
        assert result.report.has_repairs()


# ─── Coerce types ────────────────────────────────────────────────────────────


class TestCoercion:
    def test_int_as_string_coerced(self, sanitizer):
        # max_sections as string "50" → int 50
        result = sanitizer.sanitize(
            "outline",
            {"doc_id": "doc_x", "max_sections": "50"},
        )
        assert result.args["max_sections"] == 50
        assert isinstance(result.args["max_sections"], int)
        assert len(result.report.coerced_types) == 1
        assert result.report.coerced_types[0]["key"] == "max_sections"

    def test_int_as_float_with_integer_value_coerced(self, sanitizer):
        result = sanitizer.sanitize(
            "outline",
            {"doc_id": "doc_x", "max_sections": 50.0},
        )
        assert result.args["max_sections"] == 50

    def test_string_as_int_kept_as_string(self, sanitizer):
        # doc_id: type string — even si on passe int, on coerce
        result = sanitizer.sanitize("outline", {"doc_id": 42})
        assert result.args["doc_id"] == "42"
        assert any(c["key"] == "doc_id" for c in result.report.coerced_types)


# ─── Drop None for optional ──────────────────────────────────────────────────


class TestNoneHandling:
    def test_none_optional_dropped(self, sanitizer):
        # max_sections est optionnel avec default → None drop
        result = sanitizer.sanitize(
            "outline",
            {"doc_id": "doc_x", "max_sections": None},
        )
        assert "max_sections" not in result.args
        assert "max_sections" in result.report.dropped_none_keys

    def test_nullable_field_keeps_none(self, sanitizer):
        # resolve_ref.current_section_id type=["string", "null"]
        result = sanitizer.sanitize(
            "resolve_ref",
            {"doc_id": "doc_x", "ref_text": "see Article 5",
             "current_section_id": None},
        )
        # null est valide → conservé
        assert result.args.get("current_section_id") is None


# ─── Validation errors ──────────────────────────────────────────────────────


class TestValidationErrors:
    def test_missing_required_raises(self, sanitizer):
        with pytest.raises(ToolCallError) as exc:
            sanitizer.sanitize("read", {"doc_id": "doc_x"})  # missing section_path_or_numbering
        assert exc.value.error_type in (
            "schema_validation_failed",
            "missing_required",
        )

    def test_wrong_type_uncoerced_raises(self, sanitizer):
        # find_in.max_results minimum=1 — passer 0 doit échouer après sanitize
        with pytest.raises(ToolCallError):
            sanitizer.sanitize(
                "find_in",
                {"doc_id": "doc_x", "query": "test", "max_results": 0},
            )

    def test_unknown_tool_raises(self, sanitizer):
        with pytest.raises(ToolCallError) as exc:
            sanitizer.sanitize("nonexistent_tool", {})
        assert exc.value.error_type == "unknown_tool"

    def test_args_not_dict_raises(self, sanitizer):
        with pytest.raises(ToolCallError) as exc:
            sanitizer.sanitize("outline", "not a dict")
        assert exc.value.error_type == "args_not_dict"


# ─── Retired tools ───────────────────────────────────────────────────────────


class TestRetiredTools:
    def test_retired_tool_raises(self, registry):
        registry.retire("outline", reason="test_retirement")
        sanitizer = ToolCallSanitizer(registry)
        with pytest.raises(ToolCallError) as exc:
            sanitizer.sanitize("outline", {"doc_id": "doc_x"})
        assert exc.value.error_type == "retired_tool"


# ─── Combo repairs (multiple) ────────────────────────────────────────────────


class TestComboRepairs:
    def test_multiple_repairs_in_one_call(self, sanitizer):
        result = sanitizer.sanitize(
            "outline",
            {
                "doc_id": 42,  # int → str
                "max_sections": "10",  # str → int
                "min_text_chars": None,  # drop
                "extra_garbage": [1, 2, 3],  # strip
            },
        )
        report = result.report
        assert len(report.stripped_extra_keys) == 1
        assert len(report.coerced_types) == 2  # doc_id + max_sections
        assert len(report.dropped_none_keys) == 1
        assert result.args == {"doc_id": "42", "max_sections": 10}


# ─── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_track_repairs_and_invalid(self, sanitizer):
        # 1 valid clean
        sanitizer.sanitize("outline", {"doc_id": "doc_x"})
        # 1 with repair
        sanitizer.sanitize("outline", {"doc_id": "doc_x", "extra_key": "bad"})
        # 1 invalid
        try:
            sanitizer.sanitize("read", {"doc_id": "doc_x"})
        except ToolCallError:
            pass
        # 1 unknown
        try:
            sanitizer.sanitize("nonexistent", {})
        except ToolCallError:
            pass

        stats = sanitizer.stats()
        assert stats["n_total"] == 4
        assert stats["n_repaired"] == 1
        assert stats["n_invalid"] == 1
        assert stats["n_unknown_tool"] == 1
        assert 0 < stats["repair_rate"] < 1
        assert 0 < stats["invalid_rate"] < 1
