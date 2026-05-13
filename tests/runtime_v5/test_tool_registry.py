"""Tests ToolRegistry + ToolSpec (CH-52.4.1)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowbase.runtime_v5.tools.registry import (
    EXPERIMENTAL_NAMESPACE,
    MAX_PUBLIC_TOOLS,
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    ToolRegistryError,
    ToolSpec,
    get_default_registry,
    reset_default_registry,
)


def _sample_spec(name: str = "outline", experimental: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        category=ToolCategory.NAVIGATION,
        description="Returns the hierarchical structure of a document with sections, levels, and page ranges.",
        preferred_when="overview requested or first call to explore a doc",
        evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "max_sections": {"type": "integer", "default": 80},
            },
            "required": ["doc_id"],
        },
        is_experimental=experimental,
    )


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_default_registry()
    yield
    reset_default_registry()


# ─── ToolSpec validation ─────────────────────────────────────────────────────


class TestToolSpec:
    def test_minimal_valid_spec(self):
        spec = _sample_spec()
        assert spec.name == "outline"
        assert spec.category == ToolCategory.NAVIGATION

    def test_invalid_name_rejected(self):
        with pytest.raises(ValidationError):
            ToolSpec(
                name="Invalid Name!",  # spaces + punct
                category=ToolCategory.NAVIGATION,
                description="x" * 30,
                preferred_when="case",
                evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
                parameters_schema={"type": "object", "additionalProperties": False, "properties": {}},
            )

    def test_short_description_rejected(self):
        with pytest.raises(ValidationError):
            ToolSpec(
                name="t",
                category=ToolCategory.NAVIGATION,
                description="short",  # < 10 chars
                preferred_when="case xyz",
                evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
                parameters_schema={"type": "object", "additionalProperties": False, "properties": {}},
            )

    def test_schema_requires_additional_properties_false(self):
        with pytest.raises(ValidationError):
            ToolSpec(
                name="t",
                category=ToolCategory.NAVIGATION,
                description="A valid description.",
                preferred_when="case xyz",
                evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
                parameters_schema={"type": "object", "properties": {}},  # missing additionalProperties
            )

    def test_schema_requires_object_type(self):
        with pytest.raises(ValidationError):
            ToolSpec(
                name="t",
                category=ToolCategory.NAVIGATION,
                description="A valid description.",
                preferred_when="case xyz",
                evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
                parameters_schema={"type": "array", "additionalProperties": False},
            )

    def test_to_llm_schema(self):
        spec = _sample_spec()
        llm_schema = spec.to_llm_schema()
        assert llm_schema["type"] == "function"
        assert llm_schema["function"]["name"] == "outline"
        assert "Preferred when:" in llm_schema["function"]["description"]
        assert "structure_index" in llm_schema["function"]["description"]
        assert llm_schema["function"]["parameters"]["additionalProperties"] is False


# ─── Register / unregister ───────────────────────────────────────────────────


class TestRegisterUnregister:
    def test_register_and_get(self):
        reg = ToolRegistry()
        spec = _sample_spec("outline")
        reg.register(spec)
        assert reg.has("outline")
        assert reg.get("outline").name == "outline"

    def test_register_duplicate_refused(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        with pytest.raises(ToolRegistryError, match="already registered"):
            reg.register(_sample_spec("outline"))

    def test_register_replace_allowed_with_flag(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        # Replace with allow_replace=True OK
        reg.register(_sample_spec("outline"), allow_replace=True)

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        assert reg.unregister("outline") is True
        assert not reg.has("outline")
        assert reg.unregister("nonexistent") is False

    def test_retire_keeps_in_registry(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        assert reg.retire("outline", reason="testing") is True
        # Still in registry but is_retired=True
        spec = reg.get("outline")
        assert spec.is_retired is True
        assert spec.retired_reason == "testing"
        # No longer in public list
        assert reg.list_public_tools() == []


# ─── Ceiling 14 tools ────────────────────────────────────────────────────────


class TestCeiling:
    def test_register_below_ceiling_ok(self):
        reg = ToolRegistry()
        for i in range(MAX_PUBLIC_TOOLS):
            reg.register(_sample_spec(f"tool_{i}"))
        assert len(reg.list_public_tools()) == MAX_PUBLIC_TOOLS

    def test_register_above_ceiling_rejected(self):
        reg = ToolRegistry()
        for i in range(MAX_PUBLIC_TOOLS):
            reg.register(_sample_spec(f"tool_{i}"))
        with pytest.raises(ToolRegistryError, match="ceiling"):
            reg.register(_sample_spec(f"tool_{MAX_PUBLIC_TOOLS}"))

    def test_experimental_does_not_count_toward_ceiling(self):
        reg = ToolRegistry()
        for i in range(MAX_PUBLIC_TOOLS):
            reg.register(_sample_spec(f"tool_{i}"))
        # Register experimental (préfixe + flag)
        exp = _sample_spec(f"{EXPERIMENTAL_NAMESPACE}new_tool", experimental=True)
        reg.register(exp)
        assert reg.has(f"{EXPERIMENTAL_NAMESPACE}new_tool")
        assert len(reg.list_public_tools()) == MAX_PUBLIC_TOOLS  # still capped
        assert len(reg.list_public_tools(include_experimental=True)) == MAX_PUBLIC_TOOLS + 1

    def test_retired_frees_a_slot(self):
        reg = ToolRegistry()
        for i in range(MAX_PUBLIC_TOOLS):
            reg.register(_sample_spec(f"tool_{i}"))
        reg.retire("tool_0", reason="superseded")
        # Slot libéré, on peut register un nouveau public
        reg.register(_sample_spec("new_tool"))
        assert reg.has("new_tool")

    def test_experimental_prefix_must_match_flag(self):
        reg = ToolRegistry()
        # Tool starting with experimental_* but is_experimental=False → refuse
        with pytest.raises(ToolRegistryError, match="experimental"):
            reg.register(_sample_spec(f"{EXPERIMENTAL_NAMESPACE}wrong_flag", experimental=False))


# ─── LLM tools sérialisation ────────────────────────────────────────────────


class TestLlmSerialization:
    def test_to_llm_tools_excludes_experimental_by_default(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        reg.register(_sample_spec(f"{EXPERIMENTAL_NAMESPACE}beta", experimental=True))
        tools = reg.to_llm_tools()
        names = [t["function"]["name"] for t in tools]
        assert "outline" in names
        assert f"{EXPERIMENTAL_NAMESPACE}beta" not in names

    def test_to_llm_tools_includes_experimental_with_flag(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        reg.register(_sample_spec(f"{EXPERIMENTAL_NAMESPACE}beta", experimental=True))
        tools = reg.to_llm_tools(include_experimental=True)
        names = [t["function"]["name"] for t in tools]
        assert len(names) == 2
        assert f"{EXPERIMENTAL_NAMESPACE}beta" in names

    def test_retired_tools_not_in_llm_serialization(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        reg.retire("outline", reason="deprecated")
        tools = reg.to_llm_tools()
        assert tools == []


# ─── Metrics & auto-retirement ──────────────────────────────────────────────


class TestMetricsAndGate:
    def test_record_call_updates_accuracy(self):
        reg = ToolRegistry(min_calls_for_gate=10)
        reg.register(_sample_spec("outline"))
        reg.record_call("outline", was_correct_selection=True, evidence_gain=0.8)
        spec = reg.get("outline")
        assert spec.n_calls_total == 1
        assert spec.selection_accuracy is not None
        assert spec.selection_accuracy > 0

    def test_auto_retirement_when_accuracy_low(self):
        reg = ToolRegistry(
            min_accuracy_threshold=0.90,
            min_calls_for_gate=10,
        )
        reg.register(_sample_spec("bad_tool"))
        # 10 calls with 0/10 correct → accuracy = 0 → retire
        for _ in range(10):
            reg.record_call("bad_tool", was_correct_selection=False)
        spec = reg.get("bad_tool")
        assert spec.is_retired is True
        assert "auto_gate_retirement" in spec.retired_reason

    def test_no_auto_retirement_below_min_calls(self):
        reg = ToolRegistry(min_accuracy_threshold=0.90, min_calls_for_gate=100)
        reg.register(_sample_spec("new_tool"))
        # 5 calls all wrong : pas encore atteint min_calls → pas de gate
        for _ in range(5):
            reg.record_call("new_tool", was_correct_selection=False)
        spec = reg.get("new_tool")
        assert spec.is_retired is False

    def test_experimental_tools_not_auto_retired(self):
        reg = ToolRegistry(min_accuracy_threshold=0.90, min_calls_for_gate=10)
        reg.register(_sample_spec(f"{EXPERIMENTAL_NAMESPACE}bad", experimental=True))
        for _ in range(15):
            reg.record_call(f"{EXPERIMENTAL_NAMESPACE}bad", was_correct_selection=False)
        spec = reg.get(f"{EXPERIMENTAL_NAMESPACE}bad")
        assert spec.is_retired is False  # experimental exempt

    def test_confusion_matrix(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        reg.register(_sample_spec("find_in"))
        reg.record_call("outline", was_correct_selection=False, confused_with="find_in")
        reg.record_call("outline", was_correct_selection=False, confused_with="find_in")
        reg.record_call("outline", was_correct_selection=True)
        confusion = reg.get_confusion_matrix("outline")
        assert confusion.get("find_in") == 2


# ─── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_basic(self):
        reg = ToolRegistry()
        reg.register(_sample_spec("outline"))
        reg.register(_sample_spec(f"{EXPERIMENTAL_NAMESPACE}beta", experimental=True))
        reg.register(_sample_spec("retired_tool"))
        reg.retire("retired_tool", reason="testing")

        stats = reg.stats()
        assert stats["n_public"] == 1
        assert stats["n_experimental"] == 1
        assert stats["n_retired"] == 1
        assert stats["ceiling"] == MAX_PUBLIC_TOOLS
        assert stats["slots_available"] == MAX_PUBLIC_TOOLS - 1


# ─── Singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_default_registry_singleton(self):
        r1 = get_default_registry()
        r2 = get_default_registry()
        assert r1 is r2

    def test_reset_singleton(self):
        r1 = get_default_registry()
        reset_default_registry()
        r2 = get_default_registry()
        assert r1 is not r2
