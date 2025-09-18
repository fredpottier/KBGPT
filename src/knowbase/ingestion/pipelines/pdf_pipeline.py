import base64
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from knowbase.common.logging import setup_logging

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from pdf2image import convert_from_path
from qdrant_client.models import PointStruct
from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)


from knowbase.config.paths import ensure_directories
from knowbase.config.settings import get_settings


# =========================
# Path resolution
# =========================
settings = get_settings()

DATA_ROOT = settings.data_dir
DOCS_IN = settings.docs_in_dir
DOCS_DONE = settings.docs_done_dir
SLIDES_PNG = settings.slides_dir / "pdf"
STATUS_DIR = settings.status_dir
LOGS_DIR = settings.logs_dir
MODELS_DIR = settings.models_dir


def ensure_dirs():
    ensure_directories([
        DOCS_IN,
        DOCS_DONE,
        SLIDES_PNG,
        STATUS_DIR,
        LOGS_DIR,
        MODELS_DIR,
    ])


ensure_dirs()

# =============================
# Configuration & initialisation
# =============================
COLLECTION_NAME = settings.qdrant_collection
GPT_MODEL = settings.gpt_model
MODEL_NAME = os.getenv("PDF_EMB_MODEL", settings.embeddings_model)
PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")


# ====================
# Logging
# ====================
logger = setup_logging(LOGS_DIR, "ingest_pdf_debug.log")


def banner_paths():
    def exists_dir(p: Path) -> str:
        return f"{p}  (exists={p.exists()}, is_dir={p.is_dir()})"

    logger.info("=== PDF INGEST START ===")
    logger.info(f"DATA_ROOT:    {exists_dir(DATA_ROOT)}")
    logger.info(f"DOCS_IN:      {exists_dir(DOCS_IN)}")
    logger.info(f"DOCS_DONE:    {exists_dir(DOCS_DONE)}")
    logger.info(f"SLIDES_PNG:   {exists_dir(SLIDES_PNG)}")
    logger.info(f"STATUS_DIR:   {exists_dir(STATUS_DIR)}")
    logger.info(f"LOGS_DIR:     {exists_dir(LOGS_DIR)}")
    logger.info(f"MODELS_DIR:   {exists_dir(MODELS_DIR)}")
    logger.info(f"PUBLIC_URL:   {PUBLIC_URL}")


banner_paths()

# ===================
# Clients & Models
# ===================
openai_client = get_openai_client()
qdrant_client = get_qdrant_client()
model = get_sentence_transformer(MODEL_NAME)
EMB_SIZE = model.get_sentence_embedding_dimension() or 768
ensure_qdrant_collection(COLLECTION_NAME, int(EMB_SIZE))

# ==============
# Utilities
# ==============
def clean_gpt_response(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```json"):
        s = s[len("```json") :].strip()
    if s.startswith("```"):
        s = s[len("```") :].strip()
    if s.endswith("```"):
        s = s[:-3].strip()
    return s


def encode_image_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_text_from_pdf(pdf_path: Path) -> str:
    txt_output = pdf_path.with_suffix(".txt")
    logger.info(f"📑 pdftotext: {pdf_path.name}")
    try:
        import subprocess

        subprocess.run(["pdftotext", str(pdf_path), str(txt_output)], check=True)
    except Exception as e:
        logger.error(f"❌ pdftotext failed: {e}")
        return ""
    text = ""
    try:
        text = txt_output.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"⚠️ Could not read {txt_output}: {e}")
    logger.debug(f"Extracted text length: {len(text)}")
    return text


# ==================
# Pipeline Steps
# ==================
def analyze_pdf_metadata(pdf_text: str, source_name: str) -> dict:
    logger.info(f"🔍 GPT: analyse des métadonnées — {source_name}")
    try:
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are a metadata extraction assistant.",
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": (
                f"You're analyzing a PDF document: '{source_name}'.\n"
                f"Below is the raw text extracted from it:\n\n{pdf_text[:8000]}\n\n"
                "Extract the following high-level metadata and return a single JSON object with fields:\n"
                "- title\n- objective\n- main_solution\n- supporting_solutions\n"
                "- mentioned_solutions\n- document_type\n- audience\n- source_date\n- language\n\n"
                "IMPORTANT: For the field 'main_solution', always use the official SAP canonical solution name as published on the SAP website or documentation. "
                "Do not use acronyms, abbreviations, or local variants. If the document uses a non-canonical name, map it to the official SAP name. "
                "If you are unsure, leave the field empty."
            ),
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            temperature=0.2,
            max_tokens=1024,
        )
        raw = getattr(response.choices[0].message, "content", "") or ""
        cleaned = clean_gpt_response(raw)
        meta = json.loads(cleaned) if cleaned else {}
        logger.debug(
            f"META (keys): {list(meta.keys()) if isinstance(meta, dict) else 'n/a'}"
        )
        return meta if isinstance(meta, dict) else {}
    except Exception as e:
        logger.error(f"❌ GPT metadata error: {e}")
        return {}


def ask_gpt_slide_analysis(
    image_path: Path,
    slide_text: str,
    source_name: str,
    slide_index: int,
):
    logger.info(f"🧠 GPT: analyse page {slide_index}")
    try:
        image_b64 = encode_image_base64(image_path)
        prompt: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
                {
                    "type": "text",
                    "text": (
                        f"You are analyzing page {slide_index} from '{source_name}'.\n"
                        f"Page content:\n{slide_text}\n\n"
                        "Extract 1–5 standalone content blocks. For each, return:\n"
                        "- `text`\n- `meta` with `type`, `level`, `topic`\n\n"
                        "Return only a JSON array."
                    ),
                },
            ],
        }
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are an expert assistant that analyzes PDF pages.",
        }
        messages: list[ChatCompletionMessageParam] = [system_message, prompt]
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
        )
        raw = getattr(response.choices[0].message, "content", "") or ""
        cleaned = clean_gpt_response(raw)
        data = json.loads(cleaned) if cleaned else []
        if not isinstance(data, list):
            data = []
        logger.debug(f"Page {slide_index}: chunks returned = {len(data)}")
        return data
    except Exception as e:
        logger.error(f"❌ GPT page {slide_index} error: {e}")
        return []


def ingest_chunks(chunks, doc_metadata, file_uid, page_index):
    points = []
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        meta = chunk.get("meta", {}) or {}
        if not text or len(text) < 20:
            continue
        try:
            emb = model.encode([f"passage: {text}"], normalize_embeddings=True)[
                0
            ].tolist()
            payload = {
                "text": text,
                "language": "en",
                "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "gpt_chunked": True,
                "page_index": page_index,
                "page_image_url": f"{PUBLIC_URL}/static/pdf_slides/{file_uid}_page_{page_index}.png",
                "source_file_url": f"{PUBLIC_URL}/static/pdfs/{file_uid}.pdf",
            }
            payload.update(doc_metadata)
            payload.update(meta)
            points.append(
                PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload)
            )
        except Exception as e:
            logger.warning(f"⚠️ Embedding error (page {page_index}): {e}")

    if points:
        try:
            qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
            logger.info(f"✅ Page {page_index}: {len(points)} chunk(s) ingérés")
        except Exception as e:
            logger.error(f"❌ Qdrant upsert failed (page {page_index}): {e}")


def process_pdf(pdf_path: Path):
    logger.info(f"🚀 Traitement: {pdf_path.name}")
    status_file = STATUS_DIR / f"{pdf_path.stem}.status"
    try:
        status_file.write_text("processing")

        meta_path = pdf_path.with_suffix(".meta.json")
        user_meta = {}
        if meta_path.exists():
            try:
                user_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                logger.info("📎 Meta utilisateur détectée")
            except Exception as e:
                logger.warning(f"⚠️ Meta invalide: {e}")

        pdf_text = extract_text_from_pdf(pdf_path)
        gpt_meta = analyze_pdf_metadata(pdf_text, pdf_path.name)
        doc_meta = {**user_meta, **gpt_meta}

        logger.info("🖼️ Génération PNG des pages")
        images = convert_from_path(str(pdf_path))
        image_paths = {}
        for i, img in enumerate(images, start=1):
            img_path = SLIDES_PNG / f"{pdf_path.stem}_page_{i}.png"
            img.save(img_path, "PNG")
            image_paths[i] = img_path

        # Pour chaque page, on peut tenter d'extraire le texte associé (ici, on utilise le texte global)
        total_chunks = 0
        for page_index, img_path in image_paths.items():
            logger.info(f"📸 Page {page_index}/{len(image_paths)}")
            # Optionnel : extraire le texte de la page individuellement si besoin
            chunks = ask_gpt_slide_analysis(
                img_path, pdf_text, pdf_path.name, page_index
            )
            logger.info(f"🧩 Page {page_index}: chunks générés = {len(chunks)}")
            ingest_chunks(chunks, doc_meta, pdf_path.stem, page_index)
            total_chunks += len(chunks)

        try:
            DOCS_DONE.mkdir(parents=True, exist_ok=True)
            shutil.move(str(pdf_path), str(DOCS_DONE / f"{pdf_path.stem}.pdf"))
            if meta_path.exists():
                shutil.move(
                    str(meta_path), str(DOCS_DONE / f"{pdf_path.stem}.meta.json")
                )
        except Exception as e:
            logger.warning(f"⚠️ Déplacement terminé avec avertissement: {e}")

        status_file.write_text("done")
        logger.info(f"✅ Terminé: {pdf_path.name} — total chunks: {total_chunks}")

    except Exception as e:
        logger.error(f"❌ Erreur durant {pdf_path.name}: {e}")
        try:
            status_file.write_text("error")
        except Exception:
            pass


def main():
    ensure_dirs()
    logger.info("🔎 Scan du dossier DOCS_IN")
    if not DOCS_IN.exists():
        logger.error(f"❌ DOCS_IN n'existe pas: {DOCS_IN}")
        return

    files = list(DOCS_IN.glob("*.pdf"))
    logger.info(f"📦 Fichiers .pdf détectés: {len(files)}")
    if not files:
        logger.info("ℹ️ Aucun .pdf à traiter")
        return

    for file in files:
        logger.info(f"➡️ Fichier détecté: {file.name}")
        process_pdf(file)


if __name__ == "__main__":
    main()
