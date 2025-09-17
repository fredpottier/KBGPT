from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Tuple

import yaml

from knowbase.config.paths import PROJECT_ROOT

DEFAULT_PROMPTS_PATH = PROJECT_ROOT / "configs" / "prompts.yaml"


def load_prompts(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_PROMPTS_PATH
    try:
        with target.open("r", encoding="utf-8") as handler:
            data = yaml.safe_load(handler)
        if not isinstance(data, dict) or "families" not in data:
            raise ValueError("invalid prompt registry structure")
        return data
    except Exception as exc:
        logging.warning(
            "[PROMPT_REGISTRY] Erreur chargement YAML (%s). Fallback minimal utilisé.",
            exc,
        )
        return {
            "version": "fallback",
            "families": {
                "default": {
                    "deck": {
                        "id": "deck_default_fallback",
                        "template": "Summarize: {{ summary_text }}",
                    },
                    "slide": {
                        "id": "slide_default_fallback",
                        "template": "Explain slide {{ slide_index }}: {{ text }}",
                    },
                }
            },
        }


def select_prompt(registry: dict[str, Any], document_type: str, level: str) -> Tuple[str, str]:
    families = registry.get("families", {}) if isinstance(registry, dict) else {}
    family = families.get(document_type) or families.get("default", {})
    if level in family:
        entry = family[level]
        return entry.get("id", "unknown"), entry.get("template", "No prompt available.")
    default_family = families.get("default", {})
    if level in default_family:
        entry = default_family[level]
        return entry.get("id", "unknown"), entry.get("template", "No prompt available.")
    return "unknown", "No prompt available."


def render_prompt(template: str, **kwargs: Any) -> str:
    try:
        from jinja2 import Template

        return Template(template).render(**kwargs)
    except Exception as exc:
        logging.warning("[PROMPT_REGISTRY] Erreur rendu template : %s", exc)
        return template
