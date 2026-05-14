"""V5 Reading Tools — ToolCallSanitizer (validation + reparation).

ADR V1.5 §3d — CH-52.4.3 (S3.3).

Le LLM (DeepSeek-V3.1 notamment) ignore parfois `additionalProperties: false`
(1-3% des cas selon Sonnet). On ne fait pas confiance au LLM : on valide et
on REPARE les tool calls AVANT exécution.

Étapes :
1. **Resolve** : lookup du ToolSpec par name. Si tool inconnu OU retired → erreur.
2. **Sanitize args** :
   a. Strip clés non-déclarées (additionalProperties drift)
   b. Coerce types simples (int as str, bool as "true"/"false")
   c. Drop None pour params optionnels (libère les defaults)
3. **Validate** : valide finalement contre `parameters_schema` JSON Schema
4. **Repair-or-fail** : si validation échoue après sanitize, retourne ToolCallError

Métriques émises (à brancher OTel en S6) :
- `tool_call_repair_rate` : % calls avec au moins 1 réparation
- `tool_call_validation_error_rate` : % calls qui restent invalides après sanitize
- `tool_call_unknown_tool_rate` : % calls vers un tool inconnu

Domain-agnostic strict : aucune heuristique métier dans le sanitizer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

from knowbase.runtime_v5.tools.registry import ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class SanitizationReport:
    """Détail de ce qui a été modifié pendant la sanitization (audit)."""
    stripped_extra_keys: list[str] = field(default_factory=list)
    coerced_types: list[dict] = field(default_factory=list)
    dropped_none_keys: list[str] = field(default_factory=list)

    def has_repairs(self) -> bool:
        return bool(
            self.stripped_extra_keys
            or self.coerced_types
            or self.dropped_none_keys
        )

    def to_dict(self) -> dict:
        return {
            "stripped_extra_keys": list(self.stripped_extra_keys),
            "coerced_types": list(self.coerced_types),
            "dropped_none_keys": list(self.dropped_none_keys),
            "any_repair": self.has_repairs(),
        }


@dataclass
class SanitizedCall:
    """Résultat d'une sanitization réussie : prête à exécuter."""
    spec: ToolSpec
    args: dict[str, Any]
    report: SanitizationReport


class ToolCallError(Exception):
    """Sanitization a échoué (tool inconnu, validation impossible, retired tool, etc.)."""
    def __init__(self, message: str, error_type: str = "validation_error",
                 details: Optional[dict] = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


# ─── Coercion helpers (universal, no domain logic) ──────────────────────────


def _try_coerce(value: Any, target_type: str) -> tuple[Any, bool]:
    """Tente une coercion sûre vers `target_type`.

    Returns:
        (new_value, was_coerced)
    """
    if target_type == "string":
        if isinstance(value, str):
            return value, False
        if value is None:
            return value, False
        return str(value), True
    if target_type == "integer":
        if isinstance(value, bool):
            return value, False  # bool est subclass int en Python — ne coerce pas
        if isinstance(value, int):
            return value, False
        if isinstance(value, float) and value.is_integer():
            return int(value), True
        if isinstance(value, str):
            try:
                return int(value.strip()), True
            except (ValueError, AttributeError):
                return value, False
        return value, False
    if target_type == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value, False
        if isinstance(value, str):
            try:
                return float(value.strip()), True
            except (ValueError, AttributeError):
                return value, False
        return value, False
    if target_type == "boolean":
        if isinstance(value, bool):
            return value, False
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "yes", "1"):
                return True, True
            if v in ("false", "no", "0"):
                return False, True
        if isinstance(value, int) and not isinstance(value, bool):
            if value in (0, 1):
                return bool(value), True
        return value, False
    # array, object : pas de coercion automatique
    return value, False


# ─── ToolCallSanitizer ───────────────────────────────────────────────────────


class ToolCallSanitizer:
    """Valide et répare les tool calls LLM contre le ToolRegistry.

    Args:
        registry: ToolRegistry source de vérité
        strict_unknown_tools: si True (default), lève ToolCallError sur tool
                              inconnu. Si False, retourne None silencieusement.
    """

    def __init__(self, registry: ToolRegistry, strict_unknown_tools: bool = True):
        self.registry = registry
        self.strict_unknown_tools = strict_unknown_tools
        self._n_total = 0
        self._n_repaired = 0
        self._n_invalid = 0
        self._n_unknown = 0

    def sanitize(self, tool_name: str, args: Any) -> SanitizedCall:
        """Valide + répare un tool call.

        Args:
            tool_name: nom du tool appelé par le LLM
            args: dict d'arguments (ou tout autre type pour bug detection)

        Returns:
            SanitizedCall avec spec + args nettoyés + report

        Raises:
            ToolCallError si tool inconnu, retired, ou validation impossible
        """
        self._n_total += 1

        # 1. Resolve tool
        spec = self.registry.get(tool_name)
        if spec is None:
            self._n_unknown += 1
            msg = f"Unknown tool: '{tool_name}'"
            logger.warning(f"[ToolCallSanitizer] {msg}")
            if self.strict_unknown_tools:
                raise ToolCallError(msg, error_type="unknown_tool",
                                    details={"tool_name": tool_name})
            raise ToolCallError(msg, error_type="unknown_tool")

        if spec.is_retired:
            msg = f"Tool '{tool_name}' is retired: {spec.retired_reason}"
            logger.warning(f"[ToolCallSanitizer] {msg}")
            raise ToolCallError(msg, error_type="retired_tool",
                                details={"reason": spec.retired_reason})

        # 2. Args must be dict-like
        if args is None:
            args = {}
        if not isinstance(args, dict):
            self._n_invalid += 1
            raise ToolCallError(
                f"Tool '{tool_name}' args must be dict, got {type(args).__name__}",
                error_type="args_not_dict",
            )

        # 3. Sanitize : strip extra, coerce types, drop None for optional
        sanitized_args, report = self._sanitize_args(spec, args)

        # 4. Validate against JSON Schema
        if _HAS_JSONSCHEMA:
            try:
                jsonschema.validate(instance=sanitized_args,
                                    schema=spec.parameters_schema)
            except jsonschema.ValidationError as e:
                self._n_invalid += 1
                raise ToolCallError(
                    f"Tool '{tool_name}' args invalid after sanitization: {e.message}",
                    error_type="schema_validation_failed",
                    details={"validator_path": list(e.absolute_path), "validation_error": e.message},
                ) from e
        else:
            # Fallback minimal validation : required check uniquement
            self._minimal_validate(spec, sanitized_args, tool_name)

        if report.has_repairs():
            self._n_repaired += 1
            logger.info(
                f"[ToolCallSanitizer] Repaired '{tool_name}': "
                f"{report.to_dict()}"
            )

        return SanitizedCall(spec=spec, args=sanitized_args, report=report)

    def _sanitize_args(
        self, spec: ToolSpec, args: dict
    ) -> tuple[dict, SanitizationReport]:
        report = SanitizationReport()
        schema = spec.parameters_schema
        declared_props = schema.get("properties", {})
        declared_keys = set(declared_props.keys())

        sanitized = {}
        for k, v in args.items():
            if k not in declared_keys:
                # Strip clés non-déclarées (additionalProperties drift)
                report.stripped_extra_keys.append(k)
                continue

            prop_schema = declared_props[k] or {}
            prop_type = prop_schema.get("type")
            # type peut être string OR list[string] (e.g. ["string", "null"])
            target_types: list[str]
            if isinstance(prop_type, str):
                target_types = [prop_type]
            elif isinstance(prop_type, list):
                target_types = prop_type
            else:
                target_types = []

            # None tolerated si "null" dans target_types OU param a un default
            if v is None:
                if "null" in target_types:
                    sanitized[k] = None
                else:
                    # Drop la clé pour libérer le default
                    report.dropped_none_keys.append(k)
                continue

            # Coerce vers premier target_type non-null
            primary_type = next(
                (t for t in target_types if t != "null"),
                None,
            )
            if primary_type:
                new_v, coerced = _try_coerce(v, primary_type)
                if coerced:
                    report.coerced_types.append({
                        "key": k,
                        "from": type(v).__name__,
                        "to": primary_type,
                    })
                v = new_v
            sanitized[k] = v

        return sanitized, report

    def _minimal_validate(self, spec: ToolSpec, args: dict, tool_name: str) -> None:
        """Validation minimaliste si jsonschema non installé."""
        required = spec.parameters_schema.get("required", []) or []
        missing = [k for k in required if k not in args]
        if missing:
            self._n_invalid += 1
            raise ToolCallError(
                f"Tool '{tool_name}' missing required keys: {missing}",
                error_type="missing_required",
                details={"missing": missing},
            )

    # ─── Stats ───────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "n_total": self._n_total,
            "n_repaired": self._n_repaired,
            "n_invalid": self._n_invalid,
            "n_unknown_tool": self._n_unknown,
            "repair_rate": (self._n_repaired / self._n_total) if self._n_total else 0.0,
            "invalid_rate": (self._n_invalid / self._n_total) if self._n_total else 0.0,
        }

    def reset_stats(self) -> None:
        self._n_total = 0
        self._n_repaired = 0
        self._n_invalid = 0
        self._n_unknown = 0
