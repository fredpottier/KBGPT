"""Tests enregistrement des 7 POC tools dans le registry (CH-52.4.2)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    get_default_registry,
    reset_default_registry,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture
def registry():
    return ToolRegistry()


# ─── Registration ────────────────────────────────────────────────────────────


def test_register_poc_tools_success(registry):
    result = register_poc_tools(registry)
    assert result["errors"] == []
    assert len(result["registered"]) == 7
    expected_names = {
        "outline", "read", "find_in", "resolve_ref",
        "expand_context", "compare_sections",
        "experimental_list_versions",
    }
    assert set(result["registered"]) == expected_names


def test_public_tools_count(registry):
    register_poc_tools(registry)
    public = registry.list_public_tools()
    # 6 public + 1 experimental (excluded by default)
    assert len(public) == 6
    public_names = {t.name for t in public}
    assert "experimental_list_versions" not in public_names


def test_experimental_included_with_flag(registry):
    register_poc_tools(registry)
    all_tools = registry.list_public_tools(include_experimental=True)
    assert len(all_tools) == 7
    names = {t.name for t in all_tools}
    assert "experimental_list_versions" in names


def test_handlers_attached(registry):
    register_poc_tools(registry)
    spec = registry.get("outline")
    assert spec.handler is not None
    assert callable(spec.handler)


def test_double_register_fails_without_replace(registry):
    register_poc_tools(registry)
    result = register_poc_tools(registry)  # second call sans allow_replace
    # Tous failed
    assert len(result["registered"]) == 0
    assert len(result["errors"]) == 7


def test_double_register_with_replace_ok(registry):
    register_poc_tools(registry)
    result = register_poc_tools(registry, allow_replace=True)
    assert len(result["registered"]) == 7
    assert result["errors"] == []


# ─── Tool spec contracts ──────────────────────────────────────────────────────


def test_all_tools_have_evidence_type(registry):
    register_poc_tools(registry)
    for spec in registry.list_all():
        assert spec.evidence_type_returned in EvidenceType.__members__.values()


def test_all_tools_have_strict_schema(registry):
    register_poc_tools(registry)
    for spec in registry.list_all():
        schema = spec.parameters_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        # All have at least one property
        assert "properties" in schema and len(schema["properties"]) > 0


def test_specific_tool_categories(registry):
    register_poc_tools(registry)
    assert registry.get("outline").category == ToolCategory.NAVIGATION
    assert registry.get("read").category == ToolCategory.READING
    assert registry.get("find_in").category == ToolCategory.SEARCH
    assert registry.get("resolve_ref").category == ToolCategory.SEARCH
    assert registry.get("expand_context").category == ToolCategory.NAVIGATION
    assert registry.get("compare_sections").category == ToolCategory.COMPARISON
    assert registry.get("experimental_list_versions").category == ToolCategory.LIFECYCLE


def test_llm_serialization_complete(registry):
    register_poc_tools(registry)
    llm_tools = registry.to_llm_tools()
    assert len(llm_tools) == 6
    for tool in llm_tools:
        # OpenAI/Anthropic-compatible structure
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]
        assert tool["function"]["parameters"]["additionalProperties"] is False
        # description must contain preferred_when + evidence_type for LLM
        assert "Preferred when:" in tool["function"]["description"]
        assert "returns evidence type:" in tool["function"]["description"]


def test_ceiling_respected(registry):
    """Les 6 public tools laissent encore 8 slots disponibles (14-6)."""
    register_poc_tools(registry)
    stats = registry.stats()
    assert stats["n_public"] == 6
    assert stats["slots_available"] == 8


# ─── Domain-agnostic charter ──────────────────────────────────────────────────


def test_no_domain_specific_words_in_descriptions(registry):
    """Charte : aucune description ne doit mentionner SAP, S/4HANA, regulation,
    GDPR, médical, etc. — vocabulaire universel uniquement."""
    register_poc_tools(registry)
    forbidden = [
        "sap", "s/4hana", "s4hana", "gdpr", "rgpd", "regulation", "regulatory",
        "medical", "patient", "amendment", "compliance", "rfp", "aerospace",
    ]
    for spec in registry.list_all():
        desc_lower = (spec.description + " " + spec.preferred_when).lower()
        for word in forbidden:
            assert word not in desc_lower, (
                f"Tool '{spec.name}' has forbidden domain-specific word '{word}' "
                f"in description/preferred_when"
            )
