# ingest_pptx_via_gpt.py — version améliorée avec contexte global & thumbnails

import base64
import json
import os
import shutil
import subprocess
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from knowbase.common.sap.normalizer import normalize_solution_name

from langdetect import detect, DetectorFactory, LangDetectException
import fitz  # PyMuPDF
from PIL import Image
from qdrant_client.models import PointStruct
from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.common.llm_router import LLMRouter, TaskType

from knowbase.common.logging import setup_logging
from knowbase.config.prompts_loader import load_prompts, select_prompt, render_prompt


from knowbase.config.paths import ensure_directories
from knowbase.config.settings import get_settings
from knowbase.db import SessionLocal, DocumentType

# Phase 1 - Document Backbone Services
from knowbase.api.services.document_registry_service import DocumentRegistryService

# V2.2 - Extraction Cache System
from knowbase.ingestion.extraction_cache import get_cache_manager


# --- Initialisation des chemins et variables globales ---
settings = get_settings()

DOCS_IN = settings.docs_in_dir
DOCS_DONE = settings.presentations_dir
SLIDES_PNG = settings.slides_dir
THUMBNAILS_DIR = settings.thumbnails_dir
STATUS_DIR = settings.status_dir
LOGS_DIR = settings.logs_dir
MODELS_DIR = settings.models_dir

QDRANT_COLLECTION = settings.qdrant_collection
GPT_MODEL = settings.gpt_model
EMB_MODEL_NAME = settings.embeddings_model
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))

logger = setup_logging(LOGS_DIR, "ingest_debug.log", enable_console=False)
DetectorFactory.seed = 0

# Patch unstructured pour éviter HTTP 403 avant l'import MegaParse
try:
    exec(open("/app/patch_unstructured.py").read())
except Exception as e:
    logger.warning(f"Could not apply unstructured patch: {e}")

# Import conditionnel de MegaParse avec fallback (après définition du logger)
PPTX_FALLBACK = False  # Initialiser par défaut
_MODULES_LOGGED = False  # Flag pour éviter logs répétés

try:
    from megaparse import MegaParse

    MEGAPARSE_AVAILABLE = True
    if not _MODULES_LOGGED:
        logger.info("✅ MegaParse disponible")

    # Même si MegaParse est disponible, vérifier python-pptx pour le fallback
    try:
        from pptx import Presentation

        PPTX_FALLBACK = True
        if not _MODULES_LOGGED:
            logger.info("✅ python-pptx disponible comme fallback")
            _MODULES_LOGGED = True
    except ImportError:
        PPTX_FALLBACK = False
        if not _MODULES_LOGGED:
            logger.warning("⚠️ python-pptx non disponible pour fallback")
            _MODULES_LOGGED = True

except ImportError as e:
    MEGAPARSE_AVAILABLE = False
    if not _MODULES_LOGGED:
        logger.warning(f"⚠️ MegaParse non disponible, fallback vers python-pptx: {e}")

    # Fallback vers python-pptx si disponible
    try:
        from pptx import Presentation

        PPTX_FALLBACK = True
        if not _MODULES_LOGGED:
            logger.info("✅ python-pptx disponible comme fallback")
            _MODULES_LOGGED = True
    except ImportError:
        PPTX_FALLBACK = False
        if not _MODULES_LOGGED:
            logger.error("❌ Ni MegaParse ni python-pptx disponibles!")
            _MODULES_LOGGED = True

PROMPT_REGISTRY = load_prompts()

# --- Import des composants modulaires ---
from knowbase.ingestion.components.extractors import (
    calculate_checksum,
    extract_pptx_metadata,
    remove_hidden_slides_inplace,
    extract_notes_and_text,
    validate_pptx_media,
    strip_animated_gifs_from_pptx,
)
from knowbase.ingestion.components.converters import (
    convert_pptx_to_pdf,
    convert_pdf_to_images_pymupdf,
)
from knowbase.ingestion.components.transformers import (
    chunk_slides_by_tokens,
    summarize_large_pptx,
)
from knowbase.ingestion.components.utils import (
    run_cmd,
    encode_image_base64,
    normalize_public_url,
    clean_gpt_response,
    get_language_iso2,
    estimate_tokens,
)
from knowbase.ingestion.components.sinks import (
    ingest_chunks,
    embed_texts,
)

# --- Fonctions utilitaires ---


def ensure_dirs():
    ensure_directories(
        [
            DOCS_IN,
            DOCS_DONE,
            SLIDES_PNG,
            THUMBNAILS_DIR,
            STATUS_DIR,
            LOGS_DIR,
            MODELS_DIR,
        ]
    )


# Résout le chemin vers LibreOffice/soffice
def resolve_soffice_path() -> str:
    cand = os.getenv("SOFFICE_PATH", "").strip()
    if cand and Path(cand).exists():
        return cand
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return found or "/usr/bin/soffice"


PUBLIC_URL = normalize_public_url(os.getenv("PUBLIC_URL", "knowbase.ngrok.app"))
SOFFICE_PATH = resolve_soffice_path()

# --- Initialisation des clients et modèles ---
llm_router = LLMRouter()
qdrant_client = get_qdrant_client()
model = get_sentence_transformer(EMB_MODEL_NAME)
embedding_size = model.get_sentence_embedding_dimension()
if embedding_size is None:
    raise RuntimeError("SentenceTransformer returned no embedding dimension")
EMB_SIZE = int(embedding_size)
ensure_qdrant_collection(QDRANT_COLLECTION, EMB_SIZE)

MAX_TOKENS_THRESHOLD = (
    8000  # Contexte optimal pour analyse de slides (évite consommation excessive)
)
MAX_PARTIAL_TOKENS = 8000
# MAX_SUMMARY_TOKENS supprimé - OSMOSE V2.2: Aucune limite, Claude 200K gère tout

# --- Fonctions principales du pipeline ---
# (strip_animated_gifs_from_pptx, validate_pptx_media, convert_pptx_to_pdf,
#  convert_pdf_to_images_pymupdf désormais importés depuis components/)


def analyze_deck_summary(
    slides_data: List[Dict[str, Any]],
    source_name: str,
    document_type: str = "default",
    auto_metadata: dict = None,
    document_context_prompt: str = None,
) -> dict:
    logger.info(f"🔍 GPT: analyse du deck via texte extrait — {source_name}")
    summary_text = summarize_large_pptx(slides_data, document_type)
    doc_type = document_type or "default"
    deck_prompt_id, deck_template = select_prompt(PROMPT_REGISTRY, doc_type, "deck")
    prompt = render_prompt(
        deck_template, summary_text=summary_text, source_name=source_name
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

        # --- Normalisation des solutions directement sur metadata plat ---
        raw_main = metadata.get("main_solution", "")
        if raw_main:
            sol_id, canon_name = normalize_solution_name(raw_main)
            metadata["main_solution_id"] = sol_id
            metadata["main_solution"] = canon_name or raw_main

        # Normaliser supporting_solutions
        normalized_supporting = []
        for supp in metadata.get("supporting_solutions", []):
            sid, canon = normalize_solution_name(supp)
            normalized_supporting.append(canon or supp)
        metadata["supporting_solutions"] = list(set(normalized_supporting))

        # Normaliser mentioned_solutions
        normalized_mentioned = []
        for ment in metadata.get("mentioned_solutions", []):
            sid, canon = normalize_solution_name(ment)
            normalized_mentioned.append(canon or ment)
        metadata["mentioned_solutions"] = list(set(normalized_mentioned))
        # Afficher le deck_summary complet pour suivi
        if summary:
            logger.info(f"📋 Deck Summary:")
            logger.info(f"   {summary}")
        else:
            logger.warning("⚠️ Aucun résumé de deck généré")
        result["_prompt_meta"] = {
            "document_type": doc_type,
            "deck_prompt_id": deck_prompt_id,
            "prompts_version": PROMPT_REGISTRY.get("version", "unknown"),
        }
        return {
            "summary": summary,
            "metadata": metadata,
            "_prompt_meta": result["_prompt_meta"],
        }
    except Exception as e:
        logger.error(f"❌ GPT metadata error: {e}")
        return {}


# Analyse d'un slide via GPT SANS image (text-only), retourne les chunks enrichis
def ask_gpt_slide_analysis_text_only(
    deck_summary,
    slide_index,
    source_name,
    text,
    notes,
    megaparse_content="",
    document_type="default",
    deck_prompt_id="unknown",
    document_context_prompt=None,
    retries=2,
):
    """
    Analyse un slide en utilisant uniquement le texte extrait, sans Vision.
    Plus rapide et moins coûteux que la version avec Vision.
    """
    # Heartbeat avant l'appel LLM
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat

        send_worker_heartbeat()
    except Exception:
        pass

    doc_type = document_type or "default"
    slide_prompt_id, slide_template = select_prompt(PROMPT_REGISTRY, doc_type, "slide")

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
                                    "prompts_version": PROMPT_REGISTRY.get(
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


# Analyse d'un slide via GPT + image, retourne les chunks enrichis
def ask_gpt_slide_analysis(
    image_path,
    deck_summary,
    slide_index,
    source_name,
    text,
    notes,
    megaparse_content="",
    document_type="default",
    deck_prompt_id="unknown",
    document_context_prompt=None,
    retries=2,
):
    # Heartbeat avant l'appel LLM vision (long processus)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat

        send_worker_heartbeat()
    except Exception:
        pass  # Ignorer si pas dans un contexte RQ

    img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    doc_type = document_type or "default"
    slide_prompt_id, slide_template = select_prompt(PROMPT_REGISTRY, doc_type, "slide")
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

            # === NOUVEAU: Support format unifié 4 outputs {"concepts": [...], "facts": [...], "entities": [...], "relations": [...]} ===
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
                                    "prompts_version": PROMPT_REGISTRY.get(
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
    image_path,
    slide_index,
    source_name,
    text="",
    notes="",
    megaparse_content="",
    retries=2,
):
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
        retries: Nombre de tentatives en cas d'erreur

    Returns:
        str: Résumé riche et détaillé de la slide (2-4 paragraphes)
    """
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
            import re

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


# Ingestion des chunks dans Qdrant avec schéma canonique
def ingest_chunks(chunks, doc_meta, file_uid, slide_index, deck_summary):
    # Filtrer les slides non informatifs
    excluded_roles = {"title", "transition", "agenda"}

    valid = []
    for ch in chunks:
        if not ch.get("full_explanation", "").strip():
            continue

        meta = ch.get("meta", {})
        slide_role = meta.get("slide_role", "")

        # Exclure les slides de type title, transition, agenda
        if slide_role in excluded_roles:
            logger.info(
                f"Slide {slide_index}: skipping chunk with slide_role '{slide_role}'"
            )
            continue

        valid.append(ch)

    if not valid:
        logger.info(f"Slide {slide_index}: no valid chunks after filtering")
        return
    texts = [ch["full_explanation"] for ch in valid]
    embs = embed_texts(texts)
    points = []
    for ch, emb in zip(valid, embs):
        meta = ch.get("meta", {})
        payload = {
            "text": ch["full_explanation"].strip(),
            "language": get_language_iso2(ch["full_explanation"]),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "document": {
                "source_name": f"{file_uid}.pptx",
                "source_type": "pptx",
                "source_file_url": f"{PUBLIC_URL}/static/presentations/{file_uid}.pptx",
                "slide_image_url": f"{PUBLIC_URL}/static/thumbnails/{file_uid}_slide_{slide_index}.jpg",
                "title": doc_meta.get("title", ""),
                "objective": doc_meta.get("objective", ""),
                "audience": doc_meta.get("audience", []),
                "source_date": doc_meta.get("source_date", ""),
                "all_mentioned_solutions": doc_meta.get(
                    "mentioned_solutions", []
                ),  # Solutions globales du deck entier
            },
            "solution": {
                "main": doc_meta.get("main_solution", ""),
                "family": doc_meta.get("family", ""),
                "supporting": doc_meta.get("supporting_solutions", []),
                "mentioned": meta.get(
                    "mentioned_solutions", []
                ),  # Utiliser les solutions spécifiques de ce chunk/slide
                "version": doc_meta.get("version", ""),
                "deployment_model": doc_meta.get("deployment_model", ""),
            },
            "chunk": {
                "scope": meta.get("scope", "solution-specific"),
                "slide_index": slide_index,
                "type": meta.get("type", ""),
                "level": meta.get("level", ""),
                "tags": meta.get("tags", []),
            },
            "deck_summary": deck_summary,
            "prompt_meta": ch.get("prompt_meta", {}),
        }
        points.append(PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload))
    qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=points)
    logger.info(f"Slide {slide_index}: ingested {len(points)} chunks")


def load_document_type_context(document_type_id: str | None) -> str | None:
    """
    Charge le context_prompt depuis la DB pour un document_type_id donné.

    Args:
        document_type_id: ID du DocumentType (peut être None ou "default")

    Returns:
        context_prompt si trouvé, None sinon
    """
    if not document_type_id or document_type_id == "default":
        logger.info(
            "📋 Pas de document_type_id spécifique, utilisation prompts par défaut"
        )
        return None

    try:
        db = SessionLocal()
        try:
            doc_type = (
                db.query(DocumentType)
                .filter(DocumentType.id == document_type_id)
                .first()
            )
            if doc_type and doc_type.context_prompt:
                logger.info(
                    f"✅ Context prompt chargé depuis DocumentType '{doc_type.name}' ({len(doc_type.context_prompt)} chars)"
                )
                return doc_type.context_prompt
            else:
                logger.warning(
                    f"⚠️ DocumentType {document_type_id} trouvé mais sans context_prompt"
                )
                return None
        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Erreur chargement context_prompt depuis DB: {e}")
        return None


# Fonction principale pour traiter un fichier PPTX
def process_pptx(
    pptx_path: Path,
    document_type_id: str | None = None,
    progress_callback=None,
    rq_job=None,
    use_vision: bool = True,
):
    # Reconfigurer logger pour le contexte RQ worker avec lazy file creation
    global logger
    logger = setup_logging(LOGS_DIR, "ingest_debug.log", enable_console=False)

    # Premier log réel - c'est ici que le fichier sera créé
    logger.info(f"start ingestion for {pptx_path.name}")
    logger.info(f"📋 Document Type ID: {document_type_id or 'default'}")
    logger.info(
        f"🔍 Mode extraction: {'VISION (GPT-4 avec images)' if use_vision else 'TEXT-ONLY (LLM rapide)'}"
    )

    # Charger le context_prompt personnalisé depuis la DB
    document_context_prompt = load_document_type_context(document_type_id)

    # Générer ID unique pour cet import (pour traçabilité dans Neo4j)
    import_id = str(uuid.uuid4())[:8]  # UUID court pour lisibilité

    # Obtenir le job RQ actuel si pas fourni
    if rq_job is None:
        try:
            from rq import get_current_job

            rq_job = get_current_job()
        except Exception:
            rq_job = None  # Pas de job RQ, mode standalone

    if progress_callback:
        progress_callback("Préparation", 2, 100, "Suppression des slides cachés")

    # Supprimer les slides cachés DIRECTEMENT du PPTX uploadé
    remove_hidden_slides_inplace(pptx_path)

    # === PHASE 1 : DOCUMENT BACKBONE - Checksum & Duplicate Detection ===
    logger.info(f"Phase 1: Calcul checksum et vérification duplicatas...")

    if progress_callback:
        progress_callback("Vérification duplicatas", 3, 100, "Calcul checksum SHA256")

    # Calculer checksum du document
    checksum = calculate_checksum(pptx_path)

    # Initialiser DocumentRegistryService (crée sa propre connexion Neo4j)
    doc_registry = DocumentRegistryService(tenant_id="default")

    # ===== DÉSACTIVÉ TEMPORAIREMENT POUR DEBUG =====
    # Vérifier si document déjà ingéré (duplicate detection)
    # try:
    #     existing_version = doc_registry.get_version_by_checksum(checksum)
    #     if existing_version:
    #         logger.warning(f"Document DUPLICATE détecté: {pptx_path.name}")
    #         logger.warning(f"   Checksum: {checksum[:16]}...")
    #         logger.warning(f"   Document existant: {existing_version.document_id}")
    #         logger.warning(f"   Version existante: {existing_version.version_label}")
    #         logger.warning(f"   Date source: {existing_version.source_date or 'N/A'}")
    #         logger.warning(f"   SKIP INGESTION (document déjà présent dans la base)")
    #
    #         doc_registry.close()
    #
    #         # Déplacer quand même vers docs_done pour éviter re-tentatives
    #         logger.info(f"Déplacement du fichier vers docs_done (already processed)...")
    #         shutil.move(str(pptx_path), DOCS_DONE / f"{pptx_path.stem}.pptx")
    #
    #         if progress_callback:
    #             progress_callback("Terminé (duplicata)", 100, 100, "Document déjà présent - ignoré")
    #
    #         return {
    #             "chunks_inserted": 0,
    #             "status": "skipped_duplicate",
    #             "existing_document_id": existing_version.document_id,
    #             "checksum": checksum,
    #             "message": f"Document duplicate of {existing_version.document_id}"
    #         }
    # except ValueError as e:
    #     # Aucun duplicata trouvé (comportement normal)
    #     logger.info(f"Aucun duplicata détecté - Poursuite de l'ingestion")

    # DEBUG MODE: Skip duplicate detection - always process
    logger.warning(
        f"⚠️ DEBUG MODE: Duplicate detection DISABLED - processing {pptx_path.name}"
    )
    try:
        pass  # Placeholder pour garder la structure try/except
    except Exception as e:
        # Erreur inattendue lors de la vérification
        logger.error(f"Erreur vérification duplicatas: {e}")
        logger.info(f"Poursuite de l'ingestion par sécurité")

    # ===== CACHE CHECK - Skip extraction si cache disponible =====
    logger.info("[CACHE] Vérification cache extraction...")

    from knowbase.ingestion.extraction_cache import get_cache_manager
    cache_manager = get_cache_manager()

    cached_extraction = cache_manager.get_cache_for_file(pptx_path)

    if cached_extraction:
        logger.info("[CACHE] ✅ CACHE HIT - Skip extraction (PDF conversion + Vision)")
        logger.info(f"[CACHE]    Texte: {cached_extraction.extracted_text.length_chars} chars")
        logger.info(f"[CACHE]    Économie: ${cached_extraction.extraction_stats.cost_usd:.3f}")
        logger.info(f"[CACHE]    Vision calls évités: {cached_extraction.extraction_stats.vision_calls}")

        # Charger données depuis cache
        full_text_enriched = cached_extraction.extracted_text.full_text
        metadata = {
            "title": cached_extraction.document_metadata.title,
            "pages": cached_extraction.document_metadata.pages,
            "language": cached_extraction.document_metadata.language,
            "author": cached_extraction.document_metadata.author,
            "keywords": cached_extraction.document_metadata.keywords,
        }

        if progress_callback:
            progress_callback("Cache loaded", 60, 100, "Extraction chargée depuis cache")

        # Sauter directement à OSMOSE (après la ligne 2252 où cache est normalement sauvegardé)
        logger.info("[CACHE] Skip vers OSMOSE Pipeline...")

        # IMPORTANT: On a besoin de slides_data minimal pour la suite
        # On peut le reconstituer depuis cache.extracted_text.pages
        slides_data = []
        slide_summaries = []

        for page_data in cached_extraction.extracted_text.pages:
            slide_idx = page_data.get("slide_index", 0)
            text = page_data.get("text", "")

            slides_data.append({
                "slide_index": slide_idx,
                "text": text,
                "megaparse_content": None  # Pas besoin pour OSMOSE
            })

            slide_summaries.append({
                "slide_index": slide_idx,
                "summary": text
            })

        # Skip conversion PDF et extraction (économie temps + $$$)
        pdf_path = None  # Pas généré si cache

    else:
        # PAS DE CACHE - Faire extraction normale
        logger.info("[CACHE] CACHE MISS - Extraction normale (PDF + Vision)")

        if progress_callback:
            progress_callback("Conversion PDF", 5, 100, "Conversion du PowerPoint en PDF")

        ensure_dirs()
        pdf_path = convert_pptx_to_pdf(pptx_path, SLIDES_PNG)
        slides_data = extract_notes_and_text(pptx_path)

    if progress_callback:
        progress_callback(
            "Analyse du contenu", 10, 100, "Analyse du contenu et génération du résumé"
        )

    # Extraction automatique des métadonnées PPTX (date de modification, titre, etc.)
    auto_metadata = extract_pptx_metadata(pptx_path)

    deck_info = analyze_deck_summary(
        slides_data,
        pptx_path.name,
        document_type=document_type_id or "default",
        auto_metadata=auto_metadata,
        document_context_prompt=document_context_prompt,
    )
    summary = deck_info.get("summary", "")
    metadata = deck_info.get("metadata", {})
    deck_prompt_id = deck_info.get("_prompt_meta", {}).get("deck_prompt_id", "unknown")

    # === PHASE 1 : DOCUMENT BACKBONE - Create Document + DocumentVersion ===
    logger.info(f"Phase 1: Création Document + DocumentVersion dans Neo4j...")

    if progress_callback:
        progress_callback(
            "Création Document", 12, 100, "Enregistrement document dans Neo4j"
        )

    try:
        # Import schemas nécessaires
        from knowbase.api.schemas.documents import (
            DocumentCreate,
            DocumentVersionCreate,
            DocumentType as DocType,
        )

        # Préparer les metadata pour le document
        document_title = (
            metadata.get("title") or auto_metadata.get("title") or pptx_path.stem
        )
        source_date_str = metadata.get("source_date") or auto_metadata.get(
            "source_date"
        )
        creator = auto_metadata.get("creator", "Unknown")
        version_label = auto_metadata.get("version", "v1.0")

        # Créer le document d'abord
        doc_create = DocumentCreate(
            title=document_title,
            source_path=str(pptx_path),
            document_type=DocType.PPTX,
            tenant_id="default",
            description=summary[:500] if summary else None,
            metadata={
                "import_id": import_id,
                "main_solution": metadata.get("main_solution"),
                "supporting_solutions": metadata.get("supporting_solutions", []),
                "objective": metadata.get("objective"),
                "audience": metadata.get("audience", []),
                "language": metadata.get("language"),
                "company": auto_metadata.get("company"),
                "last_modified_by": auto_metadata.get("last_modified_by"),
                "revision": auto_metadata.get("revision"),
            },
        )

        document_response = doc_registry.create_document(doc_create)
        document_id = document_response.document_id

        # Créer la version initiale
        from datetime import datetime, timezone

        effective_date = (
            datetime.fromisoformat(source_date_str)
            if source_date_str
            else datetime.now(timezone.utc)
        )

        version_create = DocumentVersionCreate(
            document_id=document_id,
            version_label=version_label,
            effective_date=effective_date,
            checksum=checksum,
            file_size=pptx_path.stat().st_size,
            author_name=creator,
            metadata={
                "source_date": source_date_str,
                "modified_at": auto_metadata.get("modified_at"),
                "created_at": auto_metadata.get("created_at"),
            },
        )

        version_response = doc_registry.create_version(version_create)
        document_version_id = version_response.version_id

        logger.info(f"Document créé: {document_id}")
        logger.info(f"   Version: {version_label} (ID: {document_version_id})")
        logger.info(f"   Checksum: {checksum[:16]}...")
        logger.info(f"   Titre: {document_title}")

    except Exception as e:
        logger.error(f"Erreur création Document dans Neo4j: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        # Ne pas bloquer l'ingestion si erreur Neo4j
        document_id = None
        document_version_id = None

    # ===== IMAGE GENERATION & VISION (Skip si cache) =====
    if pdf_path:
        # PDF disponible → Génération images + Vision
        if progress_callback:
            progress_callback(
                "Génération des miniatures", 15, 100, "Conversion PDF → images en cours"
            )

        # Génération d'images avec DPI adaptatif selon la taille du document
        if len(slides_data) > 400:
            # Gros documents : DPI réduit pour économiser la mémoire
            dpi = 120
            logger.info(
                f"📊 Gros document ({len(slides_data)} slides) - DPI réduit à {dpi} pour économiser la mémoire"
            )
        elif len(slides_data) > 200:
            dpi = 150
            logger.info(f"📊 Document moyen ({len(slides_data)} slides) - DPI à {dpi}")
        else:
            dpi = 200
            logger.info(
                f"📊 Document normal ({len(slides_data)} slides) - DPI standard à {dpi}"
            )

        # Méthode unifiée avec PyMuPDF : toujours convertir tout d'un coup (plus efficace)
        try:
            images = convert_pdf_to_images_pymupdf(str(pdf_path), dpi=dpi, rq_job=rq_job)
            image_paths = {}

            for i, img in enumerate(images, start=1):
                img_path = THUMBNAILS_DIR / f"{pptx_path.stem}_slide_{i}.jpg"

                # Sauvegarder l'image pour le LLM
                if img.mode == "RGBA":
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1])
                    rgb_img.save(img_path, "JPEG", quality=60, optimize=True)
                else:
                    img.save(img_path, "JPEG", quality=60, optimize=True)

                image_paths[i] = img_path

                # Heartbeat périodique pour gros documents + libération mémoire
                if len(slides_data) > 200 and i % 100 == 0:
                    try:
                        from knowbase.ingestion.queue.jobs import send_worker_heartbeat

                        send_worker_heartbeat()
                        logger.debug(
                            f"Heartbeat envoyé après génération de {i}/{len(images)} images"
                        )
                    except Exception:
                        pass

            # Libérer la liste d'images après traitement
            del images
            logger.info(f"✅ {len(image_paths)} images générées avec succès")

        except Exception as e:
            logger.error(f"❌ Erreur génération d'images: {e}")
            raise

        logger.info(f"🔄 Début traitement LLM des slides...")

    else:
        # Cache HIT - Pas d'images générées
        logger.info("[CACHE] Skip image generation (cache loaded)")
        image_paths = {}

    # === VISION PROCESSING (Skip si cache) ===
    if pdf_path:
        # PDF disponible → Vision processing
        actual_slide_count = len(image_paths)
        total_slides = len(slides_data)  # Corriger la variable manquante
        # MAX_WORKERS est défini globalement depuis .env (ligne 58)

        if progress_callback:
            progress_callback(
                "Génération des miniatures",
                18,
                100,
                f"Création de {actual_slide_count} miniatures",
            )
    
        # ===== OSMOSE PURE : Vision génère résumés riches =====
        # Au lieu d'extraire entities/relations, Vision décrit visuellement chaque slide
        # OSMOSE fera ensuite l'analyse sémantique sur ces résumés
    
        actual_workers = 1 if total_slides > 400 else MAX_WORKERS
        logger.info(
            f"📊 [OSMOSE PURE] Utilisation de {actual_workers} workers pour {total_slides} slides"
        )
        logger.info(f"📊 [OSMOSE PURE] use_vision = {use_vision}")
        logger.info(f"📊 [OSMOSE PURE] image_paths count = {len(image_paths)}")
        logger.info(f"📊 [OSMOSE PURE] slides_data count = {len(slides_data)}")
    
        vision_tasks = []
        logger.info(
            f"🤖 [OSMOSE PURE] Soumission de {len(slides_data)} tâches Vision (résumés)..."
        )
    
        with ThreadPoolExecutor(max_workers=actual_workers) as ex:
            for slide in slides_data:
                idx = slide["slide_index"]
                raw_text = slide.get("text", "")
                notes = slide.get("notes", "")
                megaparse_content = slide.get("megaparse_content", raw_text)
    
                if idx in image_paths:
                    # Mode OSMOSE Pure: Vision génère résumé riche
                    if use_vision:
                        vision_tasks.append(
                            (
                                idx,
                                ex.submit(
                                    ask_gpt_vision_summary,  # Nouvelle fonction
                                    image_paths[idx],
                                    idx,
                                    pptx_path.name,
                                    raw_text,
                                    notes,
                                    megaparse_content,
                                ),
                            )
                        )
                    else:
                        # Fallback texte brut
                        vision_tasks.append((idx, None))  # Pas de Vision, texte direct
    
        total_slides_with_vision = len([t for t in vision_tasks if t[1] is not None])
        logger.info(
            f"🚀 [OSMOSE PURE] Début génération de {total_slides_with_vision} résumés Vision"
        )
    
        if progress_callback:
            progress_callback(
                "Analyse Vision",
                20,
                100,
                f"Génération résumés visuels ({total_slides_with_vision} slides)",
            )
    
        # Collecter les résumés
        slide_summaries = []
    
        for i, (idx, future) in enumerate(vision_tasks):
            slide_progress = 20 + int((i / len(vision_tasks)) * 40)  # 20% → 60%
            if progress_callback:
                progress_callback(
                    "Analyse Vision",
                    slide_progress,
                    100,
                    f"Slide {i+1}/{len(vision_tasks)}",
                )
    
            if future is not None:
                # Attendre résumé Vision
                try:
                    import concurrent.futures
                    import time
    
                    timeout_seconds = 60
                    start_time = time.time()
    
                    while not future.done():
                        try:
                            summary = future.result(timeout=timeout_seconds)
                            break
                        except concurrent.futures.TimeoutError:
                            # Heartbeat
                            elapsed = time.time() - start_time
                            if elapsed > 300:  # 5 minutes max
                                logger.warning(
                                    f"Slide {idx} [VISION SUMMARY]: Timeout après 5min"
                                )
                                summary = f"Slide {idx}: timeout"
                                break
                            try:
                                from knowbase.ingestion.queue.jobs import (
                                    send_worker_heartbeat,
                                )
    
                                send_worker_heartbeat()
                            except Exception:
                                pass
    
                    if not future.done():
                        logger.error(
                            f"Slide {idx} [VISION SUMMARY]: Future n'est pas done après attente"
                        )
                        summary = f"Slide {idx}: erreur"
                    else:
                        summary = future.result()
    
                except Exception as e:
                    logger.error(
                        f"Slide {idx} [VISION SUMMARY]: Erreur récupération résultat: {e}"
                    )
                    # Fallback texte
                    slide_data = slides_data[i] if i < len(slides_data) else {}
                    summary = f"Slide {idx}: {slide_data.get('text', '')} {slide_data.get('notes', '')}"
    
            else:
                # Pas de Vision, utiliser texte brut
                slide_data = slides_data[i] if i < len(slides_data) else {}
                text = slide_data.get("text", "")
                notes = slide_data.get("notes", "")
                summary = f"{text}\n{notes}".strip() or f"Slide {idx}"
    
            # Ajouter à la collection
            slide_summaries.append({"slide_index": idx, "summary": summary})
    
            logger.info(f"Slide {idx} [VISION SUMMARY]: {len(summary)} chars collectés")
    
            # Heartbeat périodique
            if (i + 1) % 3 == 0:
                try:
                    from knowbase.ingestion.queue.jobs import send_worker_heartbeat
    
                    send_worker_heartbeat()
                except Exception:
                    pass
    
        logger.info(f"✅ [OSMOSE PURE] {len(slide_summaries)} résumés Vision collectés")
    
        # ===== Construire texte complet enrichi =====
        logger.info("[OSMOSE PURE] Construction du texte enrichi complet...")
    
        full_text_parts = []
        for slide_summary in slide_summaries:
            idx = slide_summary["slide_index"]
            summary = slide_summary["summary"]
            full_text_parts.append(f"\n--- Slide {idx} ---\n{summary}")
    
        full_text_enriched = "\n\n".join(full_text_parts)
    
        logger.info(
            f"[OSMOSE PURE] Texte enrichi construit: {len(full_text_enriched)} chars depuis {len(slide_summaries)} slides"
        )
    
        # 🔍 DEBUG: Confirmer que le code continue après construction texte enrichi
        logger.info(
            "[DEBUG] 🎯 Checkpoint A: Après construction texte enrichi, avant aperçu"
        )
    
        # Afficher aperçu du texte enrichi pour validation
        preview_length = min(1000, len(full_text_enriched))
        logger.info("[DEBUG] 🎯 Checkpoint B: preview_length calculé")
        logger.info(
            f"[OSMOSE PURE] Aperçu texte enrichi (premiers {preview_length} chars):"
        )
        logger.info("=" * 80)
        logger.info(
            full_text_enriched[:preview_length]
            + ("..." if len(full_text_enriched) > preview_length else "")
        )
        logger.info("=" * 80)
        logger.info("[DEBUG] 🎯 Checkpoint C: Après aperçu texte enrichi")

    else:
        # Deux cas possibles ici:
        # 1. Cache HIT - Texte enrichi déjà chargé depuis cache (full_text_enriched existe)
        # 2. Fallback TEXT-ONLY - LibreOffice a crashé, pas de PDF, pas de Vision (full_text_enriched n'existe pas)

        if cached_extraction:
            # Cas 1: Cache HIT
            logger.info("[CACHE] ✅ Texte enrichi déjà disponible depuis cache")
            logger.info(f"[CACHE]    {len(full_text_enriched)} chars, {len(slide_summaries)} slides")
        else:
            # Cas 2: Fallback TEXT-ONLY - Construire full_text_enriched depuis texte brut
            logger.info("[FALLBACK] 📋 Mode TEXT-ONLY activé (LibreOffice failed)")
            logger.info(f"[FALLBACK] Construction texte enrichi depuis {len(slides_data)} slides (texte brut)")

            full_text_parts = []
            slide_summaries = []

            for slide in slides_data:
                idx = slide["slide_index"]
                text = slide.get("text", "")
                notes = slide.get("notes", "")

                # Combiner texte + notes pour un contenu plus riche
                combined = text
                if notes:
                    combined += f"\n[Notes: {notes}]"

                full_text_parts.append(f"\n--- Slide {idx} ---\n{combined}")
                slide_summaries.append({"slide_index": idx, "summary": combined})

            full_text_enriched = "\n\n".join(full_text_parts)

            logger.info(f"[FALLBACK] ✅ Texte enrichi construit: {len(full_text_enriched)} chars depuis {len(slide_summaries)} slides")
            logger.info(f"[FALLBACK] ⚠️ Pas d'enrichissement Vision (économie API, qualité réduite)")

    # Point de convergence: full_text_enriched est prêt (cache OU Vision)

    if progress_callback:
        progress_callback("Préparation OSMOSE", 65, 100, "Texte enrichi construit")
        logger.info("[DEBUG] 🎯 Checkpoint D: Après progress_callback")

    # ===== V2.2 - SAUVEGARDE CACHE EXTRACTION =====
    # Sauvegarder cache AVANT OSMOSE pour permettre rejeux rapides
    # (Uniquement si extraction normale, pas si cache chargé)
    if pdf_path:
        logger.info("[CACHE] Sauvegarde du cache d'extraction...")
        try:
            cache_manager = get_cache_manager()

            # Préparer les données cache
            extraction_stats = {
                "duration_seconds": time.time() - time.time(),  # TODO: tracker start_time réel
                "vision_calls": len([s for s in slide_summaries if len(s.get("summary", "")) > 100]),
                "cost_usd": 0.0,  # TODO: tracker coût extraction
                "megaparse_blocks": sum(1 for s in slides_data if s.get("megaparse_content"))
            }

            extraction_config = {
                "use_vision": use_vision,
                "document_type_id": document_type_id,
                "total_slides": len(slides_data)
            }

            # Sauvegarder cache
            cache_path = cache_manager.save_cache(
                source_file_path=pptx_path,
                extracted_text=full_text_enriched,
                document_metadata=metadata,
                extraction_config=extraction_config,
                extraction_stats=extraction_stats,
                page_texts=[{"slide_index": s["slide_index"], "text": s["summary"]} for s in slide_summaries]
            )

            if cache_path:
                logger.info(f"[CACHE] ✅ Cache saved successfully: {cache_path.name}")
        except Exception as e:
            logger.warning(f"[CACHE] ⚠️ Failed to save cache (non-critical): {e}")
    else:
        logger.info("[CACHE] Skip sauvegarde (cache déjà utilisé)")

    # ===== OSMOSE Pipeline V2.1 - Analyse Sémantique =====
    logger.info("=" * 80)
    logger.info(
        "[OSMOSE PURE] Lancement du traitement sémantique (remplace ingestion legacy)"
    )
    logger.info("=" * 80)
    logger.info("[DEBUG] 🎯 Checkpoint E: Avant try block OSMOSE")

    try:
        logger.info("[DEBUG] 🎯 Checkpoint F: Dans try block, avant import")
        from knowbase.ingestion.osmose_agentique import (
            process_document_with_osmose_agentique,
        )
        import asyncio

        logger.info("[DEBUG] 🎯 Checkpoint G: Imports OK, avant condition")

        logger.info(
            f"[DEBUG] 🔍 full_text_enriched type: {type(full_text_enriched)}, len: {len(full_text_enriched) if full_text_enriched else 'None'}"
        )

        if full_text_enriched and len(full_text_enriched) >= 100:
            logger.info(
                "[DEBUG] 🎯 Checkpoint H: Condition OSMOSE validée, entrée dans bloc"
            )
            if progress_callback:
                progress_callback(
                    "OSMOSE Semantic",
                    70,
                    100,
                    "Extraction concepts canoniques cross-linguals",
                )

            # Appeler OSMOSE Agentique (SupervisorAgent FSM) de manière asynchrone
            logger.info(
                "[DEBUG] 🎯 Checkpoint I: Avant asyncio.run(process_document_with_osmose_agentique)"
            )
            osmose_result = asyncio.run(
                process_document_with_osmose_agentique(
                    document_id=pptx_path.stem,
                    document_title=pptx_path.name,
                    document_path=pptx_path,
                    text_content=full_text_enriched,  # Résumés Vision enrichis
                    tenant_id="default",
                )
            )
            logger.info(
                f"[DEBUG] 🎯 Checkpoint J: Après asyncio.run, osmose_result.osmose_success={osmose_result.osmose_success}"
            )

            if osmose_result.osmose_success:
                logger.info(
                    "[DEBUG] 🎯 Checkpoint K: OSMOSE Success, affichage résultats"
                )
                logger.info("=" * 80)
                logger.info(
                    f"[OSMOSE PURE] ✅ Traitement réussi:\n"
                    f"  - {osmose_result.canonical_concepts} concepts canoniques\n"
                    f"  - {osmose_result.concept_connections} connexions cross-documents\n"
                    f"  - {osmose_result.topics_segmented} topics segmentés\n"
                    f"  - Proto-KG: {osmose_result.proto_kg_concepts_stored} concepts + "
                    f"{osmose_result.proto_kg_relations_stored} relations + "
                    f"{osmose_result.proto_kg_embeddings_stored} embeddings\n"
                    f"  - Durée: {osmose_result.osmose_duration_seconds:.1f}s"
                )
                logger.info("=" * 80)

                if progress_callback:
                    progress_callback(
                        "OSMOSE Complete",
                        95,
                        100,
                        f"{osmose_result.canonical_concepts} concepts canoniques extraits",
                    )

            else:
                error_msg = f"OSMOSE processing failed: {osmose_result.osmose_error}"
                logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
                if progress_callback:
                    progress_callback("Erreur OSMOSE", 70, 100, error_msg)
                raise Exception(error_msg)

        else:
            logger.info("[DEBUG] 🎯 Checkpoint X: ELSE - Condition OSMOSE échouée")
            error_msg = f"Text too short ({len(full_text_enriched) if full_text_enriched else 0} chars)"
            logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
            if progress_callback:
                progress_callback("Erreur", 70, 100, error_msg)
            raise Exception(error_msg)

    except Exception as e:
        # En mode OSMOSE Pure, une erreur OSMOSE = échec complet de l'ingestion
        logger.info(
            f"[DEBUG] 🎯 Checkpoint Z: EXCEPTION catchée: {type(e).__name__}: {str(e)[:100]}"
        )
        logger.error(
            f"[OSMOSE PURE] ❌ Erreur traitement sémantique: {e}", exc_info=True
        )
        if progress_callback:
            progress_callback("Erreur OSMOSE", 0, 100, str(e))
        raise  # Re-raise pour arrêter le traitement

    # ===== Fin OSMOSE Pure =====

    # Heartbeat final avant finalisation
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat

        send_worker_heartbeat()
        logger.debug("Heartbeat envoyé avant finalisation")
    except Exception:
        pass

    logger.info(f"📁 Déplacement du fichier vers docs_done...")
    shutil.move(str(pptx_path), DOCS_DONE / f"{pptx_path.stem}.pptx")

    if progress_callback:
        progress_callback("Terminé", 100, 100, f"Import terminé - OSMOSE Pure activé")

    logger.info(f"🎉 INGESTION TERMINÉE - {pptx_path.name} - OSMOSE Pure")
    logger.info(
        f"📊 Métriques: {osmose_result.canonical_concepts} concepts canoniques, "
        f"{osmose_result.proto_kg_concepts_stored} stockés dans Proto-KG"
    )

    logger.info(f"Done {pptx_path.name} — OSMOSE Pure mode")

    return {
        "osmose_pure": True,
        "canonical_concepts": osmose_result.canonical_concepts,
        "concept_connections": osmose_result.concept_connections,
        "proto_kg_concepts_stored": osmose_result.proto_kg_concepts_stored,
        "proto_kg_relations_stored": osmose_result.proto_kg_relations_stored,
        "proto_kg_embeddings_stored": osmose_result.proto_kg_embeddings_stored,
    }


# Fusionne plusieurs dictionnaires de métadonnées et normalise les solutions
def merge_metadata(meta_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged = {
        "main_solution": "",
        "supporting_solutions": [],
        "mentioned_solutions": [],
        "document_type": "",
        "audience": [],
        "source_date": "",
        "language": "",
        "objective": "",
        "title": "",
        "version": "",
        "family": "",
        "deployment_model": "",
    }
    for meta in meta_list:
        for k in ["supporting_solutions", "mentioned_solutions", "audience"]:
            merged[k].extend(meta.get(k, []))
        for k in [
            "main_solution",
            "document_type",
            "source_date",
            "language",
            "objective",
            "title",
            "version",
            "family",
            "deployment_model",
        ]:
            if not merged[k] and meta.get(k):
                merged[k] = meta[k]
    for k in ["supporting_solutions", "mentioned_solutions", "audience"]:
        merged[k] = list(set(merged[k]))
    if merged.get("main_solution"):
        sol_id, canon = normalize_solution_name(merged["main_solution"])
        merged["main_solution_id"] = sol_id
        merged["main_solution"] = canon or merged["main_solution"]
    else:
        merged["main_solution_id"] = "UNMAPPED"
    normalized_supporting = []
    for supp in merged["supporting_solutions"]:
        sid, canon = normalize_solution_name(supp)
        normalized_supporting.append(canon or supp)
    merged["supporting_solutions"] = list(set(normalized_supporting))
    normalized_mentioned = []
    for ment in merged["mentioned_solutions"]:
        sid, canon = normalize_solution_name(ment)
        normalized_mentioned.append(canon or ment)
    merged["mentioned_solutions"] = list(set(normalized_mentioned))
    return merged


# Point d'entrée principal du script
def main():
    ensure_dirs()
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("pptx_path", type=str, help="Chemin du fichier PPTX à ingérer")
    parser.add_argument(
        "--document-type",
        type=str,
        default=None,
        help="Type de document pour le choix des prompts",
    )
    args = parser.parse_args()
    pptx_path = Path(args.pptx_path)
    document_type = args.document_type
    if document_type is None:
        meta_path = pptx_path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                document_type = meta.get("document_type", "default")
            except Exception as e:
                logger.warning(
                    f"Impossible de lire le document_type depuis {meta_path}: {e}"
                )
                document_type = "default"
        else:
            document_type = "default"
    if pptx_path.exists():
        process_pptx(pptx_path, document_type=document_type)
    else:
        logger.error(f"File not found: {pptx_path}")


if __name__ == "__main__":
    main()
