"""
Analyse de slides via GPT-4 Vision (mode VISION avec images).

Module autonome extrait de pptx_pipeline.py avec toutes les dépendances.
Analyse les slides en mode Vision (images + texte) pour extraction enrichie.
"""

import base64
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from knowbase.common.llm_router import LLMRouter, TaskType
from knowbase.config.prompts_loader import load_prompts, select_prompt, render_prompt
from ..utils.text_utils import clean_gpt_response, recursive_chunk


def ask_gpt_slide_analysis(
    image_path: Path,
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
    Analyse un slide avec GPT-4 Vision (image + texte).
    Plus précis que le mode text-only mais plus coûteux.

    Extrait des concepts enrichis avec métadonnées pour ingestion dans Qdrant.
    Supporte le format unifié 4 outputs: concepts, facts, entities, relations.

    Args:
        image_path: Chemin vers l'image de la slide
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
        >>> concepts = ask_gpt_slide_analysis(
        ...     image_path=Path("slide_5.jpg"),
        ...     deck_summary="Présentation SAP S/4HANA...",
        ...     slide_index=5,
        ...     source_name="demo.pptx",
        ...     text="SAP S/4HANA Cloud features...",
        ...     notes="Focus on cloud deployment"
        ... )
        >>> len(concepts)
        4
        >>> concepts[0]["full_explanation"]
        "SAP S/4HANA Cloud provides..."
    """
    # Initialiser dépendances
    if llm_router is None:
        llm_router = LLMRouter()
    if prompt_registry is None:
        prompt_registry = load_prompts()
    if logger is None:
        logger = logging.getLogger(__name__)

    # Heartbeat avant l'appel LLM vision (long processus)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
    except Exception:
        pass  # Ignorer si pas dans un contexte RQ

    # Encoder image en base64
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

    doc_type = document_type or "default"
    slide_prompt_id, slide_template = select_prompt(prompt_registry, doc_type, "slide")

    prompt_text = render_prompt(
        slide_template,
        deck_summary=deck_summary,
        slide_index=slide_index,
        source_name=source_name,
        text=text,
        notes=notes,
        megaparse_content=megaparse_content,
    )

    # Injection du context_prompt personnalisé si fourni
    if document_context_prompt:
        logger.debug(
            f"Slide {slide_index}: Injection context_prompt personnalisé ({len(document_context_prompt)} chars)"
        )
        # Préfixer le prompt avec le contexte personnalisé
        prompt_text = f"""**CONTEXTE DOCUMENT TYPE**:
{document_context_prompt}

---

{prompt_text}"""

    msg = [
        {
            "role": "system",
            "content": "You analyze slides with visuals deeply and coherently.",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
            ],
        },
    ]

    for attempt in range(retries):
        try:
            # max_tokens=8000 pour format unifié (concepts + facts + entities + relations)
            raw_content = llm_router.complete(
                TaskType.VISION, msg, temperature=0.2, max_tokens=8000
            )
            cleaned_content = clean_gpt_response(raw_content or "")
            response_data = json.loads(cleaned_content)

            # DEBUG: Log type de réponse LLM
            logger.debug(
                f"Slide {slide_index}: LLM response type = {type(response_data).__name__}, keys = {list(response_data.keys()) if isinstance(response_data, dict) else 'N/A'}"
            )

            # === Support format unifié 4 outputs {"concepts": [...], "facts": [...], "entities": [...], "relations": [...]} ===
            # Compatibilité: Si ancien format (array direct), wrapper en {"concepts": [...]}
            if isinstance(response_data, list):
                # Ancien format (array de concepts)
                items = response_data
                facts_data = []
                entities_data = []
                relations_data = []
            elif isinstance(response_data, dict):
                # Nouveau format unifié (4 outputs)
                items = response_data.get("concepts", [])
                facts_data = response_data.get("facts", [])
                entities_data = response_data.get("entities", [])
                relations_data = response_data.get("relations", [])
            else:
                logger.warning(
                    f"Slide {slide_index}: Format JSON inattendu: {type(response_data)}"
                )
                items = []
                facts_data = []
                entities_data = []
                relations_data = []

            # Parser concepts pour Qdrant (comme avant)
            enriched = []
            for it in items:
                expl = it.get("full_explanation", "")
                meta = it.get("meta", {})
                if expl:
                    for seg in recursive_chunk(expl, max_len=400, overlap_ratio=0.15):
                        # Enrichir meta avec slide_index pour Phase 3
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
                                },
                            }
                        )

            # Stocker ALL extracted data dans enriched pour récupération ultérieure
            # (ajouté clés "_facts", "_entities", "_relations" pour passage à phase3)
            if facts_data or entities_data or relations_data:
                for concept in enriched:
                    concept["_facts"] = facts_data  # Attacher facts
                    concept["_entities"] = entities_data  # Attacher entities
                    concept["_relations"] = relations_data  # Attacher relations

            # Log avec tous les outputs
            logger.info(
                f"Slide {slide_index}: {len(enriched)} concepts + {len(facts_data)} facts + "
                f"{len(entities_data)} entities + {len(relations_data)} relations extraits"
            )

            return enriched

        except Exception as e:
            logger.warning(f"Slide {slide_index} attempt {attempt} failed: {e}")
            time.sleep(2 * (attempt + 1))

    return []


def ask_gpt_vision_summary(
    image_path: Path,
    slide_index: int,
    source_name: str,
    text: str = "",
    notes: str = "",
    megaparse_content: str = "",
    llm_router: Optional[LLMRouter] = None,
    logger: Optional[logging.Logger] = None,
    retries: int = 2,
) -> str:
    """
    OSMOSE Pure: Vision analyse une slide et retourne un résumé riche et détaillé.

    Contrairement à ask_gpt_slide_analysis qui extrait des entités/relations,
    cette fonction demande à Vision de décrire le contenu visuel ET textuel
    dans un format narratif fluide.

    OSMOSE fera ensuite l'extraction sémantique sur ces résumés.

    Args:
        image_path: Chemin vers l'image de la slide
        slide_index: Index de la slide
        source_name: Nom du document source
        text: Texte extrait de la slide (python-pptx)
        notes: Notes du présentateur
        megaparse_content: Contenu extrait par MegaParse (si disponible)
        llm_router: Instance LLMRouter (créée si None)
        logger: Logger optionnel
        retries: Nombre de tentatives en cas d'erreur

    Returns:
        str: Résumé riche et détaillé de la slide (2-4 paragraphes)

    Example:
        >>> summary = ask_gpt_vision_summary(
        ...     image_path=Path("slide_5.jpg"),
        ...     slide_index=5,
        ...     source_name="demo.pptx",
        ...     text="SAP S/4HANA Cloud",
        ...     notes="Focus deployment"
        ... )
        >>> len(summary)
        1500
        >>> "architecture" in summary.lower()
        True
    """
    # Initialiser dépendances
    if llm_router is None:
        llm_router = LLMRouter()
    if logger is None:
        logger = logging.getLogger(__name__)

    # Heartbeat avant l'appel LLM vision (long processus)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
    except Exception:
        pass  # Ignorer si pas dans un contexte RQ

    img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

    # Construire le contexte textuel disponible
    textual_context = []
    if text:
        textual_context.append(f"Slide text extracted: {text}")
    if notes:
        textual_context.append(f"Speaker notes: {notes}")
    if megaparse_content:
        textual_context.append(f"Enhanced content: {megaparse_content}")

    context_str = (
        "\n".join(textual_context) if textual_context else "No text extracted."
    )

    # Prompt pour résumé riche (pas de JSON structuré)
    prompt_text = f"""You are analyzing slide {slide_index} from the presentation "{source_name}".

{context_str}

**Your task**: Provide a comprehensive, detailed summary of this slide that captures BOTH textual content AND visual meaning.

Your summary should include:

1. **Visual Layout & Organization**
   - Describe the visual structure (diagrams, charts, graphics, images)
   - Explain how elements are positioned and organized spatially
   - Note the hierarchy and flow of information

2. **Main Message & Concepts**
   - What is the core message or concept being communicated?
   - What are the key takeaways?

3. **Visual Elements**
   - Describe any diagrams, flowcharts, architecture schemas, graphs
   - Explain what visual elements show (e.g., "arrows connecting X to Y", "boxes grouped together")
   - Interpret charts, trends, comparisons shown visually

4. **Textual Content**
   - Incorporate all important text from the slide
   - Explain headings, bullet points, labels, callouts

5. **Visual Emphasis**
   - What is highlighted or emphasized? (colors, sizes, callouts, icons)
   - Are there visual cues indicating importance or relationships?

6. **Visual Relationships**
   - How do different elements relate to each other visually?
   - Are there groupings, hierarchies, connections shown?

**IMPORTANT**:
- Write naturally in rich, flowing prose (2-4 paragraphs)
- Do NOT use bullet points or lists
- Do NOT return JSON or structured data
- Describe the slide as if explaining it to someone who cannot see it
- Focus on conveying the visual meaning, not just transcribing text

**Return ONLY the summary text, nothing else.**"""

    msg = [
        {
            "role": "system",
            "content": "You are an expert at analyzing visual presentations and understanding how visual design communicates meaning. You excel at describing slides in rich, detailed prose that captures both content and visual context.",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
            ],
        },
    ]

    for attempt in range(retries):
        try:
            # Température plus haute pour prose naturelle et riche
            raw_content = llm_router.complete(
                TaskType.VISION,
                msg,
                temperature=0.5,  # Plus créatif pour descriptions riches
                max_tokens=4000,  # OSMOSE V2: Augmenté pour résumés vraiment riches (~3000 mots/slide)
            )

            summary = (raw_content or "").strip()

            # Nettoyer markdown potentiel (SANS validation JSON - c'est de la prose !)
            summary = re.sub(r"^```(?:markdown|text)?\s*", "", summary)
            summary = re.sub(r"\s*```$", "", summary)
            summary = summary.strip()

            if summary and len(summary) > 50:  # Au moins 50 chars
                # Afficher le résumé complet dans les logs pour validation
                logger.info(
                    f"Slide {slide_index} [VISION SUMMARY]: {len(summary)} chars generated"
                )
                # logger.info(f"Slide {slide_index} [VISION SUMMARY CONTENT]:\n{summary}")
                # logger.info("=" * 80)
                return summary
            else:
                logger.warning(
                    f"Slide {slide_index} [VISION SUMMARY]: Response too short ({len(summary)} chars)"
                )

        except Exception as e:
            logger.warning(
                f"Slide {slide_index} [VISION SUMMARY] attempt {attempt+1} failed: {e}"
            )
            time.sleep(2 * (attempt + 1))

    # Fallback si Vision échoue: retourner texte brut
    fallback = f"Slide {slide_index}: {text}\n{notes}"
    logger.warning(
        f"Slide {slide_index} [VISION SUMMARY]: Using fallback text ({len(fallback)} chars)"
    )
    return fallback


__all__ = [
    "ask_gpt_slide_analysis",
    "ask_gpt_vision_summary",
]
