"""
Service de generation d'assertions (OSMOSE Assertion-Centric).

Ce module genere des reponses structurees en assertions a partir des sources
recuperees lors de la recherche.

Chaque assertion est un claim logique verifiable avec son type:
- FACT: Explicitement present dans les sources
- INFERRED: Deduit logiquement de FACTs

Le backend (assertion_classifier) valide ensuite ces assertions et peut
changer le statut final en FRAGILE ou CONFLICT.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from jinja2 import Template

from knowbase.common.llm_router import TaskType, get_llm_router
from knowbase.api.schemas.instrumented import (
    AssertionCandidate,
    LLMAssertionResponse,
)

logger = logging.getLogger(__name__)

# Chemin vers le fichier prompts.yaml
PROMPTS_PATH = Path(__file__).parent.parent.parent.parent.parent / "config" / "prompts.yaml"


def _load_assertion_prompt() -> str:
    """
    Charge le template du prompt assertion_synthesis depuis prompts.yaml.

    Returns:
        Template Jinja2 du prompt
    """
    try:
        with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
            prompts_config = yaml.safe_load(f)

        assertion_config = prompts_config.get("assertion_synthesis", {})
        template = assertion_config.get("template", "")

        if not template:
            logger.warning("[ASSERTION_GEN] No assertion_synthesis template found in prompts.yaml")
            return _get_fallback_prompt()

        return template

    except Exception as e:
        logger.error(f"[ASSERTION_GEN] Error loading prompt: {e}")
        return _get_fallback_prompt()


def _get_fallback_prompt() -> str:
    """Prompt de secours si le fichier YAML n'est pas accessible."""
    return """
You are OSMOSE. Generate an assertion-based answer as JSON.

Question: {{ question }}

Evidence:
{% for evidence in evidences %}
Source {{ evidence.source_id }}: {{ evidence.excerpt }}
{% endfor %}

Return JSON with:
- "assertions": list of {"id": "A1", "text_md": "...", "kind": "FACT"|"INFERRED", "evidence_used": [], "derived_from": [], "notes": null}
- "open_points": list of strings

Rules:
- FACT: supported by evidence, include evidence_used
- INFERRED: derived from FACTs, include derived_from and notes
- 6-14 assertions total
- Language: {{ language | default('fr') }}

JSON only, no explanation:
"""


def _clean_json_response(response: str) -> str:
    """
    Nettoie la reponse LLM pour extraire le JSON valide.

    Args:
        response: Reponse brute du LLM

    Returns:
        JSON nettoye
    """
    response = response.strip()

    # Enleve les balises markdown code block si presentes
    if response.startswith("```json"):
        response = response[7:]
    elif response.startswith("```"):
        response = response[3:]

    if response.endswith("```"):
        response = response[:-3]

    response = response.strip()

    # Trouve le premier { et le dernier }
    start = response.find("{")
    end = response.rfind("}")

    if start != -1 and end != -1 and end > start:
        response = response[start:end + 1]

    return response


def _parse_llm_response(response: str) -> LLMAssertionResponse:
    """
    Parse la reponse JSON du LLM en LLMAssertionResponse.

    Args:
        response: Reponse JSON du LLM

    Returns:
        LLMAssertionResponse valide

    Raises:
        ValueError: Si le JSON est invalide
    """
    cleaned = _clean_json_response(response)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"[ASSERTION_GEN] JSON parse error: {e}")
        logger.debug(f"[ASSERTION_GEN] Raw response: {response[:500]}")
        raise ValueError(f"Invalid JSON from LLM: {e}")

    # Valide et construit les AssertionCandidate
    assertions = []
    for raw_assertion in data.get("assertions", []):
        try:
            candidate = AssertionCandidate(
                id=raw_assertion.get("id", f"A{len(assertions) + 1}"),
                text_md=raw_assertion.get("text_md", ""),
                kind=raw_assertion.get("kind", "FACT"),
                evidence_used=raw_assertion.get("evidence_used", []),
                derived_from=raw_assertion.get("derived_from", []),
                notes=raw_assertion.get("notes"),
            )
            assertions.append(candidate)
        except Exception as e:
            logger.warning(f"[ASSERTION_GEN] Skip invalid assertion: {e}")
            continue

    # Extrait les open_points
    open_points = data.get("open_points", [])
    if isinstance(open_points, list):
        open_points = [str(op) for op in open_points if op]
    else:
        open_points = []

    return LLMAssertionResponse(
        assertions=assertions,
        open_points=open_points,
    )


def prepare_evidence_for_prompt(
    chunks: List[Dict[str, Any]],
    max_chunks: int = 12
) -> List[Dict[str, Any]]:
    """
    Prepare les chunks pour le prompt assertion_synthesis.

    Args:
        chunks: Liste des chunks recuperes (avec scores)
        max_chunks: Nombre max de chunks a inclure

    Returns:
        Liste d'evidences formatees pour le template
    """
    evidences = []

    for idx, chunk in enumerate(chunks[:max_chunks], 1):
        source_id = f"S{idx}"

        # Extrait les metadonnees du chunk
        source_file = chunk.get("source_file", "Document inconnu")
        slide_index = chunk.get("slide_index", "")
        text = chunk.get("text", "").strip()

        # Determine le titre du document
        if source_file and source_file != "Source inconnue":
            doc_title = Path(source_file).stem
        else:
            doc_title = "Document inconnu"

        # Determine l'autorite (heuristique basee sur le nom)
        authority = _infer_authority(source_file)

        # Determine la date si disponible
        doc_date = chunk.get("document_date")

        evidence = {
            "source_id": source_id,
            "document_title": doc_title,
            "document_date": doc_date,
            "authority": authority,
            "page_or_slide": slide_index if slide_index else None,
            "excerpt": text,
        }

        evidences.append(evidence)

    return evidences


def _infer_authority(source_file: str) -> str:
    """
    Infere le niveau d'autorite d'une source basee sur son nom.

    Args:
        source_file: Nom/chemin du fichier source

    Returns:
        Authority level: "official", "internal", "partner", "external"
    """
    if not source_file:
        return "internal"

    source_lower = source_file.lower()

    # Patterns pour sources officielles (documentation vendor)
    if any(p in source_lower for p in ["official", "documentation", "reference", "whitepaper"]):
        return "official"

    # Patterns pour sources partenaires
    if any(p in source_lower for p in ["partner", "consultant", "accenture", "deloitte", "pwc"]):
        return "partner"

    # Patterns pour sources externes
    if any(p in source_lower for p in ["external", "third-party", "blog", "article"]):
        return "external"

    # Par defaut: interne
    return "internal"


def generate_assertions(
    question: str,
    chunks: List[Dict[str, Any]],
    language: str = "fr",
    session_context: str = "",
    max_retries: int = 2,
) -> Tuple[LLMAssertionResponse, Dict[str, Any]]:
    """
    Genere des assertions structurees a partir de la question et des sources.

    Args:
        question: Question de l'utilisateur
        chunks: Chunks recuperes par la recherche
        language: Langue de la reponse ("fr" ou "en")
        session_context: Contexte conversationnel optionnel
        max_retries: Nombre de tentatives en cas d'echec

    Returns:
        Tuple (LLMAssertionResponse, metadata_dict)
        - LLMAssertionResponse contient les assertions et open_points
        - metadata_dict contient les metriques de generation
    """
    start_time = time.time()

    if not chunks:
        logger.warning("[ASSERTION_GEN] No chunks provided, returning empty response")
        return LLMAssertionResponse(assertions=[], open_points=["Aucune source disponible."]), {
            "generation_time_ms": 0,
            "llm_calls": 0,
            "chunks_used": 0,
        }

    # Prepare les evidences pour le prompt
    evidences = prepare_evidence_for_prompt(chunks)

    # Charge et rend le template
    template_str = _load_assertion_prompt()
    template = Template(template_str)

    prompt = template.render(
        question=question,
        evidences=evidences,
        language=language,
        session_context=session_context,
    )

    # Log la taille du prompt
    prompt_size = len(prompt)
    logger.info(f"[ASSERTION_GEN] Prompt size: {prompt_size} chars, {len(evidences)} sources")

    # Appel LLM avec retries
    router = get_llm_router()
    messages = [
        {
            "role": "system",
            "content": "You are OSMOSE, a knowledge synthesis assistant that produces structured assertion-based answers. Return only valid JSON."
        },
        {"role": "user", "content": prompt}
    ]

    last_error = None
    llm_calls = 0

    for attempt in range(max_retries + 1):
        try:
            llm_calls += 1
            response = router.complete(
                task_type=TaskType.LONG_TEXT_SUMMARY,
                messages=messages,
                temperature=0.2,  # Plus deterministe pour JSON
                max_tokens=3000,
            )

            # Parse la reponse
            parsed = _parse_llm_response(response)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[ASSERTION_GEN] Success: {len(parsed.assertions)} assertions, "
                f"{len(parsed.open_points)} open_points in {elapsed_ms:.0f}ms"
            )

            return parsed, {
                "generation_time_ms": elapsed_ms,
                "llm_calls": llm_calls,
                "chunks_used": len(evidences),
                "prompt_size": prompt_size,
            }

        except Exception as e:
            last_error = e
            logger.warning(f"[ASSERTION_GEN] Attempt {attempt + 1} failed: {e}")

            if attempt < max_retries:
                # Ajoute une indication pour le retry
                messages[-1]["content"] = prompt + "\n\nIMPORTANT: Return ONLY valid JSON, no explanation."

    # Echec apres tous les retries
    elapsed_ms = (time.time() - start_time) * 1000
    logger.error(f"[ASSERTION_GEN] All attempts failed: {last_error}")

    # Retourne une reponse de fallback
    fallback_response = _create_fallback_response(question, chunks, language)

    return fallback_response, {
        "generation_time_ms": elapsed_ms,
        "llm_calls": llm_calls,
        "chunks_used": len(chunks),
        "error": str(last_error),
        "fallback": True,
    }


def _create_fallback_response(
    question: str,
    chunks: List[Dict[str, Any]],
    language: str
) -> LLMAssertionResponse:
    """
    Cree une reponse de fallback basique si le LLM echoue.

    Args:
        question: Question originale
        chunks: Chunks disponibles
        language: Langue

    Returns:
        LLMAssertionResponse avec assertions basiques
    """
    assertions = []

    # Cree une assertion par chunk (max 10)
    for idx, chunk in enumerate(chunks[:10], 1):
        text = chunk.get("text", "").strip()
        if not text or len(text) < 20:
            continue

        # Tronque si trop long
        if len(text) > 300:
            text = text[:297] + "..."

        assertions.append(AssertionCandidate(
            id=f"A{idx}",
            text_md=text,
            kind="FACT",
            evidence_used=[f"S{idx}"],
            derived_from=[],
            notes=None,
        ))

    open_point = "La génération structurée a échoué. Les extraits sources sont présentés directement." if language == "fr" else "Structured generation failed. Source excerpts are presented directly."

    return LLMAssertionResponse(
        assertions=assertions,
        open_points=[open_point],
    )


def validate_assertion_references(
    response: LLMAssertionResponse,
    available_source_ids: List[str],
) -> LLMAssertionResponse:
    """
    Valide et corrige les references dans les assertions.

    - Verifie que les source_ids existent
    - Verifie que les assertion_ids dans derived_from existent

    Args:
        response: Reponse LLM a valider
        available_source_ids: Liste des IDs sources valides (S1, S2, ...)

    Returns:
        LLMAssertionResponse corrigee
    """
    valid_assertion_ids = set()
    corrected_assertions = []

    for assertion in response.assertions:
        # Valide les evidence_used
        valid_evidence = [
            sid for sid in assertion.evidence_used
            if sid in available_source_ids
        ]

        # Valide les derived_from (doivent etre des assertions PRECEDENTES)
        valid_derived = [
            aid for aid in assertion.derived_from
            if aid in valid_assertion_ids
        ]

        # Corrige le kind si necessaire
        kind = assertion.kind
        if kind == "FACT" and not valid_evidence:
            # Un FACT sans evidence valide devient INFERRED si derived_from existe
            if valid_derived:
                kind = "INFERRED"
            # Sinon on garde FACT mais sans evidence (sera traite comme FRAGILE par le classifier)

        corrected = AssertionCandidate(
            id=assertion.id,
            text_md=assertion.text_md,
            kind=kind,
            evidence_used=valid_evidence,
            derived_from=valid_derived,
            notes=assertion.notes,
        )

        corrected_assertions.append(corrected)
        valid_assertion_ids.add(assertion.id)

    return LLMAssertionResponse(
        assertions=corrected_assertions,
        open_points=response.open_points,
    )


__all__ = [
    "generate_assertions",
    "prepare_evidence_for_prompt",
    "validate_assertion_references",
]
