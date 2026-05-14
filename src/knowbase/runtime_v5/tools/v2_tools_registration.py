"""V5 Reading Tools — Enregistrement S3.4 (3 nouveaux tools).

CH-52.4.4 (Sprint S3.4) :
- navigate_by_toc : existence check + fuzzy suggestions
- read_with_footnotes : lecture + footnotes structurelles
- find_cross_references : extrait et résout les "see §X.Y" d'une section
"""
from __future__ import annotations

from knowbase.runtime_v5 import reading_tools_v2
from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    ToolSpec,
)


def _navigate_by_toc_spec() -> ToolSpec:
    return ToolSpec(
        name="navigate_by_toc",
        category=ToolCategory.NAVIGATION,
        description=(
            "Checks if a named section exists in a document (by numbering, "
            "section_path, or title substring). If not found, returns fuzzy "
            "suggestions of similar sections. Use this BEFORE assuming a section "
            "exists to avoid false_premise hallucinations."
        ),
        preferred_when="check section existence before answering false_premise risk",
        evidence_type_returned=EvidenceType.SECTION_EXISTS_CHECK,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "target": {
                    "type": "string",
                    "minLength": 1,
                    "description": "numbering '3.2' OR path '/3/3.2' OR title substring",
                },
                "max_suggestions": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                },
                "similarity_threshold": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.5,
                },
            },
            "required": ["doc_id", "target"],
        },
        handler=reading_tools_v2.navigate_by_toc,
    )


def _read_with_footnotes_spec() -> ToolSpec:
    return ToolSpec(
        name="read_with_footnotes",
        category=ToolCategory.READING,
        description=(
            "Reads a section's full text PLUS its structurally-detected footnotes "
            "(short child sections on the same page). Use when a section likely "
            "carries critical conditions, exceptions, or nuances in attached notes."
        ),
        preferred_when="critical conditions/exceptions/nuances expected",
        evidence_type_returned=EvidenceType.FULL_SECTION_WITH_FOOTNOTES,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "section_path_or_numbering": {
                    "type": "string",
                    "minLength": 1,
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": 50000,
                    "default": 8000,
                },
                "max_footnotes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
            "required": ["doc_id", "section_path_or_numbering"],
        },
        handler=reading_tools_v2.read_with_footnotes,
    )


def _find_cross_references_spec() -> ToolSpec:
    return ToolSpec(
        name="find_cross_references",
        category=ToolCategory.SEARCH,
        description=(
            "Extracts all internal cross-references ('see §X.Y', 'cf section N', "
            "'voir Annex I', '(3.2)') from a section, and resolves each to candidate "
            "target sections. Use to follow a chain of references inside a document."
        ),
        preferred_when="section contains references to follow ('see X.Y', 'cf §N')",
        evidence_type_returned=EvidenceType.LINKED_SECTIONS,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "section_id": {"type": "string"},
                "max_refs": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
                "max_candidates_per_ref": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 3,
                },
            },
            "required": ["doc_id", "section_id"],
        },
        handler=reading_tools_v2.find_cross_references,
    )


def register_v2_tools(registry: ToolRegistry, *, allow_replace: bool = False) -> dict:
    """Enregistre les 3 tools S3.4 dans le registry.

    Returns:
        {"registered": [...], "errors": [...]}
    """
    specs = [
        _navigate_by_toc_spec(),
        _read_with_footnotes_spec(),
        _find_cross_references_spec(),
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
