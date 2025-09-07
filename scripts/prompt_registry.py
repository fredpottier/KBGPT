import logging
import yaml


def load_prompts(path: str = "config/prompts.yaml") -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "families" in data and "version" in data
        return data
    except Exception as e:
        logging.warning(
            f"[PROMPT_REGISTRY] Erreur chargement YAML : {e}. Fallback sur le prompt minimal."
        )
        # Fallback minimal
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


def select_prompt(registry: dict, document_type: str, level: str):
    fam = registry.get("families", {})
    doc_type = document_type if document_type in fam else "default"
    family = fam.get(doc_type, fam.get("default"))
    if not family:
        family = fam.get("default")
    if level in family:
        return family[level]["id"], family[level]["template"]
    # Fallback sur default
    default_family = fam.get("default", {})
    if level in default_family:
        return default_family[level]["id"], default_family[level]["template"]
    # Fallback ultime
    return "unknown", "No prompt available."


def render_prompt(template: str, **kwargs) -> str:
    try:
        from jinja2 import Template

        return Template(template).render(**kwargs)
    except Exception as e:
        logging.warning(f"[PROMPT_REGISTRY] Erreur rendu template : {e}")
        return template
