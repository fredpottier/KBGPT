"""V5 Reading Tools — Specs des 5 tools quantitatifs (S3.5 mini-POC prep).

⚠️ SPECS UNIQUEMENT — handlers à implémenter en S3.5 si gate ADR ≥15pp passe.

ADR V1.5 §3d : 5 tools spécialisés pour combler le gap quantitatif (0.57 vs 0.83 EKX) :
- find_quantitative : cherche numérique + unité (domain-agnostic) dans le corpus
- get_table : accès colonnes/lignes spécifiques d'une table
- extract_numeric_evidence : extraction quantités normalisées (entity, unit, time, span)
- compute_derived_metric : delta, %, ratio sur evidence cited
- resolve_unit_or_alias : normalize unités/synonymes (GB↔Gigabyte, % ↔ percent)

Tous domain-agnostic : les patterns sont universels (nombre + unité), pas de
liste métier (pas de RTO/RPO/SLA hardcodé). Le Domain Pack peut enrichir avec
des aliases métier sans toucher au core.

Mini-POC obligatoire avant industrialisation (ADR §3d Gate dur) :
- 10 questions quantitatives échouées par V5 POC
- Mesurer V5 + ces 5 tools vs V5 POC sans tools quantitatifs
- Gate : gain ≥ 15pp sinon revoir extraction tables avant industrialisation
"""
from __future__ import annotations

from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolSpec,
)


def _not_implemented_handler(*args, **kwargs) -> dict:
    """Placeholder : retourne erreur si handler appelé avant impl S3.5."""
    return {
        "error": "Tool not implemented yet (S3.5 mini-POC prep, awaiting gate ADR ≥15pp)",
        "status": "spec_only",
    }


# ─── Spec 1 : find_quantitative ──────────────────────────────────────────────


def find_quantitative_spec() -> ToolSpec:
    return ToolSpec(
        name="find_quantitative",
        category=ToolCategory.QUANTITATIVE,
        description=(
            "Searches for numeric values with units in a document (e.g. '500 GB', "
            "'4 hours', '15%', '2 minutes'). Returns sections containing matches "
            "with the captured numeric+unit pair. Use for 'how much', 'what rate', "
            "'how long' style questions. Universal patterns (number + unit), not "
            "tied to any domain vocabulary."
        ),
        preferred_when="quantitative question ('how much', 'what rate', value with unit)",
        evidence_type_returned=EvidenceType.NUMERIC_MATCH_WITH_UNIT,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "topic_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                    "description": "Optional keywords to narrow search (e.g. 'recovery', 'storage')",
                },
                "unit_hint": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Optional unit class hint ('time', 'size', 'percent', 'currency')",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
            "required": ["doc_id", "topic_keywords"],
        },
        handler=_not_implemented_handler,
    )


# ─── Spec 2 : get_table ──────────────────────────────────────────────────────


def get_table_spec() -> ToolSpec:
    return ToolSpec(
        name="get_table",
        category=ToolCategory.QUANTITATIVE,
        description=(
            "Retrieves a structured table from a document, optionally filtered by "
            "column or row criteria. Returns headers + rows as JSON-friendly structure. "
            "Use when the answer requires lookup in a tabular structure."
        ),
        preferred_when="answer requires lookup in a table (column×row)",
        evidence_type_returned=EvidenceType.STRUCTURED_TABLE,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "table_ref": {
                    "type": "string",
                    "description": "Table caption substring, table_id, or section_id where the table appears",
                },
                "filter_column": {
                    "type": ["string", "null"],
                    "default": None,
                },
                "filter_value": {
                    "type": ["string", "null"],
                    "default": None,
                },
                "max_rows": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50,
                },
            },
            "required": ["doc_id", "table_ref"],
        },
        handler=_not_implemented_handler,
    )


# ─── Spec 3 : extract_numeric_evidence ───────────────────────────────────────


def extract_numeric_evidence_spec() -> ToolSpec:
    return ToolSpec(
        name="extract_numeric_evidence",
        category=ToolCategory.QUANTITATIVE,
        description=(
            "Extracts normalized quantitative evidence from a text snippet : "
            "{value, unit, entity, time_context, comparator (e.g. '<', '>=', '~'), "
            "confidence, source_span}. Use after locating relevant sections to "
            "structure the numeric facts before composition."
        ),
        preferred_when="need to structure raw numeric facts from text snippet",
        evidence_type_returned=EvidenceType.NORMALIZED_QUANTITY,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Text snippet to analyze",
                },
                "doc_id_context": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Doc for unit alias context (optional)",
                },
                "entity_hint": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Entity the quantities relate to (e.g. 'recovery time')",
                },
            },
            "required": ["text"],
        },
        handler=_not_implemented_handler,
    )


# ─── Spec 4 : compute_derived_metric ─────────────────────────────────────────


def compute_derived_metric_spec() -> ToolSpec:
    return ToolSpec(
        name="compute_derived_metric",
        category=ToolCategory.QUANTITATIVE,
        description=(
            "Computes a derived metric from cited evidence : delta, percent_change, "
            "ratio, min, max, sum, avg. Requires the evidence span list (each with "
            "value+unit) so the computation is auditable and grounded. Returns "
            "{result, formula, evidence_used}."
        ),
        preferred_when="answer requires comparison/computation on cited quantities",
        evidence_type_returned=EvidenceType.COMPUTED_VALUE,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["delta", "percent_change", "ratio", "min", "max", "sum", "avg"],
                },
                "evidence": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "value": {"type": "number"},
                            "unit": {"type": "string"},
                            "source_span": {"type": "string"},
                        },
                        "required": ["value", "unit"],
                    },
                },
            },
            "required": ["operation", "evidence"],
        },
        handler=_not_implemented_handler,
    )


# ─── Spec 5 : resolve_unit_or_alias ──────────────────────────────────────────


def resolve_unit_or_alias_spec() -> ToolSpec:
    return ToolSpec(
        name="resolve_unit_or_alias",
        category=ToolCategory.QUANTITATIVE,
        description=(
            "Normalizes a unit string or quantitative term to its canonical form. "
            "Handles common synonyms (GB ↔ Gigabyte, % ↔ percent, hr ↔ hour). "
            "Uses Domain Pack aliases if available. Use BEFORE extract_numeric_evidence "
            "to homogenize unit comparisons across evidence pieces."
        ),
        preferred_when="unit synonyms expected (GB/Gigabyte, hr/hour, % /percent)",
        evidence_type_returned=EvidenceType.NORMALIZED_QUANTITY,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "raw": {
                    "type": "string",
                    "minLength": 1,
                },
                "domain_pack": {
                    "type": ["string", "null"],
                    "default": None,
                    "description": "Domain Pack name for aliases (e.g. 'storage', 'time')",
                },
            },
            "required": ["raw"],
        },
        handler=_not_implemented_handler,
    )


# ─── Registration helper (specs only, no exec yet) ───────────────────────────


def list_quantitative_specs() -> list[ToolSpec]:
    """Liste les 5 specs quantitatives (sans les enregistrer)."""
    return [
        find_quantitative_spec(),
        get_table_spec(),
        extract_numeric_evidence_spec(),
        compute_derived_metric_spec(),
        resolve_unit_or_alias_spec(),
    ]
