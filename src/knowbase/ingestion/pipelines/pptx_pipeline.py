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
from knowbase.common.entity_normalizer import get_entity_normalizer

from langdetect import detect, DetectorFactory, LangDetectException
import fitz  # PyMuPDF
from PIL import Image
from qdrant_client.models import PointStruct
from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.common.llm_router import get_llm_router, TaskType

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
    analyze_deck_summary,
    ask_gpt_slide_analysis_text_only,
    ask_gpt_slide_analysis,
    ask_gpt_vision_summary,
    # Vision Gating - Optimisation coûts
    VisionDecision,
    should_use_vision,
    estimate_vision_savings,
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
# Note: get_llm_router() retourne le singleton avec support Burst Mode
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


# === FONCTIONS EXTRAITES VERS COMPONENTS/ ===
# Les fonctions suivantes sont maintenant importées depuis components/:
# - analyze_deck_summary (components.transformers.llm_analyzer)
# - ask_gpt_slide_analysis_text_only (components.transformers.llm_analyzer)
# - ask_gpt_slide_analysis (components.transformers.vision_analyzer)
# - ask_gpt_vision_summary (components.transformers.vision_analyzer)
# - ingest_chunks (components.sinks.qdrant_writer)
# - embed_texts (components.sinks.qdrant_writer)


def load_document_type_context(document_type_id: str | None) -> str | None:
    """
    Charge le context_prompt depuis la DB pour un document_type_id donné.

    .. deprecated::
        Cette fonction est DEPRECATED. Le système DocumentType est remplacé
        par le Domain Context global qui s'adapte progressivement aux documents.
        Utilisez DomainContextInjector à la place.

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
    use_vision: bool = True,  # DEPRECATED: Gardé pour compatibilité, gating automatique activé
):
    """
    Traite un fichier PPTX avec gating Vision automatique.

    Le gating Vision décide automatiquement pour chaque slide si Vision (GPT-4o)
    est nécessaire ou si le texte extrait suffit. Cela optimise les coûts en
    réduisant les appels Vision de 40-60%.

    Args:
        pptx_path: Chemin vers le fichier PPTX
        document_type_id: ID du type de document (optionnel)
        progress_callback: Callback pour progression UI
        rq_job: Job RQ pour heartbeat
        use_vision: DEPRECATED - Le gating automatique est toujours actif
    """
    # Reconfigurer logger pour le contexte RQ worker avec lazy file creation
    global logger
    logger = setup_logging(LOGS_DIR, "ingest_debug.log", enable_console=False)

    # Premier log réel - c'est ici que le fichier sera créé
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"🚀 Traitement: {pptx_path.name}")
    logger.info(f"📋 Document Type ID: {document_type_id or 'default'}")
    logger.info(
        f"🔍 Mode extraction: VISION GATING AUTOMATIQUE (décision par slide)"
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
        logger.info(f"📊 [OSMOSE PURE] image_paths count = {len(image_paths)}")
        logger.info(f"📊 [OSMOSE PURE] slides_data count = {len(slides_data)}")

        # ===== VISION GATING : Estimation des économies avant traitement =====
        gating_stats = estimate_vision_savings(slides_data, include_optional=True)
        logger.info(f"📊 [VISION GATING] Estimation pré-traitement:")
        logger.info(f"   - Total slides: {gating_stats['total_slides']}")
        logger.info(f"   - Vision requise: {gating_stats['required_vision']} slides")
        logger.info(f"   - Vision optionnelle: {gating_stats['optional_vision']} slides")
        logger.info(f"   - Skip Vision: {gating_stats['skip_vision']} slides")
        logger.info(f"   - Économie estimée: ${gating_stats['estimated_savings_usd']:.2f} ({gating_stats['savings_percent']:.0f}%)")

        vision_tasks = []
        gating_decisions = {"vision": 0, "skip": 0}

        logger.info(
            f"🤖 [OSMOSE PURE] Analyse avec gating Vision automatique..."
        )

        with ThreadPoolExecutor(max_workers=actual_workers) as ex:
            for slide in slides_data:
                idx = slide["slide_index"]
                raw_text = slide.get("text", "")
                notes = slide.get("notes", "")
                megaparse_content = slide.get("megaparse_content", raw_text)

                # === VISION GATING : Décision automatique par slide ===
                gating_result = should_use_vision(
                    slide_text=raw_text,
                    slide_notes=notes,
                    slide_index=idx,
                    has_shapes=slide.get("has_shapes", False),
                    has_images=slide.get("has_images", False),
                    has_charts=slide.get("has_charts", False),
                )

                if idx in image_paths and gating_result.decision != VisionDecision.SKIP:
                    # Vision requise ou optionnelle → appel GPT-4o Vision
                    gating_decisions["vision"] += 1
                    vision_tasks.append(
                        (
                            idx,
                            gating_result.decision.value,  # "required" ou "optional"
                            ex.submit(
                                ask_gpt_vision_summary,
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
                    # Skip Vision → utiliser texte brut
                    gating_decisions["skip"] += 1
                    vision_tasks.append((idx, "skip", None))

        total_slides_with_vision = gating_decisions["vision"]
        logger.info(f"📊 [VISION GATING] Décisions finales:")
        logger.info(f"   - Appels Vision: {gating_decisions['vision']} slides")
        logger.info(f"   - Skip (texte seul): {gating_decisions['skip']} slides")
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
        actual_vision_count = 0
        actual_skip_count = 0

        for i, (idx, decision, future) in enumerate(vision_tasks):
            slide_progress = 20 + int((i / len(vision_tasks)) * 40)  # 20% → 60%
            if progress_callback:
                progress_callback(
                    "Analyse Vision",
                    slide_progress,
                    100,
                    f"Slide {i+1}/{len(vision_tasks)} ({decision})",
                )

            if future is not None:
                # Attendre résumé Vision
                actual_vision_count += 1
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
                                    f"Slide {idx} [VISION {decision.upper()}]: Timeout après 5min"
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
                            f"Slide {idx} [VISION {decision.upper()}]: Future n'est pas done après attente"
                        )
                        summary = f"Slide {idx}: erreur"
                    else:
                        summary = future.result()

                except Exception as e:
                    logger.error(
                        f"Slide {idx} [VISION {decision.upper()}]: Erreur récupération résultat: {e}"
                    )
                    # Fallback texte
                    slide_data = slides_data[i] if i < len(slides_data) else {}
                    summary = f"Slide {idx}: {slide_data.get('text', '')} {slide_data.get('notes', '')}"

            else:
                # Skip Vision → utiliser texte brut (économie $$)
                actual_skip_count += 1
                slide_data = slides_data[i] if i < len(slides_data) else {}
                text = slide_data.get("text", "")
                notes = slide_data.get("notes", "")
                summary = f"{text}\n{notes}".strip() or f"Slide {idx}"
                logger.debug(f"Slide {idx} [SKIP]: Utilisation texte brut ({len(summary)} chars)")

            # Ajouter à la collection avec métadonnée de décision
            slide_summaries.append({
                "slide_index": idx,
                "summary": summary,
                "vision_decision": decision,  # "required", "optional", ou "skip"
            })

            if decision != "skip":
                logger.info(f"Slide {idx} [VISION {decision.upper()}]: {len(summary)} chars collectés")

            # Heartbeat périodique
            if (i + 1) % 3 == 0:
                try:
                    from knowbase.ingestion.queue.jobs import send_worker_heartbeat

                    send_worker_heartbeat()
                except Exception:
                    pass

        # Statistiques finales de gating
        logger.info(f"✅ [OSMOSE PURE] {len(slide_summaries)} résumés collectés")
        logger.info(f"📊 [VISION GATING] Bilan final:")
        logger.info(f"   - Appels Vision réels: {actual_vision_count}")
        logger.info(f"   - Slides skip (texte seul): {actual_skip_count}")
        if actual_skip_count > 0:
            savings_pct = (actual_skip_count / len(slide_summaries)) * 100
            savings_usd = actual_skip_count * 0.03  # ~$0.03 par appel Vision
            logger.info(f"   - 💰 Économie Vision: {savings_pct:.0f}% (~${savings_usd:.2f})")
    
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

    # Normalisation des solutions avec entity_normalizer (domain-agnostic)
    normalizer = get_entity_normalizer()

    if merged.get("main_solution"):
        sol_id, canon, _ = normalizer.normalize_entity_name(merged["main_solution"], "SOLUTION")
        merged["main_solution_id"] = sol_id or "UNMAPPED"
        merged["main_solution"] = canon or merged["main_solution"]
    else:
        merged["main_solution_id"] = "UNMAPPED"

    normalized_supporting = []
    for supp in merged["supporting_solutions"]:
        sid, canon, _ = normalizer.normalize_entity_name(supp, "SOLUTION")
        normalized_supporting.append(canon or supp)
    merged["supporting_solutions"] = list(set(normalized_supporting))

    normalized_mentioned = []
    for ment in merged["mentioned_solutions"]:
        sid, canon, _ = normalizer.normalize_entity_name(ment, "SOLUTION")
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
