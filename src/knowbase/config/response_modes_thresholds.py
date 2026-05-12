"""
OSMOSIS Response Modes Thresholds — Loader.

Charge les seuils calibrables (par corpus / tenant) utilisés par
`signal_policy.py` pour décider du response mode.

Pattern :
- YAML `config/response_modes_thresholds.yaml` = defaults
- tenant_overrides dans le YAML = override par tenant (lookup via TENANT_ID env)
- (futur CH-11) `tenant_settings` Postgres = override live via admin UI

Singleton avec cache module-level pour éviter de relire le YAML à chaque query.
Reload disponible via `reload_thresholds()` (utile pour les tests + admin UI).

Usage :
    from knowbase.config.response_modes_thresholds import get_thresholds
    t = get_thresholds()
    if signal.strength >= t.stage_a.tension.min_strength:
        ...
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/response_modes_thresholds.yaml")


# ─── Dataclasses miroirs du YAML ────────────────────────────────────────────


@dataclass(frozen=True)
class TensionTrigger:
    min_strength: float = 0.6
    min_texts: int = 3


@dataclass(frozen=True)
class StructuredFactTrigger:
    min_strength: float = 0.5


@dataclass(frozen=True)
class AugmentedTrigger:
    min_new_docs: int = 3


@dataclass(frozen=True)
class StageATriggers:
    tension: TensionTrigger = field(default_factory=TensionTrigger)
    structured_fact: StructuredFactTrigger = field(default_factory=StructuredFactTrigger)
    augmented: AugmentedTrigger = field(default_factory=AugmentedTrigger)


@dataclass(frozen=True)
class TensionGate:
    min_distinct_docs: int = 2
    min_kg_trust: float = 0.4


@dataclass(frozen=True)
class StructuredFactGate:
    min_comparable_facts: int = 2
    min_kg_trust: float = 0.5


@dataclass(frozen=True)
class AugmentedGate:
    min_new_docs: int = 3
    min_kg_trust: float = 0.5


@dataclass(frozen=True)
class StageBGates:
    tension: TensionGate = field(default_factory=TensionGate)
    structured_fact: StructuredFactGate = field(default_factory=StructuredFactGate)
    augmented: AugmentedGate = field(default_factory=AugmentedGate)


@dataclass(frozen=True)
class DirectToTensionOverride:
    min_confidence: float = 0.85


@dataclass(frozen=True)
class StageBOverride:
    direct_to_tension: DirectToTensionOverride = field(default_factory=DirectToTensionOverride)


@dataclass(frozen=True)
class ResponseModesThresholds:
    max_kg_injection_tokens: int = 150
    stage_a: StageATriggers = field(default_factory=StageATriggers)
    stage_b: StageBGates = field(default_factory=StageBGates)
    stage_b_override: StageBOverride = field(default_factory=StageBOverride)
    generic_entities: frozenset[str] = field(default_factory=frozenset)


# ─── Loading + cache ─────────────────────────────────────────────────────────


_cache: Optional[ResponseModesThresholds] = None


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge récursif (override prend précédence)."""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _build_thresholds(raw: dict) -> ResponseModesThresholds:
    """Construit l'objet typé depuis le dict YAML."""
    g = raw.get("global", {})
    sa = raw.get("stage_a_triggers", {})
    sb = raw.get("stage_b_gates", {})
    sbo = raw.get("stage_b_override", {})

    return ResponseModesThresholds(
        max_kg_injection_tokens=int(g.get("max_kg_injection_tokens", 150)),
        stage_a=StageATriggers(
            tension=TensionTrigger(
                min_strength=float(sa.get("tension", {}).get("min_strength", 0.6)),
                min_texts=int(sa.get("tension", {}).get("min_texts", 3)),
            ),
            structured_fact=StructuredFactTrigger(
                min_strength=float(sa.get("structured_fact", {}).get("min_strength", 0.5)),
            ),
            augmented=AugmentedTrigger(
                min_new_docs=int(sa.get("augmented", {}).get("min_new_docs", 3)),
            ),
        ),
        stage_b=StageBGates(
            tension=TensionGate(
                min_distinct_docs=int(sb.get("tension", {}).get("min_distinct_docs", 2)),
                min_kg_trust=float(sb.get("tension", {}).get("min_kg_trust", 0.4)),
            ),
            structured_fact=StructuredFactGate(
                min_comparable_facts=int(sb.get("structured_fact", {}).get("min_comparable_facts", 2)),
                min_kg_trust=float(sb.get("structured_fact", {}).get("min_kg_trust", 0.5)),
            ),
            augmented=AugmentedGate(
                min_new_docs=int(sb.get("augmented", {}).get("min_new_docs", 3)),
                min_kg_trust=float(sb.get("augmented", {}).get("min_kg_trust", 0.5)),
            ),
        ),
        stage_b_override=StageBOverride(
            direct_to_tension=DirectToTensionOverride(
                min_confidence=float(sbo.get("direct_to_tension", {}).get("min_confidence", 0.85)),
            ),
        ),
        generic_entities=frozenset(
            (e or "").lower().strip() for e in raw.get("generic_entities", []) if e
        ),
    )


def _load_raw() -> dict:
    """Lit le YAML + applique les tenant overrides."""
    if not CONFIG_PATH.exists():
        logger.warning(
            f"[ResponseModesThresholds] Config file not found: {CONFIG_PATH}. Using defaults."
        )
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"[ResponseModesThresholds] Error loading {CONFIG_PATH}: {e}. Using defaults.")
        return {}

    # Apply tenant overrides if any
    tenant_id = os.getenv("TENANT_ID", "default")
    overrides_block = raw.get("tenant_overrides", {}) or {}
    tenant_override = overrides_block.get(tenant_id) if isinstance(overrides_block, dict) else None
    if tenant_override and isinstance(tenant_override, dict):
        logger.info(f"[ResponseModesThresholds] Applied tenant overrides for tenant_id={tenant_id}")
        raw = _deep_merge(raw, tenant_override)

    return raw


def get_thresholds() -> ResponseModesThresholds:
    """Singleton — charge le YAML une fois, cache module-level."""
    global _cache
    if _cache is None:
        raw = _load_raw()
        _cache = _build_thresholds(raw)
        logger.info(
            f"[ResponseModesThresholds] Loaded — "
            f"AUGMENTED min_new_docs={_cache.stage_a.augmented.min_new_docs}, "
            f"TENSION min_strength={_cache.stage_a.tension.min_strength}, "
            f"generic_entities={len(_cache.generic_entities)}"
        )
    return _cache


def reload_thresholds() -> ResponseModesThresholds:
    """Force reload depuis le disque (utile pour tests + future admin UI)."""
    global _cache
    _cache = None
    return get_thresholds()


__all__ = [
    "ResponseModesThresholds",
    "get_thresholds",
    "reload_thresholds",
]
