"""V5 Reading Tools — Registry + ToolSpec Pydantic.

ADR V1.5 §3d : 14 tools max dans le registry public + namespace `experimental_*`
pour les tools en cours d'évaluation. Chaque tool déclare :
- `name` : identifiant snake_case unique
- `category` : navigation | search | reading | quantitative | comparison
- `description` : doc-string passée au LLM (en anglais, domain-agnostic)
- `preferred_when` : courte chaîne expliquant le cas d'usage typique
- `evidence_type_returned` : enum (désambigue l'overlap sémantique)
- `parameters_schema` : JSON Schema strict (additionalProperties: false)
- `handler` : Callable Python qui exécute le tool

Pourquoi un registry formel :
- Le LLM choisit son outil parmi un set publié → réduire le "tool zoo"
- ToolCallSanitizer (S3.3) valide chaque appel contre `parameters_schema`
- Métriques par tool (selection_accuracy, evidence_gain) → gate retrait auto
- Plafond 14 = limite cognitive empirique pour DeepSeek-V3.1 / Claude / Llama

Domain-agnostic strict (charte) :
- Aucun nom de tool ne référence un domaine (pas de `find_amendment`, etc.)
- `description` reste universelle, le hint domain passe par Domain Pack
- `preferred_when` reste générique
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# ─── Enums (closed sets pour LLM tool calling robust) ────────────────────────


class ToolCategory(str, Enum):
    """Catégorie taxonomique d'un reading tool."""
    NAVIGATION = "navigation"
    SEARCH = "search"
    READING = "reading"
    QUANTITATIVE = "quantitative"
    COMPARISON = "comparison"
    SYNTHESIS = "synthesis"  # bounded deterministic (cf summarize_subtree)
    LIFECYCLE = "lifecycle"  # list_versions


class EvidenceType(str, Enum):
    """Type de preuve qu'un tool retourne — désambigue l'overlap sémantique.

    Notation : valeurs domain-agnostic. `numeric_match_with_unit` reste
    générique (s'applique à finance, médical, technique...). Pas de
    référence à un type métier.
    """
    STRUCTURE_INDEX = "structure_index"  # outline
    SECTION_EXISTS_CHECK = "section_exists_check"  # navigate_by_toc
    PARENT_SIBLINGS_CHILDREN = "parent_siblings_children"  # expand_context
    FULL_SECTION_TEXT = "full_section_text"  # read
    FULL_SECTION_WITH_FOOTNOTES = "full_section_with_footnotes"  # read_with_footnotes
    SECTION_HITS = "section_hits"  # find_in (hybrid BM25+dense+CR)
    CANDIDATE_SECTIONS = "candidate_sections"  # resolve_ref
    LINKED_SECTIONS = "linked_sections"  # find_cross_references
    NUMERIC_MATCH_WITH_UNIT = "numeric_match_with_unit"  # find_quantitative
    STRUCTURED_TABLE = "structured_table"  # get_table
    NORMALIZED_QUANTITY = "normalized_quantity"  # extract_numeric_evidence
    COMPUTED_VALUE = "computed_value"  # compute_derived_metric
    DIFF_STRUCT = "diff_struct"  # compare_across_versions
    UNIFIED_DIFF = "unified_diff"  # compare_sections
    BOUNDED_SUMMARY = "bounded_summary"  # summarize_subtree (EXP)
    VERSION_RELATIONS = "version_relations"  # list_versions (EXP)


# Plafond formel ADR V1.5 §3d
MAX_PUBLIC_TOOLS = 14
EXPERIMENTAL_NAMESPACE = "experimental_"


# ─── ToolSpec Pydantic ───────────────────────────────────────────────────────


class ToolSpec(BaseModel):
    """Spécification d'un reading tool.

    Domain-agnostic strict : aucun nom/exemple corpus-spécifique.
    Tout hint métier passe par Domain Pack (post-S3, hors scope ici).
    """
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=False,  # On peut update metrics/retirement à runtime
    )

    name: str = Field(..., description="snake_case unique tool name")
    category: ToolCategory
    description: str = Field(..., min_length=10, description="LLM-facing tool description (en, domain-agnostic)")
    preferred_when: str = Field(..., min_length=5, description="Cas d'usage typique (1 phrase)")
    evidence_type_returned: EvidenceType
    parameters_schema: dict[str, Any] = Field(
        ..., description="JSON Schema strict (additionalProperties: false)"
    )
    handler: Optional[Callable[..., Any]] = Field(
        default=None, description="Fonction Python exécutant le tool"
    )
    is_experimental: bool = False
    is_retired: bool = False
    retired_reason: str = ""

    # Métriques offline (mises à jour par observability)
    selection_accuracy: Optional[float] = Field(
        default=None, description="% selections correctes sur 4-semaines glissantes"
    )
    evidence_gain_avg: Optional[float] = Field(
        default=None, description="evidence gain moyen par appel"
    )
    n_calls_total: int = 0

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.replace("_", "").isalnum():
            raise ValueError(f"tool name must be snake_case alphanumeric: '{v}'")
        return v

    @field_validator("parameters_schema")
    @classmethod
    def _validate_schema(cls, v: dict) -> dict:
        # Doit être un JSON Schema avec additionalProperties: false (strict mode)
        if v.get("type") != "object":
            raise ValueError("parameters_schema must have type: 'object'")
        if v.get("additionalProperties") is not False:
            raise ValueError(
                "parameters_schema must have additionalProperties: false (strict)"
            )
        return v

    def to_llm_schema(self) -> dict:
        """Représentation JSON pour LLM tool calling.

        Format compatible OpenAI / Anthropic / DeepSeek tool use.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    f"{self.description.strip()} "
                    f"(Preferred when: {self.preferred_when.strip()}; "
                    f"returns evidence type: {self.evidence_type_returned.value})"
                ),
                "parameters": self.parameters_schema,
            },
        }


# ─── ToolRegistry ────────────────────────────────────────────────────────────


class ToolRegistryError(Exception):
    pass


class ToolRegistry:
    """Registry centralisé des reading tools V5.

    Thread-safe (lock léger). Maintient :
    - `public_tools` : <=14 tools exposés au LLM par défaut
    - `experimental_tools` : tools en cours d'évaluation (préfixe namespace)
    - `retired_tools` : tools désactivés (gate auto ou manuel)

    Gate retrait automatique : si `selection_accuracy < min_accuracy_threshold`
    après `min_calls_for_gate` appels, le tool est retiré (logged + métrique OTel).
    """

    DEFAULT_MIN_ACCURACY = 0.90  # ADR V1.5 §3d : 90%
    DEFAULT_MIN_CALLS = 100  # n minimum avant gate auto

    def __init__(
        self,
        min_accuracy_threshold: float = DEFAULT_MIN_ACCURACY,
        min_calls_for_gate: int = DEFAULT_MIN_CALLS,
    ):
        self._tools: dict[str, ToolSpec] = {}
        self._lock = threading.RLock()
        self.min_accuracy = min_accuracy_threshold
        self.min_calls = min_calls_for_gate
        # Confusion matrix : (tool_name → {alt_tool: count}) — pour audit
        self._confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # ─── Register / Unregister ───────────────────────────────────────────────

    def register(self, spec: ToolSpec, *, allow_replace: bool = False) -> None:
        """Ajoute un tool au registry.

        Args:
            spec: ToolSpec
            allow_replace: si False (default), refuse de remplacer un tool existant

        Raises:
            ToolRegistryError si plafond MAX_PUBLIC_TOOLS atteint ou name conflict
        """
        with self._lock:
            if not allow_replace and spec.name in self._tools:
                raise ToolRegistryError(f"Tool '{spec.name}' already registered")

            # Si non-experimental, vérifier plafond
            if not spec.is_experimental:
                n_public_active = sum(
                    1 for t in self._tools.values()
                    if not t.is_experimental and not t.is_retired and t.name != spec.name
                )
                if n_public_active >= MAX_PUBLIC_TOOLS:
                    raise ToolRegistryError(
                        f"Public tools ceiling {MAX_PUBLIC_TOOLS} reached. "
                        f"Either retire a tool or register as experimental "
                        f"(prefix name with '{EXPERIMENTAL_NAMESPACE}')."
                    )
                # Auto-namespace check : experimental_* tools must have is_experimental=True
                if spec.name.startswith(EXPERIMENTAL_NAMESPACE):
                    raise ToolRegistryError(
                        f"Tool '{spec.name}' starts with '{EXPERIMENTAL_NAMESPACE}' "
                        f"but is_experimental=False"
                    )

            self._tools[spec.name] = spec
            logger.info(
                f"[ToolRegistry] Registered '{spec.name}' (category={spec.category.value}, "
                f"experimental={spec.is_experimental})"
            )

    def unregister(self, name: str) -> bool:
        """Supprime un tool du registry."""
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info(f"[ToolRegistry] Unregistered '{name}'")
                return True
            return False

    def retire(self, name: str, reason: str = "") -> bool:
        """Marque un tool comme retired sans le supprimer (audit trail).

        Le tool n'est plus exposé via `list_public_tools()` mais reste en
        registre pour métrique historique.
        """
        with self._lock:
            if name not in self._tools:
                return False
            self._tools[name].is_retired = True
            self._tools[name].retired_reason = reason or "manual_retirement"
            logger.warning(f"[ToolRegistry] Retired '{name}' — {reason}")
            return True

    # ─── Lookup ──────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ToolSpec]:
        with self._lock:
            return self._tools.get(name)

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def list_public_tools(self, *, include_experimental: bool = False) -> list[ToolSpec]:
        """Liste les tools exposés au LLM (non-retired, public + optionnel experimental)."""
        with self._lock:
            return [
                t for t in self._tools.values()
                if not t.is_retired
                and (include_experimental or not t.is_experimental)
            ]

    def list_all(self) -> list[ToolSpec]:
        with self._lock:
            return list(self._tools.values())

    def to_llm_tools(self, *, include_experimental: bool = False) -> list[dict]:
        """Sérialise les tools actifs au format LLM (OpenAI/Anthropic tool calling).

        Use case : `tools=registry.to_llm_tools()` lors d'un call LLM.
        """
        return [t.to_llm_schema() for t in self.list_public_tools(
            include_experimental=include_experimental
        )]

    # ─── Metrics & gate auto-retirement ──────────────────────────────────────

    def record_call(
        self,
        name: str,
        was_correct_selection: Optional[bool] = None,
        evidence_gain: Optional[float] = None,
        confused_with: Optional[str] = None,
    ) -> None:
        """Enregistre un appel pour métriques.

        Args:
            name: tool appelé
            was_correct_selection: True si le tool était le bon choix (offline labeling)
            evidence_gain: score d'information apporté (0-1)
            confused_with: si erroné, le tool qui aurait été correct (confusion matrix)
        """
        with self._lock:
            tool = self._tools.get(name)
            if tool is None:
                return
            tool.n_calls_total += 1

            # Mise à jour rolling moyenne (simple incremental)
            if was_correct_selection is not None:
                prev = tool.selection_accuracy or 0.0
                n = tool.n_calls_total
                accuracy_val = 1.0 if was_correct_selection else 0.0
                # EWMA simple : (1-alpha)*prev + alpha*new, alpha=1/n (decay slow)
                alpha = 1.0 / max(n, 1)
                tool.selection_accuracy = (1 - alpha) * prev + alpha * accuracy_val

            if evidence_gain is not None:
                prev = tool.evidence_gain_avg or 0.0
                n = tool.n_calls_total
                alpha = 1.0 / max(n, 1)
                tool.evidence_gain_avg = (1 - alpha) * prev + alpha * evidence_gain

            if confused_with and not was_correct_selection:
                self._confusion[name][confused_with] += 1

            # Gate auto-retirement check
            self._maybe_auto_retire(name)

    def _maybe_auto_retire(self, name: str) -> None:
        tool = self._tools.get(name)
        if not tool or tool.is_retired or tool.is_experimental:
            return
        if (
            tool.n_calls_total >= self.min_calls
            and tool.selection_accuracy is not None
            and tool.selection_accuracy < self.min_accuracy
        ):
            tool.is_retired = True
            tool.retired_reason = (
                f"auto_gate_retirement: selection_accuracy={tool.selection_accuracy:.2%} "
                f"< threshold={self.min_accuracy:.2%} after {tool.n_calls_total} calls"
            )
            logger.warning(
                f"[ToolRegistry] AUTO-RETIRED '{name}' — {tool.retired_reason}"
            )

    def get_confusion_matrix(self, name: str) -> dict[str, int]:
        """Retourne le mapping {tool_correct: count} pour les calls erronés sur `name`."""
        with self._lock:
            return dict(self._confusion.get(name, {}))

    # ─── Stats ───────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Stats globales du registry."""
        with self._lock:
            public = self.list_public_tools(include_experimental=False)
            experimental = [t for t in self._tools.values()
                            if t.is_experimental and not t.is_retired]
            retired = [t for t in self._tools.values() if t.is_retired]
            return {
                "n_public": len(public),
                "n_experimental": len(experimental),
                "n_retired": len(retired),
                "public_tools": [t.name for t in public],
                "experimental_tools": [t.name for t in experimental],
                "retired_tools": {t.name: t.retired_reason for t in retired},
                "ceiling": MAX_PUBLIC_TOOLS,
                "slots_available": MAX_PUBLIC_TOOLS - len(public),
            }


# ─── Singleton factory ───────────────────────────────────────────────────────

_default_registry: Optional[ToolRegistry] = None
_default_lock = threading.RLock()


def get_default_registry() -> ToolRegistry:
    """Singleton du registry V5 (chargé avec les 14 tools en S3.2-S3.6)."""
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = ToolRegistry()
        return _default_registry


def reset_default_registry() -> None:
    """Reset singleton (utile pour tests)."""
    global _default_registry
    with _default_lock:
        _default_registry = None
