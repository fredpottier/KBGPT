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
    else:
        logger.error("❌ Réponse LLM vide")
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

MAX_TOKENS_THRESHOLD = 8000  # Contexte optimal pour analyse de slides (évite consommation excessive)
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


def convert_pdf_to_images_pymupdf(pdf_path: str, dpi: int = 150, rq_job=None):
    """
    Convertit un PDF en images PIL avec PyMuPDF (plus rapide que pdf2image)
    Compatible avec l'API de pdf2image convert_from_path

    Args:
        pdf_path: Chemin vers le fichier PDF (string)
        dpi: Résolution des images (défaut: 150)
        rq_job: Job RQ pour les heartbeats (optionnel)

    Returns:
        List[PIL.Image]: Liste d'images PIL (comme convert_from_path)
    """
    import io
    from PIL import Image

    logger.info(f"🔄 Conversion PDF→Images PyMuPDF: {Path(pdf_path).name} (DPI: {dpi})")

    try:
        # Ouvrir le document PDF
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        logger.info(f"📄 {total_pages} pages détectées dans le PDF")

        # Facteur d'échelle basé sur le DPI (72 DPI = facteur 1.0)
        zoom_factor = dpi / 72.0
        mat = fitz.Matrix(zoom_factor, zoom_factor)

        images = []

        for page_num in range(total_pages):
            try:
                # Envoyer un heartbeat périodiquement (toutes les 30 pages)
                if rq_job and page_num % 30 == 0:
                    try:
                        # Essayer l'ancienne API d'abord
                        rq_job.heartbeat()
                        logger.debug(f"Heartbeat envoyé - page {page_num + 1}/{total_pages}")
                    except TypeError:
                        # Nouvelle API RQ : heartbeat avec datetime et ttl
                        try:
                            from datetime import datetime, timezone
                            rq_job.heartbeat(timestamp=datetime.now(timezone.utc), ttl=600)
                            logger.debug(f"Heartbeat envoyé (nouvelle API) - page {page_num + 1}/{total_pages}")
                        except Exception as e:
                            logger.debug(f"Erreur heartbeat nouvelle API: {e}")
                    except Exception as e:
                        logger.debug(f"Erreur heartbeat: {e}")

                page = doc[page_num]
                pix = page.get_pixmap(matrix=mat)

                # Convertir en PIL Image
                img_data = pix.tobytes("ppm")
                img = Image.open(io.BytesIO(img_data))

                images.append(img)
                logger.debug(f"✅ Page {page_num + 1} convertie en PIL Image")

                # Libérer la mémoire du pixmap
                pix = None

            except Exception as e:
                logger.error(f"❌ Erreur conversion page {page_num + 1}: {e}")
                continue

        doc.close()
        logger.info(f"✅ Conversion PyMuPDF terminée: {len(images)} images générées")
        return images

    except Exception as e:
        logger.error(f"❌ Erreur PyMuPDF: {e}")
        raise


def get_hidden_slides(pptx_path: Path) -> List[int]:
    """
    Identifie les slides cachés dans un PPTX en analysant la structure XML.

    Returns:
        List[int]: Liste des numéros de slides cachés (1-indexé)
    """
    try:
        from pptx import Presentation

        prs = Presentation(str(pptx_path))
        presentation_part = prs.part
        presentation_element = presentation_part._element

        # Parcourir les sldId dans sldIdLst pour détecter show="0" (caché)
        hidden_slides = []
        slide_elements = presentation_element.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId')

        for i, sld_id in enumerate(slide_elements, start=1):
            show_attr = sld_id.get('show', '1')  # Par défaut '1' = visible
            if show_attr == '0':
                hidden_slides.append(i)
                logger.debug(f"🙈 Slide {i}: détecté comme caché (show='0')")

        if hidden_slides:
            logger.info(f"🙈 {len(hidden_slides)} slides cachés détectés: {hidden_slides}")
        else:
            logger.debug(f"✅ Aucun slide caché détecté dans {pptx_path.name}")

        return hidden_slides

    except Exception as e:
        logger.warning(f"⚠️ Impossible de détecter les slides cachés: {e}")
        return []  # En cas d'erreur, ne pas filtrer


def remove_hidden_slides_inplace(pptx_path: Path) -> int:
    """
    Supprime directement les slides cachés du fichier PPTX uploadé.
    Manipulation XML directe pour préserver l'intégrité complète du document.

    Returns:
        int: Nombre de slides cachés supprimés
    """
    try:
        import zipfile
        import tempfile
        from lxml import etree
        import shutil

        logger.info(f"🔍 Analyse des slides cachés dans {pptx_path.name}")

        # Lire le PPTX comme un ZIP
        with zipfile.ZipFile(pptx_path, 'r') as zip_read:
            # Lire presentation.xml
            presentation_xml = zip_read.read('ppt/presentation.xml')

        # Parser le XML
        root = etree.fromstring(presentation_xml)
        namespaces = {
            'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
            'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        }

        # Trouver les slides cachés
        sld_id_lst = root.find('.//p:sldIdLst', namespaces)
        if sld_id_lst is None:
            logger.info(f"✅ Aucune liste de slides trouvée")
            return 0

        hidden_slides = []
        slide_rids_to_remove = []

        for i, sld_id in enumerate(sld_id_lst.findall('p:sldId', namespaces), 1):
            show_attr = sld_id.get('show', '1')
            if show_attr == '0':
                hidden_slides.append(i)
                rid = sld_id.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                if rid:
                    slide_rids_to_remove.append(rid)
                logger.debug(f"🙈 Slide {i} caché détecté (rId: {rid})")

        if not hidden_slides:
            logger.info(f"✅ Aucun slide caché détecté dans {pptx_path.name}")
            return 0

        logger.info(f"🗑️ Suppression de {len(hidden_slides)} slides cachés: {hidden_slides}")

        # Supprimer les éléments sldId cachés du XML
        for sld_id in sld_id_lst.findall('p:sldId', namespaces):
            if sld_id.get('show') == '0':
                sld_id_lst.remove(sld_id)

        # Créer un nouveau PPTX sans les slides cachés
        with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        with zipfile.ZipFile(pptx_path, 'r') as zip_read:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zip_write:

                for item in zip_read.infolist():
                    # Lire le contenu
                    content = zip_read.read(item.filename)

                    if item.filename == 'ppt/presentation.xml':
                        # Utiliser le XML modifié
                        content = etree.tostring(root, encoding='utf-8', xml_declaration=True)
                    elif item.filename.startswith('ppt/slides/slide') and item.filename.endswith('.xml'):
                        # Vérifier si ce slide doit être supprimé
                        # Extraire le numéro de slide du nom de fichier
                        import re
                        match = re.search(r'slide(\d+)\.xml', item.filename)
                        if match:
                            slide_num = int(match.group(1))
                            if slide_num in hidden_slides:
                                logger.debug(f"🗑️ Suppression du fichier {item.filename}")
                                continue  # Skip ce fichier
                    elif item.filename.startswith('ppt/slides/_rels/slide') and item.filename.endswith('.xml.rels'):
                        # Supprimer aussi les relations des slides cachés
                        import re
                        match = re.search(r'slide(\d+)\.xml\.rels', item.filename)
                        if match:
                            slide_num = int(match.group(1))
                            if slide_num in hidden_slides:
                                logger.debug(f"🗑️ Suppression des relations {item.filename}")
                                continue  # Skip ce fichier

                    # Copier le fichier
                    zip_write.writestr(item, content)

        # Remplacer le fichier original
        shutil.move(str(temp_path), str(pptx_path))

        logger.info(f"✅ {len(hidden_slides)} slides cachés supprimés avec succès de {pptx_path.name}")
        return len(hidden_slides)

    except Exception as e:
        logger.error(f"❌ Erreur suppression slides cachés: {e}")
        logger.info(f"🔄 Poursuite avec le PPTX original")
        return 0


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
    logger.info(f"📊 [MEGAPARSE] Extraction PPTX: {pptx_path.name}")

    try:
        megaparse = MegaParse()
        start_time = time.time()
        parsed_content = megaparse.load(str(pptx_path))
        load_duration = time.time() - start_time

        # MegaParse retourne le contenu structuré complet
        content_str = str(parsed_content) if not isinstance(parsed_content, str) else parsed_content

        # Extraction des slides réels depuis le contenu MegaParse
        slides_data = extract_slides_from_megaparse(content_str, pptx_path.name)
        logger.info(f"✅ [MEGAPARSE] Extraction terminée - {len(slides_data)} slides extraits en {load_duration:.1f}s")
        return slides_data

    except Exception as e:
        import traceback
        logger.error(f"❌ [MEGAPARSE TRACE] ERREUR CRITIQUE dans MegaParse pour {pptx_path.name}")
        logger.error(f"❌ [MEGAPARSE TRACE] Type d'erreur: {type(e).__name__}")
        logger.error(f"❌ [MEGAPARSE TRACE] Message d'erreur: {str(e)}")
        logger.error(f"❌ [MEGAPARSE TRACE] Traceback complet:\n{traceback.format_exc()}")

        # Fallback vers python-pptx si disponible
        if PPTX_FALLBACK:
            logger.info(f"🔄 [MEGAPARSE TRACE] Fallback vers python-pptx pour {pptx_path.name}")
            return extract_with_python_pptx(pptx_path)
        else:
            logger.error(f"❌ [MEGAPARSE TRACE] Aucun fallback disponible!")
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


# Extrait les slides réels depuis le contenu MegaParse
def extract_slides_from_megaparse(content: str, source_name: str) -> List[Dict[str, Any]]:
    """
    NOUVELLE ARCHITECTURE : Utilise MegaParse pour extraire le contenu slide par slide.
    MegaParse extrait déjà le contenu structuré - on ne fait plus de segmentation artificielle.
    """
    from pptx import Presentation

    # Charger le fichier PPTX original pour connaître le nombre réel de slides
    pptx_path = Path("/data/docs_in").resolve() / source_name
    if not pptx_path.exists():
        logger.error(f"Fichier PPTX introuvable: {pptx_path}")
        return []

    try:
        # Obtenir le nombre réel de slides
        prs = Presentation(str(pptx_path))
        real_slide_count = len(prs.slides)
        logger.info(f"📊 Document PPTX: {real_slide_count} slides réels détectés")

        # Diviser le contenu MegaParse en fonction du nombre réel de slides
        content_lines = content.split('\n')
        lines_per_slide = len(content_lines) // real_slide_count if real_slide_count > 0 else len(content_lines)

        slides_data = []

        for slide_num in range(1, real_slide_count + 1):
            # Calculer les indices de ligne pour cette slide
            start_line = (slide_num - 1) * lines_per_slide
            end_line = slide_num * lines_per_slide if slide_num < real_slide_count else len(content_lines)

            # Extraire le contenu pour cette slide
            slide_content = '\n'.join(content_lines[start_line:end_line]).strip()

            # Ne créer une slide que si elle contient du contenu significatif
            if slide_content and len(slide_content) > 20:
                slides_data.append({
                    "slide_index": slide_num,
                    "text": slide_content,
                    "notes": "",
                    "megaparse_content": slide_content,
                    "content_type": "real_slide"
                })

        logger.info(f"✅ Extraction réelle: {len(slides_data)} slides avec contenu significatif")
        return slides_data

    except Exception as e:
        logger.error(f"Erreur lors de l'extraction des slides réels: {e}")
        # Fallback : traiter tout le contenu comme une seule slide
        return [{
            "slide_index": 1,
            "text": content,
            "notes": "",
            "megaparse_content": content,
            "content_type": "fallback_single"
        }]


# Note: Les images sont générées directement dans THUMBNAILS_DIR
# et utilisées telles quelles par le LLM (pas de thumbnail séparé)


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
def summarize_large_pptx(slides_data: List[Dict[str, Any]], document_type: str = "default") -> str:
    all_text = "\n\n".join(
        (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
        for slide in slides_data
        if slide.get("text", "") or slide.get("notes", "")
    )

    total_tokens = estimate_tokens(all_text)
    if total_tokens <= MAX_TOKENS_THRESHOLD:
        logger.info(f"📊 Analyse deck: {len(slides_data)} slides, {total_tokens} tokens (direct)")
        return all_text

    # Document volumineux → résumé par batchs
    logger.info(f"📊 Analyse deck: {len(slides_data)} slides, {total_tokens} tokens (résumé requis)")
    batch_prompt_id, batch_template = select_prompt(
        PROMPT_REGISTRY, document_type, "deck"
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
            batch_template, summary_text=batch_text
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
            batch_template,
            summary_text=final_summary[: MAX_SUMMARY_TOKENS * 2]
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


def extract_pptx_metadata(pptx_path: Path) -> dict:
    """
    Extrait les métadonnées depuis le fichier PPTX (docProps/core.xml)
    Retourne notamment la date de modification pour éliminer la saisie manuelle
    """
    try:
        with zipfile.ZipFile(pptx_path, 'r') as pptx_zip:
            if 'docProps/core.xml' not in pptx_zip.namelist():
                logger.warning(f"Pas de métadonnées core.xml dans {pptx_path.name}")
                return {}

            core_xml = pptx_zip.read('docProps/core.xml').decode('utf-8')
            root = ET.fromstring(core_xml)

            # Namespaces Office Open XML
            namespaces = {
                'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
                'dc': 'http://purl.org/dc/elements/1.1/',
                'dcterms': 'http://purl.org/dc/terms/',
                'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
            }

            metadata = {}

            # Date de modification (prioritaire pour source_date)
            modified_elem = root.find('dcterms:modified', namespaces)
            if modified_elem is not None:
                try:
                    modified_str = modified_elem.text
                    modified_dt = datetime.fromisoformat(modified_str.replace('Z', '+00:00'))
                    metadata['source_date'] = modified_dt.strftime('%Y-%m-%d')
                    logger.info(f"📅 Date de modification extraite: {metadata['source_date']}")
                except Exception as e:
                    logger.warning(f"Erreur parsing date modification: {e}")

            # Autres métadonnées utiles
            title_elem = root.find('dc:title', namespaces)
            if title_elem is not None and title_elem.text:
                metadata['title'] = title_elem.text
                logger.info(f"📄 Titre extrait: {metadata['title']}")

            creator_elem = root.find('dc:creator', namespaces)
            if creator_elem is not None and creator_elem.text:
                metadata['creator'] = creator_elem.text

            return metadata

    except Exception as e:
        logger.warning(f"Erreur extraction métadonnées PPTX {pptx_path.name}: {e}")
        return {}


# Analyse globale du deck pour extraire résumé et métadonnées (document, solution)
def analyze_deck_summary(
    slides_data: List[Dict[str, Any]], source_name: str, document_type: str = "default", auto_metadata: dict = None
) -> dict:
    logger.info(f"🔍 GPT: analyse du deck via texte extrait — {source_name}")
    summary_text = summarize_large_pptx(slides_data, document_type)
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

        # --- Fusion avec les métadonnées auto-extraites du PPTX ---
        if auto_metadata:
            # Priorité aux métadonnées auto-extraites pour certains champs
            for key in ['source_date', 'title']:
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


# Analyse d'un slide via GPT + image, retourne les chunks enrichis
def create_fallback_chunks(
    text: str,
    notes: str,
    megaparse_content: str,
    slide_index: int,
    document_type: str = "default",
    slide_prompt_id: str = "unknown"
) -> List[Dict[str, Any]]:
    """
    Créer chunks de base depuis texte brut (fallback si LLM échoue)

    Critère 6 Phase 0: Garantir ingestion chunks même si extraction LLM échoue

    Args:
        text: Texte slide python-pptx
        notes: Notes speaker
        megaparse_content: Contenu MegaParse
        slide_index: Index slide
        document_type: Type document
        slide_prompt_id: ID prompt utilisé

    Returns:
        Liste chunks de base (au moins 1 chunk si contenu présent)
    """
    # Priorité: MegaParse > text > notes
    content_sources = []
    if megaparse_content and megaparse_content.strip():
        content_sources.append(("megaparse", megaparse_content.strip()))
    if text and text.strip():
        content_sources.append(("text", text.strip()))
    if notes and notes.strip():
        content_sources.append(("notes", notes.strip()))

    if not content_sources:
        logger.warning(f"Slide {slide_index}: Aucun contenu pour fallback chunks")
        return []

    # Combiner contenus disponibles
    combined_content = "\n\n".join([f"[{source}] {content}" for source, content in content_sources])

    # Chunking simple (400 caractères, overlap 15%)
    chunks = []
    for seg in recursive_chunk(combined_content, max_len=400, overlap_ratio=0.15):
        chunks.append({
            "full_explanation": seg,
            "meta": {
                "scope": "slide-fallback",
                "type": "fallback_chunk",
                "level": "basic"
            },
            "prompt_meta": {
                "document_type": document_type,
                "slide_prompt_id": slide_prompt_id,
                "prompts_version": PROMPT_REGISTRY.get("version", "unknown"),
                "extraction_status": "chunks_only_fallback"
            }
        })

    logger.info(
        f"Slide {slide_index}: {len(chunks)} fallback chunks créés "
        f"(sources: {', '.join([s for s, _ in content_sources])})"
    )

    return chunks


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
    """
    Analyse slide via LLM vision avec fallback automatique

    Critère 6 Phase 0: Extraction découplée
    - Bloc best-effort: Extraction enrichie LLM vision (peut échouer)
    - Bloc critique: Fallback chunks-only (doit toujours réussir)

    Returns:
        Liste chunks (enrichis si LLM OK, fallback sinon - jamais vide si contenu présent)
    """
    # Heartbeat avant l'appel LLM vision (long processus)
    try:
        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
        send_worker_heartbeat()
    except Exception:
        pass  # Ignorer si pas dans un contexte RQ

    doc_type = document_type or "default"
    slide_prompt_id, slide_template = select_prompt(
        PROMPT_REGISTRY, doc_type, "slide"
    )

    # BLOC BEST-EFFORT: Extraction enrichie LLM vision
    try:
        img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
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
                                        "extraction_status": "unified_success"
                                    },
                                }
                            )

                if enriched:
                    logger.info(
                        f"Slide {slide_index}: {len(enriched)} concepts extraits (LLM success)"
                    )
                    return enriched
                else:
                    logger.warning(
                        f"Slide {slide_index}: LLM retourné vide, tentative {attempt + 1}/{retries}"
                    )

            except Exception as e:
                logger.warning(
                    f"Slide {slide_index} LLM attempt {attempt + 1}/{retries} failed: {e}"
                )
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))

    except Exception as e:
        logger.error(
            f"Slide {slide_index}: Erreur critique LLM vision: {e}. "
            f"Basculement fallback chunks-only"
        )

    # BLOC CRITIQUE: Fallback chunks-only (doit toujours réussir)
    logger.warning(
        f"Slide {slide_index}: LLM échoué après {retries} tentatives. "
        f"Fallback chunks-only activé"
    )

    fallback_chunks = create_fallback_chunks(
        text=text,
        notes=notes,
        megaparse_content=megaparse_content,
        slide_index=slide_index,
        document_type=doc_type,
        slide_prompt_id=slide_prompt_id
    )

    return fallback_chunks


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
                "all_mentioned_solutions": doc_meta.get("mentioned_solutions", []),  # Solutions globales du deck entier
            },
            "solution": {
                "main": doc_meta.get("main_solution", ""),
                "family": doc_meta.get("family", ""),
                "supporting": doc_meta.get("supporting_solutions", []),
                "mentioned": meta.get("mentioned_solutions", []),  # Utiliser les solutions spécifiques de ce chunk/slide
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
def process_pptx(pptx_path: Path, document_type: str = "default", progress_callback=None, rq_job=None):
    logger.info(f"start ingestion for {pptx_path.name}")

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

    if progress_callback:
        progress_callback("Conversion PDF", 5, 100, "Conversion du PowerPoint en PDF")

    ensure_dirs()
    pdf_path = convert_pptx_to_pdf(pptx_path, SLIDES_PNG)
    slides_data = extract_notes_and_text(pptx_path)

    if progress_callback:
        progress_callback("Analyse du contenu", 10, 100, "Analyse du contenu et génération du résumé")

    # Extraction automatique des métadonnées PPTX (date de modification, titre, etc.)
    auto_metadata = extract_pptx_metadata(pptx_path)

    deck_info = analyze_deck_summary(
        slides_data, pptx_path.name, document_type=document_type, auto_metadata=auto_metadata
    )
    summary = deck_info.get("summary", "")
    metadata = deck_info.get("metadata", {})
    deck_prompt_id = deck_info.get("_prompt_meta", {}).get("deck_prompt_id", "unknown")

    if progress_callback:
        progress_callback("Génération des miniatures", 15, 100, "Conversion PDF → images en cours")

    # Génération d'images avec DPI adaptatif selon la taille du document
    if len(slides_data) > 400:
        # Gros documents : DPI réduit pour économiser la mémoire
        dpi = 120
        logger.info(f"📊 Gros document ({len(slides_data)} slides) - DPI réduit à {dpi} pour économiser la mémoire")
    elif len(slides_data) > 200:
        dpi = 150
        logger.info(f"📊 Document moyen ({len(slides_data)} slides) - DPI à {dpi}")
    else:
        dpi = 200
        logger.info(f"📊 Document normal ({len(slides_data)} slides) - DPI standard à {dpi}")

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
                    logger.debug(f"Heartbeat envoyé après génération de {i}/{len(images)} images")
                except Exception:
                    pass

        # Libérer la liste d'images après traitement
        del images
        logger.info(f"✅ {len(image_paths)} images générées avec succès")

    except Exception as e:
        logger.error(f"❌ Erreur génération d'images: {e}")
        raise

    logger.info(f"🔄 Début traitement LLM des slides...")

    actual_slide_count = len(image_paths)
    total_slides = len(slides_data)  # Corriger la variable manquante
    MAX_WORKERS = 3  # Valeur par défaut, peut être configurée

    if progress_callback:
        progress_callback("Génération des miniatures", 18, 100, f"Création de {actual_slide_count} miniatures")

    # Réduire les workers pour gros documents (éviter OOM)
    actual_workers = 1 if total_slides > 400 else MAX_WORKERS
    logger.info(f"📊 Utilisation de {actual_workers} workers pour {total_slides} slides")

    tasks = []
    logger.info(f"🤖 Soumission de {len(slides_data)} tâches LLM au ThreadPoolExecutor...")

    with ThreadPoolExecutor(max_workers=actual_workers) as ex:
        for slide in slides_data:
            idx = slide["slide_index"]
            raw_text = slide.get("text", "")
            notes = slide.get("notes", "")
            megaparse_content = slide.get("megaparse_content", raw_text)
            content_type = slide.get("content_type", "unknown")

            # Ne transmettre le texte legacy que si nous n'avons pas de contenu MegaParse exploitable
            if megaparse_content and content_type not in ("python_pptx_fallback", "fallback_single"):
                prompt_text = ""
            else:
                prompt_text = raw_text

            # Suppression des logs détaillés du contenu MegaParse par slide pour simplifier la lecture

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
                            prompt_text,
                            notes,
                            megaparse_content,
                            document_type,
                            deck_prompt_id,
                        ),
                    )
                )

    total_slides = len(tasks)
    logger.info(f"🚀 Début analyse LLM de {total_slides} slides")
    if progress_callback:
        progress_callback("Analyse des slides", 20, 100, f"Analyse IA de {total_slides} slides")
        # Petit délai pour forcer la mise à jour de l'interface
        import time
        time.sleep(0.1)

    total = 0

    for i, (idx, future) in enumerate(tasks):
        # Progression de 20% à 90% pendant l'analyse des slides
        slide_progress = 20 + int((i / total_slides) * 70)
        if progress_callback:
            progress_callback("Analyse des slides", slide_progress, 100, f"Analyse slide {i+1}/{total_slides}")

        logger.info(f"🔍 Attente résultat LLM pour slide {idx} ({i+1}/{total_slides})")

        # Attendre le résultat avec heartbeats réguliers pendant l'attente
        chunks = None
        try:
            import concurrent.futures
            import time

            # Attendre avec timeout et heartbeats
            timeout_seconds = 30  # Heartbeat toutes les 30 secondes max
            start_time = time.time()

            while not future.done():
                try:
                    # Essayer de récupérer le résultat avec un court timeout
                    chunks = future.result(timeout=timeout_seconds)
                    break
                except concurrent.futures.TimeoutError:
                    # Timeout atteint → envoyer heartbeat et continuer à attendre
                    elapsed = time.time() - start_time
                    try:
                        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                        send_worker_heartbeat()
                        logger.debug(f"Heartbeat envoyé pendant analyse slide {idx} (attente: {elapsed:.1f}s)")
                    except Exception as e:
                        logger.warning(f"Erreur envoi heartbeat pendant attente: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Erreur lors de l'analyse slide {idx}: {e}")
                    chunks = []
                    break

            # Si la boucle s'est terminée sans résultat, récupérer le résultat final
            if chunks is None:
                chunks = future.result()

        except Exception as e:
            logger.error(f"Erreur critique slide {idx}: {e}")
            chunks = []

        chunks = chunks or []
        if not chunks:
            logger.info(f"Slide {idx}: No concepts extracted (empty/title/transition slide)")
        else:
            logger.info(f"✅ Slide {idx}: {len(chunks)} concepts extracted")

        ingest_chunks(chunks, metadata, pptx_path.stem, idx, summary)
        logger.debug(f"📝 Slide {idx}: chunks ingérés dans Qdrant")
        total += len(chunks)

        # Heartbeat final après traitement de la slide
        try:
            from knowbase.ingestion.queue.jobs import send_worker_heartbeat
            send_worker_heartbeat()
            logger.debug(f"Heartbeat envoyé après traitement slide {i+1}/{total_slides}")
        except Exception as e:
            logger.warning(f"Erreur envoi heartbeat: {e}")
            pass  # Ignorer si pas dans un contexte RQ

    logger.info(f"🎯 Finalisation: {total} chunks au total traités")

    if progress_callback:
        progress_callback("Ingestion dans Qdrant", 95, 100, "Insertion des chunks dans la base vectorielle")

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
        progress_callback("Terminé", 100, 100, f"Import terminé - {total} chunks insérés")

    logger.info(f"🎉 INGESTION TERMINÉE - {pptx_path.name} - {total} chunks insérés")

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
