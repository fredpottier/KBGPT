"""Schémas Pydantic versionnés du runtime A3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1 + §2.4 + §2.5.

Versioning : tous les schémas exposent `schema_version: str = "a3.0"`. Migration future
via discriminated unions Pydantic V2.

Note A3.1 : ce fichier ne contient pour l'instant que les schémas Parse. Les schémas
Plan / Execute / Evaluate / Synthesize seront ajoutés dans les tasks suivantes (A3.2-A3.5).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

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
