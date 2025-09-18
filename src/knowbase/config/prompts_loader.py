from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Tuple

import yaml

from knowbase.config.paths import PROJECT_ROOT

# Dans un conteneur Docker, PROJECT_ROOT peut ne pas être calculé correctement
# Donc on vérifie si on est dans un environnement Docker
def _get_prompts_path() -> Path:
    # Chemin calculé normalement
    calculated_path = PROJECT_ROOT.resolve() / "config" / "prompts.yaml"

    # Si on est dans un conteneur Docker (/app est le workdir)
    docker_path = Path("/app/config/prompts.yaml")

    # Utiliser le chemin Docker s'il existe, sinon le chemin calculé
    if docker_path.exists():
        return docker_path
    elif calculated_path.exists():
        return calculated_path
    else:
        # Fallback vers le chemin calculé même s'il n'existe pas (pour le logging d'erreur)
        return calculated_path

DEFAULT_PROMPTS_PATH = _get_prompts_path()


def load_prompts(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_PROMPTS_PATH
    logging.debug(f"[PROMPT_REGISTRY] Tentative de chargement depuis : {target.absolute()}")
    logging.debug(f"[PROMPT_REGISTRY] Fichier existe : {target.exists()}")
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
