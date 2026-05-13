"""V5 Reading Tools — Enregistrement des 7 tools POC dans le ToolRegistry.

CH-52.4.2 (S3.2) : wrap les 7 reading tools du POC (CH-51) dans des ToolSpec
formels avec parameters_schema strict, preferred_when, evidence_type_returned.

Les 7 tools migrés depuis `reading_tools.py` :
- outline (navigation)
- read (reading)
- find_in (search)
- resolve_ref (search)
- expand_context (navigation)
- compare_sections (comparison)
- list_versions (lifecycle, downgrade experimental)

Restant à ajouter (S3.4 + S3.5 + S3.6) :
- navigate_by_toc, read_with_footnotes, find_cross_references (S3.4)
- find_quantitative, get_table, extract_numeric_evidence, compute_derived_metric (S3.5)
- compare_across_versions (S3.6)
- experimental_summarize_subtree (downgrade EXP)
"""
from __future__ import annotations

from typing import Optional

from knowbase.runtime_v5 import reading_tools
from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    ToolSpec,
)


# ─── ToolSpec definitions (7 POC tools + 2 EXP) ──────────────────────────────


def _outline_spec() -> ToolSpec:
    return ToolSpec(
        name="outline",
        category=ToolCategory.NAVIGATION,
        description=(
            "Returns the hierarchical table of contents of a document, "
            "with section_id, level, numbering, title, section_path and text size. "
            "Use this as the FIRST call to explore a doc structure."
        ),
        preferred_when="overview requested, first call to explore a doc",
        evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string", "description": "Document identifier"},
                "max_sections": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 80,
                },
                "min_text_chars": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Filter sections with less than N chars of text",
                },
            },
            "required": ["doc_id"],
        },
        handler=reading_tools.outline,
    )


def _read_spec() -> ToolSpec:
    return ToolSpec(
        name="read",
        category=ToolCategory.READING,
        description=(
            "Reads the full text of a section, identified by section_path "
            "(e.g. '/3/3.1') or numbering ('Article 5', '3.2', 'Annex I'). "
            "Returns title, section_path, full text, total chars."
        ),
        preferred_when="section_id known, content needed",
        evidence_type_returned=EvidenceType.FULL_SECTION_TEXT,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "section_path_or_numbering": {
                    "type": "string",
                    "description": "Path '/X/Y' OR numbering 'Article 5', '3.2.1', 'Annex I'",
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": 50000,
                    "default": 8000,
                },
            },
            "required": ["doc_id", "section_path_or_numbering"],
        },
        handler=reading_tools.read,
    )


def _find_in_spec() -> ToolSpec:
    return ToolSpec(
        name="find_in",
        category=ToolCategory.SEARCH,
        description=(
            "Searches a string or regex pattern within a document and returns "
            "matching sections with snippets around each hit. Case-insensitive."
        ),
        preferred_when="query non-specific, broad search inside a doc",
        evidence_type_returned=EvidenceType.SECTION_HITS,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "query": {"type": "string", "minLength": 1},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
                "snippet_chars": {
                    "type": "integer",
                    "minimum": 50,
                    "maximum": 2000,
                    "default": 400,
                },
            },
            "required": ["doc_id", "query"],
        },
        handler=reading_tools.find_in,
    )


def _resolve_ref_spec() -> ToolSpec:
    return ToolSpec(
        name="resolve_ref",
        category=ToolCategory.SEARCH,
        description=(
            "Resolves an internal reference like 'see Article 5(3)', 'cf section 3.2', "
            "'voir paragraphe 7'. Returns candidate sections that could match the reference. "
            "Use when text mentions a numbered cross-reference that needs disambiguation."
        ),
        preferred_when="ambiguous textual reference to resolve",
        evidence_type_returned=EvidenceType.CANDIDATE_SECTIONS,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "ref_text": {"type": "string", "minLength": 1},
                "current_section_id": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Section where the reference appears (context hint)",
                },
            },
            "required": ["doc_id", "ref_text"],
        },
        handler=reading_tools.resolve_ref,
    )


def _expand_context_spec() -> ToolSpec:
    return ToolSpec(
        name="expand_context",
        category=ToolCategory.NAVIGATION,
        description=(
            "Returns the parent, siblings, and children of a section to expand "
            "the hierarchical context around it. Useful for disambiguation when a "
            "section is too narrow or to understand its place in the document structure."
        ),
        preferred_when="contextual disambiguation needed around a section",
        evidence_type_returned=EvidenceType.PARENT_SIBLINGS_CHILDREN,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "section_id": {"type": "string"},
                "window": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 2,
                    "description": "How many siblings before/after to include",
                },
            },
            "required": ["doc_id", "section_id"],
        },
        handler=reading_tools.expand_context,
    )


def _compare_sections_spec() -> ToolSpec:
    return ToolSpec(
        name="compare_sections",
        category=ToolCategory.COMPARISON,
        description=(
            "Computes a unified line-by-line diff between two sections. "
            "Returns added/removed/unchanged lines. Use when two specific sections "
            "are named and a textual difference is needed."
        ),
        preferred_when="two named sections to compare textually",
        evidence_type_returned=EvidenceType.UNIFIED_DIFF,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id_a": {"type": "string"},
                "section_a": {"type": "string"},
                "doc_id_b": {"type": "string"},
                "section_b": {"type": "string"},
                "max_lines": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 500,
                    "default": 100,
                },
            },
            "required": ["doc_id_a", "section_a", "doc_id_b", "section_b"],
        },
        handler=reading_tools.compare_sections,
    )


def _list_versions_spec() -> ToolSpec:
    """list_versions est downgrade en experimental (ADR §3d, requires Domain Pack)."""
    return ToolSpec(
        name="experimental_list_versions",
        category=ToolCategory.LIFECYCLE,
        description=(
            "(EXPERIMENTAL) Lists versions of a document subject across tenant, "
            "based on KG LIFECYCLE_RELATION. Requires Domain Pack for subject normalization. "
            "Returns version relations chain."
        ),
        preferred_when="lifecycle history query, e.g. 'previous versions of X'",
        evidence_type_returned=EvidenceType.VERSION_RELATIONS,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_subject": {"type": "string"},
                "tenant_id": {"type": "string", "default": "default"},
            },
            "required": ["doc_subject"],
        },
        handler=reading_tools.list_versions,
        is_experimental=True,
    )


# ─── Registration helper ─────────────────────────────────────────────────────


def register_poc_tools(registry: ToolRegistry, *, allow_replace: bool = False) -> dict:
    """Enregistre les 6 tools POC publics + 1 experimental dans le registry.

    Args:
        registry: ToolRegistry cible
        allow_replace: si True, remplace les tools déjà enregistrés

    Returns:
        {"registered": [...], "errors": [...]}
    """
    specs = [
        _outline_spec(),
        _read_spec(),
        _find_in_spec(),
        _resolve_ref_spec(),
        _expand_context_spec(),
        _compare_sections_spec(),
        _list_versions_spec(),  # experimental
    ]
    registered = []
    errors = []
    for spec in specs:
        try:
            registry.register(spec, allow_replace=allow_replace)
            registered.append(spec.name)
        except Exception as e:
            errors.append({"name": spec.name, "error": str(e)})
    return {"registered": registered, "errors": errors}
