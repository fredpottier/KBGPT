"""Schémas Pydantic versionnés du runtime A3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1 + §2.4 + §2.5.

Versioning : tous les schémas exposent `schema_version: str = "a3.0"`. Migration future
via discriminated unions Pydantic V2.

Note A3.1 : ce fichier ne contient pour l'instant que les schémas Parse. Les schémas
Plan / Execute / Evaluate / Synthesize seront ajoutés dans les tasks suivantes (A3.2-A3.5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Parse (LLM #1) — Décomposition question → sub-goals
# ============================================================================


# Types de sub-goals supportés (cf ADR §2.1)
SubGoalKind = Literal[
    "fact_lookup",          # "X.predicate = ?"
    "list_enumeration",     # "tous les X tels que ..."
    "comparison",           # "X vs Y sur predicate Z"
    "lifecycle_trace",      # "évolution de X au fil du temps"
    "contradiction_check",  # "y a-t-il des contradictions sur X.predicate ?"
    "definition_lookup",    # "qu'est-ce que X ?"
]

# Kinds de valeur attendue par un sub-goal (pour aider Execute / sanity check)
ExpectedValueKind = Literal[
    "percent",
    "version",
    "number",
    "string",
    "date",
    "boolean",
]

# Filtres temporels
TimeFilter = Literal[
    "as_of",      # point-in-time historique
    "current",    # ce qui est vrai maintenant (défaut)
    "evolution",  # trace des changements
]

# Langues détectées
Language = Literal["fr", "en", "de", "es", "other"]


class SubGoal(BaseModel):
    """Un objectif concret extractable du KG, mappable à un tool unique (cf ADR §2.1).

    Le LLM Parse produit une liste de SubGoal au lieu de classer la question dans un
    bucket figé. Decomposition > Classification.
    """

    model_config = ConfigDict(extra="forbid")

    kind: SubGoalKind = Field(
        description="Type de sub-goal (détermine le tool en Plan)",
    )
    subject_canonical: Optional[str] = Field(
        default=None,
        description=(
            "Entité focus du sub-goal. Peut être None si trop large pour être nommée. "
            "Execute fera une re-évaluation via index canonical entities (LLM peut "
            "halluciner, sanity check en aval)."
        ),
    )
    predicate_hint: Optional[str] = Field(
        default=None,
        description="Verbe ou relation visée (ex: 'uses', 'released_at'). None si vague.",
    )
    object_hint: Optional[str] = Field(
        default=None,
        description="Valeur attendue ou pattern (ex: 'version', 'date').",
    )
    expected_value_kind: Optional[ExpectedValueKind] = Field(
        default=None,
        description="Kind de valeur attendue (helps Execute sanity-check + Synthesize formatting).",
    )
    time_filter: TimeFilter = Field(
        default="current",
        description="Filtre temporel (cf ADR §2.1).",
    )
    priority: int = Field(
        default=1,
        ge=1,
        le=2,
        description="1 = essentiel (sub_goal central), 2 = enrichissement (sub_goal secondaire).",
    )


class ParseInput(BaseModel):
    """Input du module Parse."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        ...,
        description="Texte brut de la question utilisateur.",
        min_length=1,
    )
    tenant_id: str = Field(
        ...,
        description="Tenant ID multi-tenant.",
        min_length=1,
    )
    language_hint: Optional[Language] = Field(
        default=None,
        description="Hint langue si connu (sinon auto-detect par Parse).",
    )
    as_of_date: Optional[datetime] = Field(
        default=None,
        description="Date point-in-time pour queries historiques (sinon now()).",
    )


class ParseOutput(BaseModel):
    """Output structuré du Parse (cf ADR §2.1).

    Schema_version permet migrations futures via discriminated unions.
    """

    model_config = ConfigDict(extra="forbid")

    sub_goals: List[SubGoal] = Field(
        ...,
        description="Liste de sub-goals concrets. Max 5 (cf §2.9 hard caps).",
        max_length=5,
    )
    entities: List[str] = Field(
        default_factory=list,
        description="Entités canonical détectées dans la question (helpers pour Plan).",
    )
    language: Language = Field(
        ...,
        description="Langue détectée de la question.",
    )
    raw_question: str = Field(
        ...,
        description="Echo de la question originale.",
    )
    parse_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Score d'auto-évaluation du Parse. "
            "Si < 0.5, Evaluate prioritise INSUFFICIENT (saut Plan/Execute inutile)."
        ),
    )
    parse_warnings: List[str] = Field(
        default_factory=list,
        description=(
            "Warnings émis par Parse "
            "(ex: 'ambiguous subject', 'out_of_scope_for_corpus', 'question_truncated')."
        ),
    )
    schema_version: str = Field(
        default="a3.0",
        description="Version du schéma pour discriminated unions futures.",
    )


# ============================================================================
# Plan (déterministe) — Mapping sub_goal → tool
# ============================================================================


# Tools disponibles (cf ADR §2.2 + §4)
ToolName = Literal[
    "kg_claims",                # fact_lookup, definition_lookup
    "kg_claims_list",           # list_enumeration
    "lifecycle_query",          # lifecycle_trace
    "contradiction_surface",    # contradiction_check
    "comparison_query",         # comparison (composé)
    "qdrant_sections",          # fallback / enrichissement vectoriel
]


class ToolCall(BaseModel):
    """Une invocation de tool prévue par Plan (cf ADR §2.2).

    100% déterministe — pas de LLM dans Plan. Le mapping sub_goal.kind → tool
    est une table de correspondance (cf plan.py).
    """

    model_config = ConfigDict(extra="forbid")

    sub_goal_idx: int = Field(
        ...,
        ge=0,
        description="Index du sub_goal dans ParseOutput.sub_goals.",
    )
    tool: ToolName = Field(
        ...,
        description="Tool à invoquer (cf ADR §4).",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Paramètres Cypher / Qdrant (subject, predicate, as_of, tenant_id, ...).",
    )
    depends_on: List[int] = Field(
        default_factory=list,
        description="Indices d'autres ToolCall qui doivent finir avant celui-ci.",
    )
    timeout_s: float = Field(
        default=15.0,
        gt=0.0,
        le=60.0,
        description="Timeout en secondes (cf §2.9 hard caps).",
    )


class PlanOutput(BaseModel):
    """Output structuré du Plan (cf ADR §2.2)."""

    model_config = ConfigDict(extra="forbid")

    tool_calls: List[ToolCall] = Field(
        default_factory=list,
        description="Liste des invocations de tools planifiées.",
    )
    unmappable_sub_goals: List[int] = Field(
        default_factory=list,
        description=(
            "Indices des sub_goals qui n'ont pas pu être mappés à un tool "
            "(Evaluate décidera fallback Qdrant ou abstention)."
        ),
    )
    plan_warnings: List[str] = Field(
        default_factory=list,
        description="Warnings émis par Plan (ex: missing_subject_for_kg_claims).",
    )
    schema_version: str = Field(
        default="a3.0",
        description="Version du schéma pour discriminated unions futures.",
    )


# ============================================================================
# Execute — Résultats agrégés par tool call
# ============================================================================


CoverageSignal = Literal["full", "partial", "empty"]


class ClaimSummary(BaseModel):
    """Vue compacte d'un :Claim Neo4j (cf ADR_BITEMPOREL §4)."""

    model_config = ConfigDict(extra="allow")  # tolère champs additionnels du KG

    claim_id: str
    subject_canonical: Optional[str] = None
    predicate: Optional[str] = None
    value: Optional[str] = None
    value_normalized: Optional[str] = None
    confidence: Optional[float] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    ingested_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    marker_type: Optional[str] = None  # explicit / inferred / prudence
    source_doc_id: Optional[str] = None


class SectionSummary(BaseModel):
    """Vue compacte d'une :Section ou chunk Qdrant pour citation cliquable."""

    model_config = ConfigDict(extra="allow")

    section_id: str
    document_id: Optional[str] = None
    heading: Optional[str] = None
    text_excerpt: Optional[str] = None  # tronqué pour ne pas inflate l'output
    score: Optional[float] = None        # score retrieval (Qdrant uniquement)


class ConflictPendingSummary(BaseModel):
    """Vue compacte d'un :ConflictPending node (cf ADR_RELATIONS_CLAIM_CLAIM §2.6)."""

    model_config = ConfigDict(extra="allow")

    conflict_id: str
    resolution_status: str = "unresolved"
    involved_claim_ids: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class RelationSummary(BaseModel):
    """Vue compacte d'une relation claim-vs-claim (cf ADR_RELATIONS_CLAIM_CLAIM)."""

    model_config = ConfigDict(extra="allow")

    relation_type: str  # EVOLUTION_OF | SUPERSEDES | CONTRADICTS | REFINES | QUALIFIES
    from_claim_id: str
    to_claim_id: str
    confidence: Optional[float] = None
    detected_at: Optional[datetime] = None


class ToolResult(BaseModel):
    """Résultat d'un ToolCall (cf ADR §2.3)."""

    model_config = ConfigDict(extra="forbid")

    sub_goal_idx: int = Field(..., ge=0)
    tool: ToolName
    claims: List[ClaimSummary] = Field(default_factory=list)
    sections: List[SectionSummary] = Field(default_factory=list)
    conflict_pendings: List[ConflictPendingSummary] = Field(default_factory=list)
    relations_traced: List[RelationSummary] = Field(default_factory=list)
    coverage_signal: CoverageSignal = "empty"
    duration_s: float = Field(default=0.0, ge=0.0)
    error: Optional[str] = None


class ExecuteOutput(BaseModel):
    """Output structuré de l'Execute (cf ADR §2.3)."""

    model_config = ConfigDict(extra="forbid")

    results: List[ToolResult] = Field(default_factory=list)
    total_duration_s: float = Field(default=0.0, ge=0.0)
    schema_version: str = "a3.0"


# ============================================================================
# Evaluate (LLM #2) — Verdict 4-classes + re_plan_hint contrôlé
# ============================================================================


Verdict = Literal[
    "CORRECT",                # tous sub_goals couverts par evidence
    "AMBIGUOUS",              # couverture partielle ou conflits — re-plan possible
    "INCORRECT",              # evidence contradictoire / non-pertinente
    "INSUFFICIENT_EVIDENCE",  # tools retournent rien → abstention motivée
]


RePlanHint = Literal[
    "broaden_subject",
    "add_qdrant_fallback",
    "decompose_comparison",
    "check_lifecycle",
    "narrow_time_filter",
    "drop_overspecific_filters",
    "none",
]


class EvaluateInput(BaseModel):
    """Input du module Evaluate (cf ADR §2.4)."""

    model_config = ConfigDict(extra="forbid")

    parse_output: "ParseOutput"
    plan_output: "PlanOutput"
    execute_output: "ExecuteOutput"
    iteration: int = Field(
        default=0,
        ge=0,
        le=2,
        description="0 = 1er pass, 1 = re-plan (limite hard cap §2.9)",
    )


class EvaluateOutput(BaseModel):
    """Output structuré de l'Evaluate (cf ADR §2.4)."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict = Field(..., description="Verdict 4-classes.")
    covered_sub_goals: List[int] = Field(default_factory=list)
    uncovered_sub_goals: List[int] = Field(default_factory=list)
    re_plan_hint: RePlanHint = Field(default="none")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(
        default="",
        max_length=600,
        description="Courte explication (40-80 mots cible, 600 chars max).",
    )
    schema_version: str = Field(default="a3.0")


# ============================================================================
# Exceptions
# ============================================================================


class ParseError(Exception):
    """Erreur générique du module Parse."""

    pass


class ParseValidationError(ParseError):
    """LLM output ne valide pas le schéma Pydantic même après retry."""

    pass


class ParseTimeoutError(ParseError):
    """LLM Parse a timeout."""

    pass


class PlanError(Exception):
    """Erreur générique du module Plan."""

    pass


class ExecuteError(Exception):
    """Erreur générique du module Execute."""

    pass


class EvaluateError(Exception):
    """Erreur générique du module Evaluate."""

    pass


# Forward refs (EvaluateInput nest ParseOutput/PlanOutput/ExecuteOutput)
EvaluateInput.model_rebuild()
