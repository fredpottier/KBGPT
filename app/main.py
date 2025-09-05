import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, quote
from collections import defaultdict

from fastapi import FastAPI, File, Form, UploadFile, APIRouter, Request, Body
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from import_logging import setup_logging

# === DEBUG (optionnel) ===
import debugpy

if os.getenv("DEBUG_MODE") == "true":
    print("🔧 Attaching debugpy on port 5678...")
    debugpy.listen(("0.0.0.0", 5678))
    print("En attente du débogueur VS Code...", flush=True)
    debugpy.wait_for_client()
    print("✅ Debugger attached!")

# === CONFIGURATION ===
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "sap_kb"
TOP_K = 10
SCORE_THRESHOLD = 0.5

ROOT = Path(__file__).parent.parent.resolve()
DOCS_IN = ROOT / "docs_in"
DOCS_DONE = ROOT / "public_files" / "presentations"
SLIDES_PNG = ROOT / "public_files" / "slides"
STATUS_DIR = ROOT / "status"
LOGS_DIR = ROOT / "logs"
logger = setup_logging(LOGS_DIR, "app_debug.log")
PUBLIC_DIR = ROOT / "public_files"
SLIDES_DIR = PUBLIC_DIR / "slides"
PPTX_DIR = PUBLIC_DIR / "presentations"

qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
# MODEL_NAME = "sentence-transformers/paraphrase-xlm-r-multilingual-v1"
MODEL_NAME = os.getenv("EMB_MODEL_NAME", "intfloat/multilingual-e5-base")
model = SentenceTransformer(MODEL_NAME)

app = FastAPI()
router = APIRouter()

OPENAPI_PATH = Path(__file__).parent / "openapi.json"
with open(OPENAPI_PATH, "r", encoding="utf-8") as f:
    custom_openapi_spec = json.load(f)
app.openapi = lambda: custom_openapi_spec

app.mount("/static/slides", StaticFiles(directory=SLIDES_DIR), name="slides")
app.mount(
    "/static/presentations", StaticFiles(directory=PPTX_DIR), name="presentations"
)


class SearchRequest(BaseModel):
    question: str
    language: Optional[str] = None
    mime: Optional[str] = None


@app.post("/search")
async def search_qdrant(req: SearchRequest):
    try:
        query = req.question.strip()
        query_vector = model.encode(query)
        if hasattr(query_vector, "tolist"):
            query_vector = query_vector.tolist()
        elif hasattr(query_vector, "numpy"):
            query_vector = query_vector.numpy().tolist()
        query_vector = [float(x) for x in query_vector]

        results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=TOP_K,
            with_payload=True,
        )
        filtered = [r for r in results if r.score >= SCORE_THRESHOLD]
        if not filtered:
            return {
                "status": "no_results",
                "results": [],
                "message": "Aucune information pertinente n’a été trouvée dans la base de connaissance.",
            }

        # On retourne à GPT uniquement les infos essentielles pour chaque chunk
        response_chunks = []
        for r in filtered:
            payload = r.payload or {}
            response_chunks.append(
                {
                    "text": payload.get("text", ""),
                    "source_file": payload.get("source_file_url", ""),
                    "slide_index": payload.get("slide_index", ""),
                    "score": r.score,
                }
            )

        return {"status": "success", "results": response_chunks}
    except Exception as e:
        return {"status": "error", "message": f"Erreur : {str(e)}"}


@app.post("/dispatch")
async def dispatch_action(
    request: Request,
    action_type: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    question: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    meta: Optional[str] = Form(None),
):
    print("=== /dispatch call received ===")
    print(f"action_type: {action_type}")
    print(f"document_type: {document_type}")
    print(f"question: {question}")
    print(f"meta (raw): {meta}")
    if file:
        print(f"file: {file.filename} ({file.content_type})")
    print("================================")

    if action_type == "search":
        if not question:
            return {"error": "Missing 'question' for action_type=search"}
        try:
            query_vector = model.encode(question)
            if hasattr(query_vector, "tolist"):
                query_vector = query_vector.tolist()
            elif hasattr(query_vector, "numpy"):
                query_vector = query_vector.numpy().tolist()
            query_vector = [float(x) for x in query_vector]

            results = qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=TOP_K,
                with_payload=True,
            )
            filtered = [r for r in results if r.score >= SCORE_THRESHOLD]
            if not filtered:
                return {
                    "action": "search",
                    "status": "no_results",
                    "answer_markdown": "Aucune information pertinente n’a été trouvée dans la base de connaissance.",
                }

            # Filtre les chunks avec slide_image_url, slide_index, source_file_url
            filtered_thumbs = [
                r
                for r in filtered
                if r.payload
                and r.payload.get("slide_image_url")
                and r.payload.get("slide_index")
                and r.payload.get("source_file_url")
            ]
            # Trie par score décroissant et garde les 4 premiers
            filtered_thumbs = sorted(
                filtered_thumbs, key=lambda r: r.score, reverse=True
            )[:4]

            # --- Génération du markdown amélioré ---
            thumbnails_md = "## 📸 Aperçus\n\n"
            for r in filtered_thumbs:
                payload = r.payload
                slide_image_url = payload.get("slide_image_url")
                image_name = os.path.basename(slide_image_url)
                slide_num = payload.get("slide_index", "?")
                # Utilise le numéro de slide comme texte alternatif
                thumb_url = f"https://sapkb.ngrok.app/static/thumbnails/{urlify_image_url(image_name)}"
                encoded_image_name = quote(image_name)
                hd_url = slide_image_url.replace(image_name, encoded_image_name)
                thumbnails_md += f"[![Slide {slide_num}]({thumb_url})]({hd_url}) "

            thumbnails_md += "\n\n---\n\n"

            text_md = ""
            source_md = "**📎 Sources**\n\n"
            sources_map = defaultdict(
                lambda: {"slides": [], "file_url": "", "type": "pptx"}
            )

            for r in filtered:
                payload = r.payload or {}
                file_url = f"https://sapkb.ngrok.app/static/presentations/{urlify_image_url(os.path.basename(payload.get('source_file_url', '')))}"
                filename = payload.get("source_file_url", "").split("/")[-1]
                file_title = unquote(filename)
                slide_num = payload.get("slide_index", "?")
                caption = payload.get("text", "").strip().split("\n")[0][:80]

                text_md += f"- {caption}  \n*({file_title}, slide {slide_num})*\n\n"
                sources_map[file_title]["file_url"] = file_url
                sources_map[file_title]["slides"].append(slide_num)

            for title, meta in sources_map.items():
                source_md += (
                    f"- [{title}]({meta['file_url']}) — {meta['type'].upper()}\n"
                )

            answer_markdown = f"{thumbnails_md}{text_md}{source_md}"
            logger.debug(
                f"[SEARCH] Markdown généré pour la réponse :\n{answer_markdown}"
            )

            return {
                "action": "search",
                "status": "success",
                "answer_markdown": answer_markdown,
            }

        except Exception as e:
            return {"action": "search", "status": "error", "error": str(e)}

    elif action_type == "ingest":
        if not file or not document_type:
            return {"error": "Missing 'file' or 'document_type' for action_type=ingest"}

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Normalise le nom du fichier
        safe_filename = normalize_filename(file.filename)
        base_name = Path(safe_filename).stem if safe_filename else "uploaded"
        uid = f"{base_name}__{now}"

        DOCS_IN.mkdir(parents=True, exist_ok=True)

        # Détermination du script et extension selon le type de document
        if document_type.lower() == "pptx":
            saved_path = DOCS_IN / f"{uid}.pptx"
            script_to_run = "/scripts/ingest_pptx_via_gpt.py"
        elif document_type.lower() == "pdf":
            saved_path = DOCS_IN / f"{uid}.pdf"
            script_to_run = "/scripts/ingest_pdf_via_gpt.py"
        elif document_type.lower() == "xlsx":
            saved_path = DOCS_IN / f"{uid}.xlsx"
            script_to_run = "/scripts/ingest_excel_via_gpt.py"
        else:
            return {"error": f"Unsupported document_type: {document_type}"}

        with open(saved_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        if meta:
            try:
                meta_path = DOCS_IN / f"{uid}.meta.json"
                with open(meta_path, "w", encoding="utf-8") as f_meta:
                    json.dump(json.loads(meta), f_meta, indent=2)
            except Exception as e:
                return {"error": f"Invalid meta JSON: {e}"}

        try:
            subprocess.Popen(
                ["python", script_to_run, str(saved_path)],
                cwd="/scripts",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            return {
                "action": "ingest",
                "status": "error",
                "error": f"Launch error: {e}",
            }

        return {
            "action": "ingest",
            "status": "processing",
            "uid": uid,
            "filename": file.filename,
            "message": f"File received and ingestion launched in background for {document_type}.",
        }

    elif action_type == "fill_excel":
        if not file:
            return {"error": "Missing 'file' for action_type=fill_excel"}
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(file.filename).stem if file.filename else "questions"
        uid = f"{base_name}__{now}"

        DOCS_IN.mkdir(parents=True, exist_ok=True)
        saved_path = DOCS_IN / f"{uid}.xlsx"
        meta_path = DOCS_IN / f"{uid}.meta.json"

        # Sauvegarde du fichier Excel
        with open(saved_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        # Sauvegarde du fichier meta
        try:
            with open(meta_path, "w", encoding="utf-8") as f_meta:
                meta_json = json.loads(meta)
                # Contrôle du nom canonique de la solution
                user_solution = meta_json.get("solution")
                if user_solution:
                    canonical_name, solution_names = get_canonical_solution_name(
                        user_solution
                    )
                    if canonical_name not in solution_names:
                        logger.error(
                            f"Aucune correspondance parfaite pour '{user_solution}'. Suggestions : {canonical_name}"
                        )
                        return {
                            "action": "fill_excel",
                            "status": "error",
                            "message": f"Aucune correspondance parfaite pour '{user_solution}'. Suggestions : {canonical_name}",
                        }
                    # Remplace le nom de solution par le nom canonique
                    meta_json["solution"] = canonical_name
                json.dump(meta_json, f_meta, indent=2)
        except Exception as e:
            return {"error": f"Invalid meta JSON: {e}"}

        # Lancement du script fillEmptyExcel.py en arrière-plan
        try:
            subprocess.Popen(
                ["python", "fill_empty_excel.py", str(saved_path), str(meta_path)],
                cwd="/scripts",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            return {
                "action": "fill_excel",
                "status": "error",
                "error": f"Launch error: {e}",
            }

        return {
            "action": "fill_excel",
            "status": "processing",
            "uid": uid,
            "filename": file.filename,
            "message": "Fichier reçu et traitement lancé en arrière-plan.",
        }

    else:
        return {
            "error": f"Unknown action_type: {action_type}. Expected 'search' or 'ingest'."
        }


@router.get("/status/{uid}")
async def get_status(uid: str):
    # Chemin du fichier traité
    filled_path = DOCS_DONE / f"{uid}_filled.xlsx"
    if filled_path.exists():
        return {
            "action": "fill_excel",
            "status": "done",
            "download_url": f"https://sapkb.ngrok.app/static/presentations/{uid}_filled.xlsx",
        }
    else:
        # Optionnel : vérifier si une erreur a été loguée
        return {"action": "fill_excel", "status": "processing"}


def get_canonical_solution_name(user_solution_name):
    # Recherche des solutions existantes dans Qdrant
    # (extraction des valeurs distinctes du champ "main_solution")
    existing_solutions = qdrant_client.scroll(
        collection_name=COLLECTION_NAME,
        limit=1000,
        with_payload=["main_solution", "type"],  # récupère uniquement ces champs
        scroll_filter=None,
    )
    solution_names = set()
    for point in existing_solutions[0]:
        if point.payload.get("type") == "rfp_qa_enriched":
            name = point.payload.get("main_solution")
            if name:
                solution_names.add(name)

    # Utilise GPT pour trouver le nom canonique le plus proche
    prompt = (
        f"L'utilisateur a saisi le nom de solution suivant : '{user_solution_name}'.\n"
        f"Voici la liste des solutions connues :\n{list(solution_names)}\n"
        "Donne uniquement le nom canonique le plus proche, ou une liste de suggestions si aucune correspondance parfaite."
    )
    response = openai_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=100,
    )
    canonical_name = response.choices[0].message.content.strip()
    return canonical_name, solution_names


def normalize_filename(filename: str) -> str:
    # Remplace les espaces et caractères spéciaux par "_"
    name, ext = os.path.splitext(filename)
    name = re.sub(r"[^\w\-]", "_", name)  # garde lettres, chiffres, tirets
    return f"{name}{ext}"


def urlify_image_url(url_or_name: str) -> str:
    """
    Remplace les espaces et caractères spéciaux dans le nom de fichier ou l'URL par leur encodage URL.
    Si une URL complète est passée, encode uniquement le nom de fichier à la fin.
    """
    # Si c'est une URL complète, on encode juste le nom du fichier
    if "/" in url_or_name:
        parts = url_or_name.split("/")
        parts[-1] = quote(parts[-1])
        return "/".join(parts)
    else:
        return quote(url_or_name)


# ... définition des routes sur router ...

app.include_router(router)
