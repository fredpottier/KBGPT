"""
CH-12 — Loader des listes de détection linguistique externalisées.

Lit `config/detection_keywords.yaml` et expose des tuples immuables
(rétrocompat avec les hardcodes Python originels qui étaient des listes).

Usage minimal :

    from knowbase.config.detection_keywords import get_detection_keywords

    kw = get_detection_keywords()
    if any(t in answer.lower() for t in kw.tension_keywords):
        ...

Pour le tenant : `get_detection_keywords(tenant_id="acme")`.
Les listes du tenant override la liste de base si présentes.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "DETECTION_KEYWORDS_CONFIG",
        "config/detection_keywords.yaml",
    )
)


@dataclass(frozen=True)
class DetectionKeywords:
    tension_keywords: tuple[str, ...] = field(default_factory=tuple)
    ignorance_keywords: tuple[str, ...] = field(default_factory=tuple)
    correction_keywords: tuple[str, ...] = field(default_factory=tuple)
    temporal_keywords: tuple[str, ...] = field(default_factory=tuple)
    contradiction_keywords: tuple[str, ...] = field(default_factory=tuple)
    idk_phrases: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict) -> "DetectionKeywords":
        def _t(key: str) -> tuple[str, ...]:
            v = data.get(key) or []
            return tuple(str(x).lower() for x in v if x is not None)

        return cls(
            tension_keywords=_t("tension_keywords"),
            ignorance_keywords=_t("ignorance_keywords"),
            correction_keywords=_t("correction_keywords"),
            temporal_keywords=_t("temporal_keywords"),
            contradiction_keywords=_t("contradiction_keywords"),
            idk_phrases=_t("idk_phrases"),
        )


_cache: dict[str, DetectionKeywords] = {}
_raw_yaml: Optional[dict] = None


def _load_yaml() -> dict:
    global _raw_yaml
    if _raw_yaml is not None:
        return _raw_yaml
    path = DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        # Résoudre depuis la racine du repo (parents de src/knowbase/config)
        repo_root = Path(__file__).resolve().parents[3]
        path = repo_root / path
    if not path.exists():
        logger.warning("[DETECTION_KEYWORDS] Config not found: %s — using empty defaults", path)
        _raw_yaml = {}
        return _raw_yaml
    try:
        with path.open("r", encoding="utf-8") as f:
            _raw_yaml = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("[DETECTION_KEYWORDS] Failed to load %s: %s", path, exc)
        _raw_yaml = {}
    return _raw_yaml


def _merge_with_overrides(base: dict, overrides: Optional[dict]) -> dict:
    if not overrides:
        return base
    merged = dict(base)
    for key, val in overrides.items():
        if isinstance(val, list):
            merged[key] = val
    return merged


def get_detection_keywords(tenant_id: str = "default") -> DetectionKeywords:
    """Retourne le bundle de listes pour le tenant donné (cache process-level)."""
    if tenant_id in _cache:
        return _cache[tenant_id]

    raw = _load_yaml()
    overrides = (raw.get("tenant_overrides") or {}).get(tenant_id) or {}
    merged = _merge_with_overrides(raw, overrides)
    obj = DetectionKeywords.from_dict(merged)
    _cache[tenant_id] = obj
    return obj


def reload_detection_keywords() -> None:
    """Force le rechargement YAML (utile en test ou après edit live)."""
    global _raw_yaml, _cache
    _raw_yaml = None
    _cache = {}
