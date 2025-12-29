"""
Analyse de slides via LLM (mode text-only).

Module autonome extrait de pptx_pipeline.py avec toutes les dépendances.
Analyse les slides en mode text-only (sans Vision) pour extraction de métadonnées et concepts.
"""

import json
import time
from typing import List, Dict, Any, Optional
import logging

from knowbase.common.llm_router import LLMRouter, TaskType, get_llm_router
from knowbase.common.entity_normalizer import get_entity_normalizer
from knowbase.config.prompts_loader import load_prompts, select_prompt, render_prompt
from ..utils.text_utils import clean_gpt_response, recursive_chunk
from .deck_summarizer import summarize_large_pptx


def analyze_deck_summary(
    slides_data: List[Dict[str, Any]],
    source_name: str,
    document_type: str = "default",
    auto_metadata: Optional[Dict] = None,
    document_context_prompt: Optional[str] = None,
    llm_router: Optional[LLMRouter] = None,
    prompt_registry: Optional[Dict] = None,
    logger: Optional[logging.Logger] = None
) -> dict:
    """
    Analyse globale d'un deck PPTX avec extraction de métadonnées enrichies.

    Utilise un LLM pour extraire:
    - Résumé global du deck
    - Métadonnées structurées (titre, objectif, audience, solutions SAP, etc.)
    - Fusionne avec métadonnées auto-extraites (date source, titre PPTX, etc.)
    - Normalise les noms de solutions SAP avec le catalogue

    Args:
        slides_data: Liste des slides extraits [{slide_index, text, notes}, ...]
        source_name: Nom du fichier source (ex: "presentation.pptx")
        document_type: Type de document pour sélection prompts (ex: "crr", "default")
        auto_metadata: Métadonnées auto-extraites du PPTX (optionnel)
            {title, source_date, creator, company, ...}
        document_context_prompt: Prompt contexte custom (optionnel)
            Injecté au début du prompt pour guider l'extraction
        llm_router: Instance LLMRouter (créée si None)
        prompt_registry: Registry prompts (chargé depuis YAML si None)
        logger: Logger optionnel

    Returns:
        dict: {
            "summary": str,  # Résumé global du deck
            "metadata": dict,  # Métadonnées structurées
            "_prompt_meta": dict  # Métadonnées de prompt (traçabilité)
        }

    Example:
        >>> result = analyze_deck_summary(
        ...     slides_data=[{"slide_index": 1, "text": "SAP S/4HANA"}],
        ...     source_name="sap_demo.pptx",
        ...     document_type="crr",
        ...     auto_metadata={"source_date": "2025-01-15"}
        ... )
        >>> result["metadata"]["main_solution"]
        "SAP S/4HANA"
    """
    # Initialiser dépendances si non fournies (singleton avec support Burst Mode)
    if llm_router is None:
        llm_router = get_llm_router()
    if prompt_registry is None:
        prompt_registry = load_prompts()
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.info(f"🔍 GPT: analyse du deck via texte extrait — {source_name}")

    # Résumer le deck (avec chunking si nécessaire)
    summary_text = summarize_large_pptx(slides_data, document_type, llm_router, logger)

    # Sélectionner le prompt approprié pour le type de document
    doc_type = document_type or "default"
    deck_prompt_id, deck_template = select_prompt(prompt_registry, doc_type, "deck")

    # Rendre le prompt avec les variables
    prompt = render_prompt(
        deck_template,
        summary_text=summary_text,
        source_name=source_name
    )

    # Injection du context_prompt personnalisé si fourni
    if document_context_prompt:
        logger.debug(
            f"Deck summary: Injection context_prompt personnalisé ({len(document_context_prompt)} chars)"
        )
        prompt = f"""**CONTEXTE DOCUMENT TYPE**:
{document_context_prompt}

---

{prompt}"""

    try:
        # Appel LLM pour extraction métadonnées
        messages = [
            {
                "role": "system",
                "content": "You are a precise document metadata extraction assistant.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        raw = llm_router.complete(TaskType.METADATA_EXTRACTION, messages)
        cleaned = clean_gpt_response(raw)
        result = json.loads(cleaned) if cleaned else {}

        if not isinstance(result, dict):
            result = {}

        summary = result.get("summary", "")
        metadata = result.get("metadata", {})

        # --- Fusion avec les métadonnées auto-extraites du PPTX ---
        if auto_metadata:
            # Priorité aux métadonnées auto-extraites pour certains champs
            for key in ["source_date", "title"]:
                if key in auto_metadata and auto_metadata[key]:
                    metadata[key] = auto_metadata[key]
                    logger.info(f"✅ {key} auto-extrait utilisé: {auto_metadata[key]}")

        # --- Normalisation des solutions avec entity_normalizer (domain-agnostic) ---
        normalizer = get_entity_normalizer()

        raw_main = metadata.get("main_solution", "")
        if raw_main:
            sol_id, canon_name, _ = normalizer.normalize_entity_name(raw_main, "SOLUTION")
            metadata["main_solution_id"] = sol_id or "UNMAPPED"
            metadata["main_solution"] = canon_name or raw_main

        # Normaliser supporting_solutions
        normalized_supporting = []
        for supp in metadata.get("supporting_solutions", []):
            sid, canon, _ = normalizer.normalize_entity_name(supp, "SOLUTION")
            normalized_supporting.append(canon or supp)
        metadata["supporting_solutions"] = list(set(normalized_supporting))

        # Normaliser mentioned_solutions
        normalized_mentioned = []
        for ment in metadata.get("mentioned_solutions", []):
            sid, canon, _ = normalizer.normalize_entity_name(ment, "SOLUTION")
            normalized_mentioned.append(canon or ment)
        metadata["mentioned_solutions"] = list(set(normalized_mentioned))

        # Afficher le deck_summary complet pour suivi
        if summary:
            logger.info(f"📋 Deck Summary:")
            logger.info(f"   {summary}")
        else:
            logger.warning("⚠️ Aucun résumé de deck généré")

        # Métadonnées de traçabilité
        result["_prompt_meta"] = {
            "document_type": doc_type,
            "deck_prompt_id": deck_prompt_id,
            "prompts_version": prompt_registry.get("version", "unknown"),
        }

        return {
            "summary": summary,
            "metadata": metadata,
            "_prompt_meta": result["_prompt_meta"],
        }

    except Exception as e:
        logger.error(f"❌ GPT metadata error: {e}")
        return {}


def ask_gpt_slide_analysis_text_only(
    deck_summary: str,
    slide_index: int,
    source_name: str,
    text: str,
    notes: str = "",
    megaparse_content: str = "",
    document_type: str = "default",
    deck_prompt_id: str = "unknown",
    document_context_prompt: Optional[str] = None,
    llm_router: Optional[LLMRouter] = None,
    prompt_registry: Optional[Dict] = None,
    logger: Optional[logging.Logger] = None,
    retries: int = 2,
) -> List[Dict[str, Any]]:
    """
    Analyse un slide en utilisant uniquement le texte extrait, sans Vision.
    Plus rapide et moins coûteux que la version avec Vision.

    Extrait des concepts enrichis avec métadonnées pour ingestion dans Qdrant.
    Supporte le format unifié 4 outputs: concepts, facts, entities, relations.

    Args:
        deck_summary: Résumé global du deck (contexte)
        slide_index: Index de la slide
        source_name: Nom du fichier source
        text: Texte extrait de la slide (python-pptx)
        notes: Notes du présentateur (optionnel)
        megaparse_content: Contenu extrait par MegaParse (optionnel)
        document_type: Type de document pour sélection prompts
        deck_prompt_id: ID du prompt deck utilisé (traçabilité)
        document_context_prompt: Prompt contexte custom (optionnel)
        llm_router: Instance LLMRouter (créée si None)
        prompt_registry: Registry prompts (chargé si None)
        logger: Logger optionnel
        retries: Nombre de tentatives en cas d'erreur

    Returns:
        List[Dict]: Liste de concepts enrichis pour Qdrant
            [
                {
                    "full_explanation": str,  # Texte du concept (chunké si nécessaire)
                    "meta": dict,  # Métadonnées du concept
                    "prompt_meta": dict,  # Métadonnées de prompt
                    "_facts": list,  # Facts extraits (optionnel)
                    "_entities": list,  # Entities extraits (optionnel)
                    "_relations": list  # Relations extraites (optionnel)
                },
                ...
            ]

    Example:
        >>> concepts = ask_gpt_slide_analysis_text_only(
        ...     deck_summary="Présentation SAP S/4HANA...",
        ...     slide_index=5,
        ...     source_name="demo.pptx",
        ...     text="SAP S/4HANA Cloud features...",
        ...     notes="Focus on cloud deployment"
        ... )
        >>> len(concepts)
        3
        >>> concepts[0]["full_explanation"]
        "SAP S/4HANA Cloud provides..."
    """
    # Initialiser dépendances (singleton avec support Burst Mode)
    if llm_router is None:
        llm_router = get_llm_router()
    if prompt_registry is None:
        prompt_registry = load_prompts()
    if logger is None:
        logger = logging.getLogger(__name__)

    # Heartbeat avant l'appel LLM
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
    except Exception:
        pass

    doc_type = document_type or "default"
    slide_prompt_id, slide_template = select_prompt(prompt_registry, doc_type, "slide")

    # Préparer le contenu textuel pour l'analyse
    content_text = megaparse_content if megaparse_content else text
    if notes:
        content_text += f"\n\nNotes: {notes}"

    prompt_text = render_prompt(
        slide_template,
        deck_summary=deck_summary,
        slide_index=slide_index,
        source_name=source_name,
        text=content_text,
        notes=notes,
        megaparse_content=megaparse_content,
    )

    # Injection du context_prompt personnalisé si fourni
    if document_context_prompt:
        logger.debug(
            f"Slide {slide_index}: Injection context_prompt personnalisé ({len(document_context_prompt)} chars) [TEXT-ONLY MODE]"
        )
        prompt_text = f"""**CONTEXTE DOCUMENT TYPE**:
{document_context_prompt}

---

{prompt_text}"""

    msg = [
        {
            "role": "system",
            "content": "You analyze document content deeply and coherently. Extract concepts, facts, entities, and relations from the provided text.",
        },
        {
            "role": "user",
            "content": prompt_text,
        },
    ]

    for attempt in range(retries):
        try:
            # Utiliser TaskType.LONG_TEXT_SUMMARY au lieu de VISION (LLM plus rapide)
            raw_content = llm_router.complete(
                TaskType.LONG_TEXT_SUMMARY, msg, temperature=0.2, max_tokens=8000
            )
            cleaned_content = clean_gpt_response(raw_content or "")
            response_data = json.loads(cleaned_content)

            logger.debug(
                f"Slide {slide_index} [TEXT-ONLY]: LLM response type = {type(response_data).__name__}, keys = {list(response_data.keys()) if isinstance(response_data, dict) else 'N/A'}"
            )

            # Support format unifié 4 outputs
            if isinstance(response_data, list):
                items = response_data
                facts_data = []
                entities_data = []
                relations_data = []
            elif isinstance(response_data, dict):
                items = response_data.get("concepts", [])
                facts_data = response_data.get("facts", [])
                entities_data = response_data.get("entities", [])
                relations_data = response_data.get("relations", [])
            else:
                logger.warning(
                    f"Slide {slide_index} [TEXT-ONLY]: Format JSON inattendu: {type(response_data)}"
                )
                items = []
                facts_data = []
                entities_data = []
                relations_data = []

            # Parser concepts pour Qdrant
            enriched = []
            for it in items:
                expl = it.get("full_explanation", "")
                meta = it.get("meta", {})
                if expl:
                    for seg in recursive_chunk(expl, max_len=400, overlap_ratio=0.15):
                        meta_enriched = {**meta, "slide_index": slide_index}
                        enriched.append(
                            {
                                "full_explanation": seg,
                                "meta": meta_enriched,
                                "prompt_meta": {
                                    "document_type": doc_type,
                                    "slide_prompt_id": slide_prompt_id,
                                    "prompts_version": prompt_registry.get(
                                        "version", "unknown"
                                    ),
                                    "extraction_mode": "text_only",  # Marqueur mode text-only
                                },
                            }
                        )

            # Attacher facts/entities/relations
            if facts_data or entities_data or relations_data:
                for concept in enriched:
                    concept["_facts"] = facts_data
                    concept["_entities"] = entities_data
                    concept["_relations"] = relations_data

            logger.info(
                f"Slide {slide_index} [TEXT-ONLY]: {len(enriched)} concepts + {len(facts_data)} facts + "
                f"{len(entities_data)} entities + {len(relations_data)} relations extraits"
            )

            return enriched

        except Exception as e:
            logger.warning(
                f"Slide {slide_index} [TEXT-ONLY] attempt {attempt} failed: {e}"
            )
            time.sleep(2 * (attempt + 1))

    return []


__all__ = [
    "analyze_deck_summary",
    "ask_gpt_slide_analysis_text_only",
]
