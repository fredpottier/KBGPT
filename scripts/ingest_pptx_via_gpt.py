# ingest_pptx_via_gpt.py — version améliorée avec contexte global & thumbnails
import base64
import debugpy
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from openai import OpenAI
from langdetect import detect, DetectorFactory
from pdf2image import convert_from_path
from pptx import Presentation
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from import_logging import setup_logging
from claims_utils import extract_claims_from_chunk, check_claim_conflicts


# Custom HTTP client to ignore system envs (e.g., proxies)
class CustomHTTPClient(httpx.Client):
    def __init__(self, *args, **kwargs):
        kwargs.pop("proxies", None)
        super().__init__(*args, **kwargs, trust_env=False)


# Paths
def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()
DOCS_IN = PROJECT_ROOT / "docs_in"
DOCS_DONE = PROJECT_ROOT / "public_files" / "presentations"
SLIDES_PNG = PROJECT_ROOT / "public_files" / "slides"
THUMBNAILS_DIR = PROJECT_ROOT / "public_files" / "thumbnails"
STATUS_DIR = PROJECT_ROOT / "status"
LOGS_DIR = PROJECT_ROOT / "logs"
MODELS_DIR = PROJECT_ROOT / "models"

os.environ.setdefault("HF_HOME", str(MODELS_DIR))

# Config
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "sap_kb")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")
EMB_MODEL_NAME = os.getenv("EMB_MODEL_NAME", "intfloat/multilingual-e5-base")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logger = setup_logging(LOGS_DIR, "ingest_debug.log")
DetectorFactory.seed = 0


# Helpers
def ensure_dirs():
    for d in [
        DOCS_IN,
        DOCS_DONE,
        SLIDES_PNG,
        THUMBNAILS_DIR,
        STATUS_DIR,
        LOGS_DIR,
        MODELS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd, timeout=120):
    try:
        subprocess.run(cmd, check=True, timeout=timeout)
        return True
    except Exception as e:
        logger.error(f"Command failed ({e}): {' '.join(cmd)}")
    return False


def encode_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def clean_gpt_response(raw: str) -> str:
    s = (raw or "").strip()
    for delim in ("```json", "```"):
        if s.startswith(delim):
            s = s[len(delim) :].strip()
        if s.endswith(delim):
            s = s[: -len(delim)].strip()
    return s


def get_language_iso2(text: str) -> str:
    try:
        return detect(text)
    except:
        return "en"


def embed_texts(texts: List[str]) -> List[List[float]]:
    batched = [f"passage: {t}" for t in texts]
    return model.encode(batched, normalize_embeddings=True, convert_to_numpy=False)


# Inits
client = OpenAI(api_key=OPENAI_API_KEY, http_client=CustomHTTPClient())
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
model = SentenceTransformer(EMB_MODEL_NAME)
EMB_SIZE = model.get_sentence_embedding_dimension()
if not qdrant.collection_exists(QDRANT_COLLECTION):
    qdrant.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(size=EMB_SIZE, distance=Distance.COSINE),
    )


# Pipeline
MAX_TOKENS_THRESHOLD = 40000  # seuil pour basculer en mode résumé partiel
MAX_PARTIAL_TOKENS = 8000  # Taille max d'un résumé partiel
MAX_SUMMARY_TOKENS = 60000


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


def estimate_tokens(text: str) -> int:
    # Estimation simple : 1 token ≈ 0.75 mot
    return int(len(text.split()) / 0.75)


def summarize_large_pptx(slides_data: List[Dict[str, Any]]) -> str:
    """
    Si le texte total est trop long, découpe en blocs et fait des résumés partiels.
    Si le texte final est encore trop long, fait un résumé global via GPT.
    Retourne un texte synthétique global.
    """
    all_text = "\n\n".join(
        (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
        for slide in slides_data
        if slide.get("text", "") or slide.get("notes", "")
    )
    total_tokens = estimate_tokens(all_text)
    if total_tokens <= MAX_TOKENS_THRESHOLD:
        return all_text

    # Découpe en batchs selon le nombre de tokens
    batches = chunk_slides_by_tokens(slides_data, MAX_PARTIAL_TOKENS)
    partial_summaries = []
    for batch in batches:
        batch_text = "\n\n".join(
            (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
            for slide in batch
            if slide.get("text", "") or slide.get("notes", "")
        )
        prompt = (
            "You are given a partial excerpt of a PowerPoint deck. "
            "Summarize the key objectives and topics in 5–8 sentences. "
            "Preserve all SAP solution names, objectives, document types, audience, and dates mentioned.\n"
            f"Text:\n{batch_text[:40000]}"
        )
        try:
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise summarization assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=MAX_PARTIAL_TOKENS,
            )
            raw = getattr(response.choices[0].message, "content", "") or ""
            summary = clean_gpt_response(raw)
            partial_summaries.append(summary)
        except Exception as e:
            logger.error(f"❌ Partial summary error: {e}")
            continue

    final_summary = "\n".join(partial_summaries)
    # Si le résumé final est trop long, tu peux refaire un passage GPT pour le réduire
    if estimate_tokens(final_summary) > MAX_SUMMARY_TOKENS:
        prompt = (
            "You are given a concatenation of partial summaries from a PowerPoint deck. "
            "Write a concise global summary (max 8 sentences) covering all main objectives, topics, and SAP solutions mentioned.\n"
            f"Text:\n{final_summary[:MAX_SUMMARY_TOKENS*2]}"
        )
        try:
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise summarization assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=MAX_SUMMARY_TOKENS,
            )
            raw = getattr(response.choices[0].message, "content", "") or ""
            final_summary = clean_gpt_response(raw)
        except Exception as e:
            logger.error(f"❌ Global summary reduction error: {e}")
            final_summary = final_summary[: MAX_SUMMARY_TOKENS * 100]  # fallback

    return final_summary


def analyze_deck_summary(slides_data: List[Dict[str, Any]], source_name: str) -> dict:
    logger.info(f"🔍 GPT: analyse du deck via texte extrait — {source_name}")

    summary_text = summarize_large_pptx(slides_data)

    prompt = (
        "You are given a global text summary from a PowerPoint slide deck.\n\n"
        "Return a single JSON object with two fields:\n"
        '- "summary": a concise thematic summary (3-5 sentences) of the deck\'s main purpose and intended audience.\n'
        '- "metadata": a JSON object with the following fields:\n'
        "    - title\n    - objective\n    - main_solution\n    - supporting_solutions\n"
        "    - mentioned_solutions\n    - document_type\n    - audience\n    - source_date\n    - language\n\n"
        "IMPORTANT:\n"
        "- For 'main_solution', always use the official SAP canonical solution name as published by SAP.\n"
        "- For 'supporting_solutions', only consider SAP Solutions and always use the official SAP canonical solution name.\n"
        "- Do not use acronyms, abbreviations, or local variants.\n"
        "- If unsure, leave the field empty.\n"
        "- Return only the JSON object — no explanation.\n\n"
        f"Global summary text:\n{summary_text}"
    )

    try:
        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise SAP document metadata extraction assistant.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        raw = getattr(response.choices[0].message, "content", "") or ""
        cleaned = clean_gpt_response(raw)
        result = json.loads(cleaned) if cleaned else {}
        if not isinstance(result, dict):
            result = {}
        logger.debug(
            f"Deck summary + metadata keys: {list(result.keys()) if result else 'n/a'}"
        )
        return result
    except Exception as e:
        logger.error(f"❌ GPT metadata error: {e}")
        return {}


def generate_thumbnail(image_path: Path) -> Path:
    img = Image.open(image_path)
    img.thumbnail((300, 300), Image.LANCZOS)
    thumb_path = THUMBNAILS_DIR / image_path.name
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(thumb_path, "PNG")
    return thumb_path


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


def normalize_public_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip().rstrip("/")
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    return u


def resolve_soffice_path() -> str:
    cand = os.getenv("SOFFICE_PATH", "").strip()
    if cand and Path(cand).exists():
        return cand
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return found or "/usr/bin/soffice"


PUBLIC_URL = normalize_public_url(os.getenv("PUBLIC_URL", "sapkb.ngrok.app"))
SOFFICE_PATH = resolve_soffice_path()


def convert_pptx_to_pdf(pptx_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"📄 Conversion PPTX→PDF: {pptx_path.name}")
    ok = run_cmd(
        [
            SOFFICE_PATH,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(pptx_path),
        ],
        timeout=180,
    )
    pdf_path = output_dir / (pptx_path.stem + ".pdf")
    if not ok or not pdf_path.exists():
        raise RuntimeError("LibreOffice conversion failed or PDF missing")
    logger.debug(f"PDF path: {pdf_path} (exists={pdf_path.exists()})")
    return pdf_path


def extract_notes_and_text(pptx_path: Path) -> List[Dict[str, Any]]:
    logger.info(f"📊 Extraction texte+notes du PPTX: {pptx_path.name}")
    prs = Presentation(str(pptx_path))
    slides_data = []
    for i, slide in enumerate(prs.slides, start=1):
        # Notes
        notes = ""
        if getattr(slide, "has_notes_slide", False):
            notes_slide = getattr(slide, "notes_slide", None)
            if notes_slide and hasattr(notes_slide, "notes_text_frame"):
                tf = notes_slide.notes_text_frame
                if tf and hasattr(tf, "text"):
                    notes = (tf.text or "").strip()

        # Textes
        texts = []
        for shape in slide.shapes:
            txt = getattr(shape, "text", None)
            if isinstance(txt, str) and txt.strip():
                texts.append(txt.strip())

        slides_data.append(
            {
                "slide_index": i,
                "text": "\n".join(texts),
                "notes": notes,
            }
        )
    logger.debug(f"Slides parsed: {len(slides_data)}")
    return slides_data


def ask_gpt_slide_analysis(
    image_path, deck_summary, slide_index, source_name, text, notes, retries=2
):
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    prompt_text = (
        f"Global deck summary:\n{deck_summary}\n\n"
        f"Slide {slide_index} extracted text:\n{text}\n\n"
        f"Slide {slide_index} notes:\n{notes}\n\n"
        f"Analyze slide {slide_index} ('{source_name}').\n\n"
        "You are analyzing a single PowerPoint slide. Your goal is to extract its meaning and value for use in a knowledge base.\n"
        "Describe the **visual content** in detail — if there is a diagram, process flow, table, chart, or architecture, explain what it shows and what its key message is.\n\n"
        "Return a JSON array where each item includes:\n"
        "1. 'full_explanation' (string): a complete, detailed explanation of what this slide conveys, combining textual and visual content.\n"
        "2. 'metadata' (object):\n"
        "   - 'slide_title': extracted or inferred title of the slide\n"
        "   - 'slide_type': one of ['title', 'agenda', 'content', 'summary', 'transition']\n"
        "   - 'insight_level': one of ['descriptive', 'analytical', 'strategic'] depending on how deep the insight goes\n"
        "   - 'topic': main topic covered by this slide (ex: SLA, SAP BTP, forecasting...)\n"
        "   - 'mentioned_solutions': list of all software solutions or platforms mentioned, including both SAP and non-SAP.\n"
        "       - For SAP solutions, use the official SAP canonical names (e.g. 'SAP S/4HANA Cloud', not 'S4').\n"
        "       - For non-SAP solutions (e.g. Salesforce, Azure, Snowflake), use the commonly known brand or product name.\n"
        "   - 'contains_visuals': true if this slide includes diagrams, charts, tables, etc.\n"
        "   - 'language': 'fr' or 'en', based on content\n"
        "   - 'section': if this slide belongs to a named section of the deck, include it\n"
        "   - 'applies_to': {\n"
        "       'generic_categories': liste de catégories parentes (ex: ['SAP Cloud Services']),\n"
        "       'scope': liste de tags de portée (ex: ['global','multi-product'] ou ['product-specific']),\n"
        "       'is_all_sap_cloud': true/false,\n"
        "       'statement': explication courte en langage naturel de la portée\n"
        "   }\n"
        "Instructions:\n"
        "- Si le slide concerne les SAP Cloud Services en général, ne liste pas tous les produits enfants, mais tague comme global/multi-product.\n"
        "- Utilise un langage professionnel, clair et concis.\n"
        "- Ne pas inventer d'information. Laisse vide ou null si tu n'es pas sûr.\n"
        "- Retourne uniquement le tableau JSON, sans texte supplémentaire ni commentaire."
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
            resp = client.chat.completions.create(
                model=GPT_MODEL, messages=msg, temperature=0.2, max_tokens=1024
            )
            logger.debug(
                f"GPT response for slide {slide_index}: {resp.choices[0].message.content!r}"
            )
            items = json.loads(clean_gpt_response(resp.choices[0].message.content))
            enriched = []
            for it in items:
                expl = it.get("full_explanation", "")
                if expl:
                    for seg in recursive_chunk(expl, max_len=400, overlap_ratio=0.15):
                        enriched.append({**it, "full_explanation": seg})
            return enriched
        except Exception as e:
            logger.warning(f"Slide {slide_index} attempt {attempt} failed: {e}")
            time.sleep(2 * (attempt + 1))
    return []


def ingest_chunks(chunks, doc_meta, file_uid, slide_index, deck_summary):
    valid = [ch for ch in chunks if ch.get("full_explanation", "").strip()]
    if not valid:
        logger.info(f"Slide {slide_index}: no valid chunks")
        return
    texts = [ch["full_explanation"] for ch in valid]
    embs = embed_texts(texts)
    points = []
    for ch, emb in zip(valid, embs):
        applies_to = validate_applies_to(ch.get("metadata", {}).get("applies_to", {}))
        logger.info(f"Slide {slide_index}: applies_to = {applies_to}")
        payload = {
            "text": ch["full_explanation"].strip(),
            "language": get_language_iso2(ch["full_explanation"]),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "gpt_chunked": True,
            "slide_index": slide_index,
            "slide_image_url": f"{PUBLIC_URL}/static/slides/{file_uid}_slide_{slide_index}.png",
            "source_file_url": f"{PUBLIC_URL}/static/presentations/{file_uid}.pptx",
            "source_name": f"{file_uid}.pptx",
            "source_type": "pptx",
            "doc_meta": doc_meta,
            "deck_summary": deck_summary,
            "chunk_meta": ch.get("meta", {}),
            "tags": ch.get("meta", {}).get("tags", []),
            "claim_tag": "Valid",
            "applies_to": applies_to,
        }
        points.append(PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload))
    qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points)
    logger.info(f"Slide {slide_index}: ingested {len(points)} chunks")


def process_pptx(pptx_path: Path):
    logger.info(f"start ingestion for {pptx_path.name}")
    ensure_dirs()
    pdf_path = convert_pptx_to_pdf(pptx_path, SLIDES_PNG)
    slides_data = extract_notes_and_text(pptx_path)
    deck_info = analyze_deck_summary(slides_data, pptx_path.name)
    summary = deck_info.get("summary", "")
    metadata = deck_info.get("metadata", {})
    images = convert_from_path(str(pdf_path), output_folder=None)
    image_paths = {}
    for i, img in enumerate(images, start=1):
        img_path = THUMBNAILS_DIR / f"{pptx_path.stem}_slide_{i}.png"
        img.save(img_path, "PNG")
        image_paths[i] = img_path
        generate_thumbnail(img_path)
    tasks = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for slide in slides_data:
            idx = slide["slide_index"]
            text = slide["text"]
            notes = slide["notes"]
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
                        ),
                    )
                )
    total = 0
    for idx, future in tasks:
        chunks = future.result() or []
        ingest_chunks(chunks, metadata, pptx_path.stem, idx, summary)
        total += len(chunks)
    shutil.move(str(pptx_path), DOCS_DONE / f"{pptx_path.stem}.pptx")
    logger.info(f"Done {pptx_path.name} — total chunks: {total}")


def merge_metadata(meta_list):
    # Fusionne les listes de solutions, audience, etc.
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
    }
    for meta in meta_list:
        # Fusionne intelligemment chaque champ (exemple pour les listes)
        for k in ["supporting_solutions", "mentioned_solutions", "audience"]:
            merged[k].extend(meta.get(k, []))
        # Pour les champs uniques, garde le premier non vide
        for k in [
            "main_solution",
            "document_type",
            "source_date",
            "language",
            "objective",
            "title",
        ]:
            if not merged[k] and meta.get(k):
                merged[k] = meta[k]
    # Déduplique les listes
    for k in ["supporting_solutions", "mentioned_solutions", "audience"]:
        merged[k] = list(set(merged[k]))
    return merged


def validate_applies_to(applies_to):
    # Validation simple du champ applies_to
    if not isinstance(applies_to, dict):
        return {
            "generic_categories": [],
            "scope": [],
            "is_all_sap_cloud": None,
            "statement": "",
        }
    out = {}
    out["generic_categories"] = (
        applies_to.get("generic_categories")
        if isinstance(applies_to.get("generic_categories"), list)
        else []
    )
    out["scope"] = (
        applies_to.get("scope") if isinstance(applies_to.get("scope"), list) else []
    )
    out["is_all_sap_cloud"] = (
        bool(applies_to.get("is_all_sap_cloud"))
        if "is_all_sap_cloud" in applies_to
        else None
    )
    out["statement"] = (
        applies_to.get("statement")
        if isinstance(applies_to.get("statement"), str)
        else ""
    )
    return out


def main():
    ensure_dirs()
    if len(sys.argv) > 1:
        pptx_path = Path(sys.argv[1])
        if pptx_path.exists():
            process_pptx(pptx_path)
        else:
            logger.error(f"File not found: {pptx_path}")
    else:
        logger.error("No file path provided as argument.")


if __name__ == "__main__":
    main()
