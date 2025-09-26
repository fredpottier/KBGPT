# ingest_pptx_via_gpt.py — version améliorée avec contexte global & thumbnails

import base64
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from knowbase.common.sap.normalizer import normalize_solution_name

from langdetect import detect, DetectorFactory, LangDetectException
from pdf2image import convert_from_path
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

logger = setup_logging(LOGS_DIR, "ingest_debug.log")
DetectorFactory.seed = 0

# Patch unstructured pour éviter HTTP 403 avant l'import MegaParse
try:
    exec(open('/app/patch_unstructured.py').read())
except Exception as e:
    logger.warning(f"Could not apply unstructured patch: {e}")

# Import conditionnel de MegaParse avec fallback (après définition du logger)
PPTX_FALLBACK = False  # Initialiser par défaut

try:
    from megaparse import MegaParse
    MEGAPARSE_AVAILABLE = True
    logger.info("✅ MegaParse disponible")

    # Même si MegaParse est disponible, vérifier python-pptx pour le fallback
    try:
        from pptx import Presentation
        PPTX_FALLBACK = True
        logger.info("✅ python-pptx disponible comme fallback")
    except ImportError:
        PPTX_FALLBACK = False
        logger.warning("⚠️ python-pptx non disponible pour fallback")

except ImportError as e:
    MEGAPARSE_AVAILABLE = False
    logger.warning(f"⚠️ MegaParse non disponible, fallback vers python-pptx: {e}")

    # Fallback vers python-pptx si disponible
    try:
        from pptx import Presentation
        PPTX_FALLBACK = True
        logger.info("✅ python-pptx disponible comme fallback")
    except ImportError:
        PPTX_FALLBACK = False
        logger.error("❌ Ni MegaParse ni python-pptx disponibles!")

PROMPT_REGISTRY = load_prompts()

# --- Fonctions utilitaires ---


def ensure_dirs():
    ensure_directories([
        DOCS_IN,
        DOCS_DONE,
        SLIDES_PNG,
        THUMBNAILS_DIR,
        STATUS_DIR,
        LOGS_DIR,
        MODELS_DIR,
    ])



# Exécute une commande système avec timeout
def run_cmd(cmd, timeout=120, env=None):
    try:
        subprocess.run(cmd, check=True, timeout=timeout, env=env)
        return True
    except Exception as e:
        logger.error(f"Command failed ({e}): {' '.join(cmd)}")
    return False


# Encode une image en base64
def encode_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


# Nettoie la réponse GPT (retire les balises Markdown) et valide le JSON
def clean_gpt_response(raw: str) -> str:
    import re
    import json

    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip()

    # Validation et réparation basique du JSON tronqué
    if s:
        try:
            # Test si le JSON est valide
            json.loads(s)
            return s
        except json.JSONDecodeError as e:
            logger.warning(f"JSON invalide détecté, tentative de réparation: {str(e)[:100]}")

            # Tentative de réparation simple pour JSON tronqué
            if s.endswith('"'):
                # JSON tronqué au milieu d'une string
                s = s + '}'
                if s.count('[') > s.count(']'):
                    s = s + ']'
            elif s.endswith(','):
                # JSON tronqué après une virgule
                s = s[:-1]  # Retirer la virgule
                if s.count('[') > s.count(']'):
                    s = s + ']'
                if s.count('{') > s.count('}'):
                    s = s + '}'
            elif not s.endswith((']', '}')):
                # JSON clairement tronqué
                if s.count('[') > s.count(']'):
                    s = s + ']'
                if s.count('{') > s.count('}'):
                    s = s + '}'

            # Test final de la réparation
            try:
                json.loads(s)
                logger.info("JSON réparé avec succès")
                return s
            except json.JSONDecodeError:
                logger.error("Impossible de réparer le JSON, retour d'un array vide")
                return "[]"

    return s


# Détecte la langue d'un texte (ISO2)
def get_language_iso2(text: str) -> str:
    try:
        return detect(text)
    except LangDetectException:
        return "en"


# Embedding des textes via SentenceTransformer
def embed_texts(texts: List[str]) -> List[List[float]]:
    batched = [f"passage: {t}" for t in texts]
    embeddings = model.encode(
        batched, normalize_embeddings=True, convert_to_numpy=True
    )
    return embeddings.tolist()


# Découpe les slides en batchs selon le nombre de tokens
def chunk_slides_by_tokens(slides_data, max_tokens):
    batches = []
    current_batch = []
    current_tokens = 0
    for slide in slides_data:
        slide_text = (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
        slide_tokens = estimate_tokens(slide_text)
        if current_tokens + slide_tokens > max_tokens and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(slide)
        current_tokens += slide_tokens
    if current_batch:
        batches.append(current_batch)
    return batches


# Estime le nombre de tokens dans un texte
def estimate_tokens(text: str) -> int:
    return int(len(text.split()) / 0.75)


# Normalise une URL publique
def normalize_public_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip().rstrip("/")
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    return u


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

MAX_TOKENS_THRESHOLD = 40000
MAX_PARTIAL_TOKENS = 8000
MAX_SUMMARY_TOKENS = 60000

# --- Fonctions principales du pipeline ---


# Convertit un PPTX en PDF via LibreOffice
# Retourne le chemin du PDF généré
def convert_pptx_to_pdf(pptx_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"📄 Conversion PPTX→PDF: {pptx_path.name}")

    # Envoyer heartbeat avant la conversion PDF (peut prendre plusieurs minutes)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
        logger.debug("Heartbeat envoyé avant conversion PDF")
    except Exception:
        pass  # Ignorer si pas dans un contexte RQ

    # Configuration environnement pour LibreOffice headless
    env = os.environ.copy()
    env.update({
        'HOME': '/tmp',
        'DISPLAY': '',
        'SAL_USE_VCLPLUGIN': 'svp',
    })

    # Commande de conversion avec retry
    command = [
        SOFFICE_PATH,
        "--headless",
        "--invisible",
        "--nodefault",
        "--nolockcheck",
        "--nologo",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(pptx_path),
    ]

    logger.debug(f"🔧 Commande LibreOffice: {' '.join(command)}")

    # Tentative de conversion avec environnement amélioré
    ok = run_cmd(command, timeout=600, env=env)

    pdf_path = output_dir / (pptx_path.stem + ".pdf")

    if not ok or not pdf_path.exists():
        # Log détaillé pour debugging
        logger.error(f"❌ Échec conversion PPTX→PDF:")
        logger.error(f"   - Fichier source: {pptx_path} (existe: {pptx_path.exists()})")
        logger.error(f"   - Répertoire sortie: {output_dir} (existe: {output_dir.exists()})")
        logger.error(f"   - PDF attendu: {pdf_path} (existe: {pdf_path.exists()})")
        logger.error(f"   - SOFFICE_PATH: {SOFFICE_PATH}")

        # Test direct du binaire
        test_ok = run_cmd([SOFFICE_PATH, "--version"], timeout=10, env=env)
        logger.error(f"   - Test binaire LibreOffice: {'OK' if test_ok else 'FAIL'}")

        raise RuntimeError("LibreOffice conversion failed or PDF missing")

    logger.debug(f"✅ PDF path: {pdf_path} (exists={pdf_path.exists()})")
    return pdf_path


# Extrait le contenu du PPTX avec MegaParse ou fallback python-pptx
def extract_notes_and_text(pptx_path: Path) -> List[Dict[str, Any]]:
    if MEGAPARSE_AVAILABLE:
        return extract_with_megaparse(pptx_path)
    elif PPTX_FALLBACK:
        return extract_with_python_pptx(pptx_path)
    else:
        logger.error(f"Aucun parser PPTX disponible pour {pptx_path.name}")
        return [{
            "slide_index": 1,
            "text": "Erreur: aucun parser PPTX disponible",
            "notes": "",
            "megaparse_content": "",
            "content_type": "error"
        }]


def extract_with_megaparse(pptx_path: Path) -> List[Dict[str, Any]]:
    """Extraction via MegaParse avec segmentation intelligente"""
    global PPTX_FALLBACK
    logger.info(f"📊 Extraction contenu PPTX via MegaParse: {pptx_path.name}")

    try:
        megaparse = MegaParse()
        parsed_content = megaparse.load(str(pptx_path))

        # MegaParse retourne le contenu structuré complet
        content_str = str(parsed_content) if not isinstance(parsed_content, str) else parsed_content

        # Tentative de segmentation intelligente du contenu
        slides_data = segment_megaparse_content(content_str, pptx_path.name)

        logger.debug(f"Slides segmentées via MegaParse: {len(slides_data)}")
        return slides_data

    except Exception as e:
        logger.error(f"❌ Erreur MegaParse pour {pptx_path.name}: {e}")
        # Fallback vers python-pptx si disponible
        if PPTX_FALLBACK:
            logger.info(f"Fallback vers python-pptx pour {pptx_path.name}")
            return extract_with_python_pptx(pptx_path)
        else:
            return [{
                "slide_index": 1,
                "text": f"Erreur d'extraction: {str(e)}",
                "notes": "",
                "megaparse_content": "",
                "content_type": "error"
            }]


def extract_with_python_pptx(pptx_path: Path) -> List[Dict[str, Any]]:
    """Extraction legacy via python-pptx"""
    logger.info(f"📊 Extraction contenu PPTX via python-pptx (legacy): {pptx_path.name}")

    try:
        prs = Presentation(str(pptx_path))
        slides_data = []
        for i, slide in enumerate(prs.slides, start=1):
            notes = ""
            if getattr(slide, "has_notes_slide", False):
                notes_slide = getattr(slide, "notes_slide", None)
                if notes_slide and hasattr(notes_slide, "notes_text_frame"):
                    tf = notes_slide.notes_text_frame
                    if tf and hasattr(tf, "text"):
                        notes = (tf.text or "").strip()
            texts = []
            for shape in slide.shapes:
                txt = getattr(shape, "text", None)
                if isinstance(txt, str) and txt.strip():
                    texts.append(txt.strip())
            text_content = "\n".join(texts)
            slides_data.append({
                "slide_index": i,
                "text": text_content,
                "notes": notes,
                "megaparse_content": text_content,  # Utiliser le texte comme fallback
                "content_type": "python_pptx_fallback"
            })
        logger.debug(f"Slides extraites via python-pptx: {len(slides_data)}")
        return slides_data
    except Exception as e:
        logger.error(f"❌ Erreur python-pptx pour {pptx_path.name}: {e}")
        return [{
            "slide_index": 1,
            "text": f"Erreur d'extraction python-pptx: {str(e)}",
            "notes": "",
            "megaparse_content": "",
            "content_type": "error"
        }]


# Segmente le contenu MegaParse en sections logiques
def segment_megaparse_content(content: str, source_name: str) -> List[Dict[str, Any]]:
    """
    Segmente le contenu MegaParse en sections logiques pour simulation de slides.
    Essaie de détecter les séparateurs de slides/sections dans le contenu.
    """

    # Indicateurs de séparation de slides (patterns communs dans MegaParse)
    slide_separators = [
        "---",           # Séparateur horizontal
        "Page ",         # Numérotation de page
        "Slide ",        # Slide explicite
        "\n\n\n",        # Triple saut de ligne
        "## ",           # Titre de section niveau 2
        "# ",            # Titre de section niveau 1
    ]

    segments = []
    current_segment = ""
    slide_index = 1

    lines = content.split('\n')

    for line in lines:
        # Vérifier si la ligne contient un séparateur de slide
        is_separator = any(sep in line for sep in slide_separators if sep != "\n\n\n")

        if is_separator and current_segment.strip():
            # Finaliser le segment actuel
            segments.append({
                "slide_index": slide_index,
                "text": current_segment.strip(),
                "notes": "",
                "megaparse_content": current_segment.strip(),
                "content_type": "segmented",
                "separator_found": True
            })
            slide_index += 1
            current_segment = line + "\n"
        else:
            current_segment += line + "\n"

    # Ajouter le dernier segment s'il existe
    if current_segment.strip():
        segments.append({
            "slide_index": slide_index,
            "text": current_segment.strip(),
            "notes": "",
            "megaparse_content": current_segment.strip(),
            "content_type": "segmented",
            "separator_found": False
        })

    # Si aucune segmentation n'a été trouvée, traiter comme un seul bloc
    if not segments or len(segments) == 1:
        # Découpage par taille pour éviter des chunks trop longs
        max_chars_per_segment = 4000

        if len(content) > max_chars_per_segment:
            # Découpage par paragraphes
            paragraphs = content.split('\n\n')
            current_chunk = ""
            slide_index = 1
            segments = []

            for para in paragraphs:
                if len(current_chunk + para) > max_chars_per_segment and current_chunk:
                    segments.append({
                        "slide_index": slide_index,
                        "text": current_chunk.strip(),
                        "notes": "",
                        "megaparse_content": current_chunk.strip(),
                        "content_type": "chunked_by_size"
                    })
                    slide_index += 1
                    current_chunk = para + "\n\n"
                else:
                    current_chunk += para + "\n\n"

            # Dernier chunk
            if current_chunk.strip():
                segments.append({
                    "slide_index": slide_index,
                    "text": current_chunk.strip(),
                    "notes": "",
                    "megaparse_content": current_chunk.strip(),
                    "content_type": "chunked_by_size"
                })
        else:
            # Contenu court, un seul segment
            segments = [{
                "slide_index": 1,
                "text": content,
                "notes": "",
                "megaparse_content": content,
                "content_type": "single_block"
            }]

    logger.debug(f"Segmentation MegaParse: {len(segments)} segments pour {source_name}")
    return segments


# Génère une miniature pour une image de slide
def generate_thumbnail(image_path: Path) -> Path:
    img = Image.open(image_path)
    img.thumbnail((1800, 1800), Image.Resampling.LANCZOS)

    # Changer l'extension vers .jpg pour compression
    thumb_name = image_path.stem + ".jpg"
    thumb_path = THUMBNAILS_DIR / thumb_name
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    # Sauvegarder en JPEG avec qualité réduite pour compenser la taille plus grande
    if img.mode == "RGBA":
        # Convertir RGBA en RGB pour JPEG
        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
        rgb_img.paste(img, mask=img.split()[-1])
        rgb_img.save(thumb_path, "JPEG", quality=60, optimize=True)
    else:
        img.save(thumb_path, "JPEG", quality=60, optimize=True)

    return thumb_path


# Découpe un texte en chunks avec chevauchement
def recursive_chunk(text: str, max_len=400, overlap_ratio=0.15) -> List[str]:
    tokens = text.split()
    step = int(max_len * (1 - overlap_ratio))
    chunks = []
    for i in range(0, len(tokens), step):
        chunk = tokens[i : i + max_len]
        chunks.append(" ".join(chunk))
        if i + max_len >= len(tokens):
            break
    return chunks


# Résume un deck PPTX trop volumineux en plusieurs passes GPT
def summarize_large_pptx(slides_data: List[Dict[str, Any]]) -> str:
    all_text = "\n\n".join(
        (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
        for slide in slides_data
        if slide.get("text", "") or slide.get("notes", "")
    )
    total_tokens = estimate_tokens(all_text)
    if total_tokens <= MAX_TOKENS_THRESHOLD:
        return all_text
    document_type = "generic"
    deck_prompt_id, deck_template = select_prompt(
        PROMPT_REGISTRY, "pptx", f"deck.{document_type}"
    )
    batches = chunk_slides_by_tokens(slides_data, MAX_PARTIAL_TOKENS)
    partial_summaries = []
    for batch in batches:
        batch_text = "\n\n".join(
            (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
            for slide in batch
            if slide.get("text", "") or slide.get("notes", "")
        )
        prompt = render_prompt(
            deck_template, summary_text=batch_text[:40000], source_name="partial"
        )
        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a precise summarization assistant.",
                },
                {"role": "user", "content": prompt},
            ]
            raw = llm_router.complete(TaskType.LONG_TEXT_SUMMARY, messages)
            summary = clean_gpt_response(raw)
            partial_summaries.append(summary)
        except Exception as e:
            logger.error(f"❌ Partial summary error: {e}")
            continue
    final_summary = "\n".join(partial_summaries)
    if estimate_tokens(final_summary) > MAX_SUMMARY_TOKENS:
        prompt = render_prompt(
            deck_template,
            summary_text=final_summary[: MAX_SUMMARY_TOKENS * 2],
            source_name="global",
        )
        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a precise summarization assistant.",
                },
                {"role": "user", "content": prompt},
            ]
            raw = llm_router.complete(TaskType.LONG_TEXT_SUMMARY, messages)
            final_summary = clean_gpt_response(raw)
        except Exception as e:
            logger.error(f"❌ Global summary reduction error: {e}")
            final_summary = final_summary[: MAX_SUMMARY_TOKENS * 100]
    return final_summary


# Analyse globale du deck pour extraire résumé et métadonnées (document, solution)
def analyze_deck_summary(
    slides_data: List[Dict[str, Any]], source_name: str, document_type: str = "default"
) -> dict:
    logger.info(f"🔍 GPT: analyse du deck via texte extrait — {source_name}")
    summary_text = summarize_large_pptx(slides_data)
    doc_type = document_type or "default"
    deck_prompt_id, deck_template = select_prompt(
        PROMPT_REGISTRY, doc_type, "deck"
    )
    prompt = render_prompt(
        deck_template, summary_text=summary_text, source_name=source_name
    )
    try:
        messages = [
            {
                "role": "system",
                "content": "You are a precise SAP document metadata extraction assistant.",
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
        logger.debug(
            f"Deck summary + metadata keys: {list(result.keys()) if result else 'n/a'}"
        )
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
    retries=2,
):
    # Note: Heartbeat géré au niveau de la boucle principale (toutes les 3 slides)
    # pour éviter trop d'overhead sur chaque slide

    img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    doc_type = document_type or "default"
    slide_prompt_id, slide_template = select_prompt(
        PROMPT_REGISTRY, doc_type, "slide"
    )
    prompt_text = render_prompt(
        slide_template,
        deck_summary=deck_summary,
        slide_index=slide_index,
        source_name=source_name,
        text=text,
        notes=notes,
        megaparse_content=megaparse_content,
    )
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
            raw_content = llm_router.complete(TaskType.VISION, msg)
            logger.debug(
                f"LLM response for slide {slide_index}: {raw_content!r}"
            )
            cleaned_content = clean_gpt_response(raw_content or "")
            items = json.loads(cleaned_content)
            enriched = []
            for it in items:
                expl = it.get("full_explanation", "")
                meta = it.get("meta", {})
                if expl:
                    for seg in recursive_chunk(expl, max_len=400, overlap_ratio=0.15):
                        enriched.append(
                            {
                                "full_explanation": seg,
                                "meta": meta,
                                "prompt_meta": {
                                    "document_type": doc_type,
                                    "slide_prompt_id": slide_prompt_id,
                                    "prompts_version": PROMPT_REGISTRY.get(
                                        "version", "unknown"
                                    ),
                                },
                            }
                        )
            return enriched
        except Exception as e:
            logger.warning(f"Slide {slide_index} attempt {attempt} failed: {e}")
            time.sleep(2 * (attempt + 1))
    return []


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
            logger.info(f"Slide {slide_index}: skipping chunk with slide_role '{slide_role}'")
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
            },
            "solution": {
                "main": doc_meta.get("main_solution", ""),
                "family": doc_meta.get("family", ""),
                "supporting": doc_meta.get("supporting_solutions", []),
                "mentioned": doc_meta.get("mentioned_solutions", []),
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


# Fonction principale pour traiter un fichier PPTX
def process_pptx(pptx_path: Path, document_type: str = "default", progress_callback=None):
    logger.info(f"start ingestion for {pptx_path.name}")

    if progress_callback:
        progress_callback("Conversion PDF", 5, 100, "Conversion du PowerPoint en PDF")

    ensure_dirs()
    pdf_path = convert_pptx_to_pdf(pptx_path, SLIDES_PNG)
    slides_data = extract_notes_and_text(pptx_path)

    if progress_callback:
        progress_callback("Analyse du contenu", 10, 100, "Analyse du contenu et génération du résumé")

    deck_info = analyze_deck_summary(
        slides_data, pptx_path.name, document_type=document_type
    )
    summary = deck_info.get("summary", "")
    metadata = deck_info.get("metadata", {})
    deck_prompt_id = deck_info.get("_prompt_meta", {}).get("deck_prompt_id", "unknown")

    if progress_callback:
        progress_callback("Génération des miniatures", 15, 100, f"Création de {len(slides_data)} miniatures")

    # Convertir PDF en images directement en mémoire (évite les fichiers PPM temporaires)
    images = convert_from_path(str(pdf_path))
    image_paths = {}
    for i, img in enumerate(images, start=1):
        img_path = THUMBNAILS_DIR / f"{pptx_path.stem}_slide_{i}.jpg"
        if img.mode == "RGBA":
            # Convertir RGBA en RGB pour JPEG
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1])
            rgb_img.save(img_path, "JPEG", quality=60, optimize=True)
        else:
            img.save(img_path, "JPEG", quality=60, optimize=True)
        image_paths[i] = img_path
        generate_thumbnail(img_path)
    if progress_callback:
        progress_callback("Analyse des slides", 20, 100, f"Analyse IA de {len(slides_data)} slides")

    tasks = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for slide in slides_data:
            idx = slide["slide_index"]
            text = slide["text"]
            notes = slide["notes"]
            megaparse_content = slide.get("megaparse_content", text)

            # Log debug du contenu MegaParse envoyé au LLM
            content_type = slide.get("content_type", "unknown")
            preview = (megaparse_content or text)[:200]
            if content_type.startswith("python_pptx"):
                logger.debug(f"[SLIDE {idx}] python-pptx fallback content (truncated): {preview}...")
            else:
                logger.debug(f"[SLIDE {idx}] MegaParse content (truncated): {preview}...")

            if idx in image_paths:
                tasks.append(
                    (
                        idx,
                        ex.submit(
                            ask_gpt_slide_analysis,
                            image_paths[idx],
                            summary,
                            idx,
                            pptx_path.name,
                            text,
                            notes,
                            megaparse_content,
                            document_type,
                            deck_prompt_id,
                        ),
                    )
                )

    total = 0
    total_slides = len(tasks)

    for i, (idx, future) in enumerate(tasks):
        # Progression de 20% à 90% pendant l'analyse des slides
        slide_progress = 20 + int((i / total_slides) * 70)
        if progress_callback:
            progress_callback("Analyse des slides", slide_progress, 100, f"Analyse slide {i+1}/{total_slides}")

        chunks = future.result() or []
        if not chunks:
            logger.info(f"Slide {idx}: No concepts extracted (empty/title/transition slide)")
        ingest_chunks(chunks, metadata, pptx_path.stem, idx, summary)
        total += len(chunks)

        # Envoyer heartbeat toutes les 3 slides (pour documents longs) + plus fréquent pour très longs imports
        if i % 3 == 0 or (total_slides > 50 and i % 2 == 0):
            try:
                from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                send_worker_heartbeat()
                logger.debug(f"Heartbeat envoyé pour slide {i+1}/{total_slides}")
            except Exception as e:
                logger.warning(f"Erreur envoi heartbeat: {e}")
                pass  # Ignorer si pas dans un contexte RQ

    if progress_callback:
        progress_callback("Ingestion dans Qdrant", 95, 100, "Insertion des chunks dans la base vectorielle")

    shutil.move(str(pptx_path), DOCS_DONE / f"{pptx_path.stem}.pptx")

    if progress_callback:
        progress_callback("Terminé", 100, 100, f"Import terminé - {total} chunks insérés")

    logger.info(f"Done {pptx_path.name} — total chunks: {total}")

    return {"chunks_inserted": total}


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
