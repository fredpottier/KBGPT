import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, DefaultDict, Optional, TypedDict
from urllib.parse import quote, unquote

# === DEBUG (optionnel) ===
import debugpy
from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from import_logging import setup_logging
from pydantic import BaseModel
from qdrant_client.models import FieldCondition, Filter, MatchValue
from ingestion.job_queue import (
    enqueue_excel_ingestion,
    enqueue_fill_excel,
    enqueue_pdf_ingestion,
    enqueue_pptx_ingestion,
    fetch_job,
)
from utils.shared_clients import (
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)

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
GPT_MODEL = "gpt-4o"

# MODEL_NAME = "sentence-transformers/paraphrase-xlm-r-multilingual-v1"
qdrant_client = get_qdrant_client()
model = get_sentence_transformer()
openai_client = get_openai_client()

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
app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")


class SearchRequest(BaseModel):
    question: str
    language: Optional[str] = None
    mime: Optional[str] = None


class SourceMetadata(TypedDict):
    slides: list[str]
    file_url: str
    type: str


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

        query_filter = Filter(
            must_not=[FieldCondition(key="type", match=MatchValue(value="rfp_qa"))]
        )
        results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=TOP_K,
            with_payload=True,
            query_filter=query_filter,
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
            slide_image_url = payload.get("slide_image_url", "") if payload else ""
            if slide_image_url:
                slide_image_url = f"https://sapkb.ngrok.app/static/thumbnails/{os.path.basename(slide_image_url)}"
            response_chunks.append(
                {
                    "text": payload.get("text", ""),
                    "source_file": payload.get("source_file_url", ""),
                    "slide_index": payload.get("slide_index", ""),
                    "score": r.score,
                    "slide_image_url": slide_image_url,  # <-- Ajout ici
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

            query_filter = Filter(
                must_not=[
                    FieldCondition(key="type", match=MatchValue(value="rfp_qa"))
                ]
            )
            results = qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=TOP_K,
                with_payload=True,
                query_filter=query_filter,
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
                slide_image_url = payload.get("slide_image_url", "") if payload else ""
                image_name = (
                    os.path.basename(slide_image_url) if slide_image_url else ""
                )
                slide_num = payload.get("slide_index", "?") if payload else ""
                # Utilise le numéro de slide comme texte alternatif
                thumb_url = f"https://sapkb.ngrok.app/static/thumbnails/{urlify_image_url(image_name)}"
                encoded_image_name = quote(image_name)
                hd_url = (
                    slide_image_url.replace(image_name, encoded_image_name)
                    if slide_image_url and image_name
                    else ""
                )
                thumbnails_md += f"[![Slide {slide_num}]({thumb_url})]({hd_url}) "

            thumbnails_md += "\n\n---\n\n"

            text_md = ""
            source_md = "**📎 Sources**\n\n"
            sources_map: DefaultDict[str, SourceMetadata] = defaultdict(
                lambda: SourceMetadata(slides=[], file_url="", type="pptx")
            )

            for r in filtered:
                payload = r.payload or {}
                source_file_url = payload.get("source_file_url", "") if payload else ""
                file_url = f"https://sapkb.ngrok.app/static/presentations/{urlify_image_url(os.path.basename(source_file_url))}"
                filename = payload.get("source_file_url", "").split("/")[-1]
                file_title = unquote(filename)
                raw_slide_index = payload.get("slide_index")
                slide_num = str(raw_slide_index) if raw_slide_index is not None else "?"
                caption = (payload.get("text") or "").strip().split("\n")[0][:80]

                text_md += f"- {caption}  \n*({file_title}, slide {slide_num})*\n\n"
                source_entry = sources_map[file_title]
                source_entry["file_url"] = file_url
                source_entry["slides"].append(slide_num)

            for title, source_meta in sources_map.items():
                source_md += (
                    f"- [{title}]({source_meta['file_url']}) — {source_meta['type'].upper()}\n"
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
        safe_filename = normalize_filename(file.filename or "uploaded")
        base_name = Path(safe_filename).stem if safe_filename else "uploaded"
        uid = f"{base_name}__{now}"

        DOCS_IN.mkdir(parents=True, exist_ok=True)

        document_kind = document_type.lower()
        if document_kind not in {"pptx", "pdf", "xlsx"}:
            return {"error": f"Unsupported document_type: {document_type}"}

        saved_path = DOCS_IN / f"{uid}.{document_kind}"
        with open(saved_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        meta_dict: dict[str, Any] = {}
        meta_path: Optional[Path] = None
        if meta:
            try:
                meta_dict = json.loads(meta)
            except Exception as e:
                return {"error": f"Invalid meta JSON: {e}"}
            meta_path = DOCS_IN / f"{uid}.meta.json"
            with open(meta_path, "w", encoding="utf-8") as f_meta:
                json.dump(meta_dict, f_meta, indent=2)

        try:
            if document_kind == "pptx":
                job = enqueue_pptx_ingestion(
                    job_id=uid,
                    file_path=str(saved_path),
                    document_type=meta_dict.get("document_type", "default"),
                    meta_path=str(meta_path) if meta_path else None,
                )
            elif document_kind == "pdf":
                job = enqueue_pdf_ingestion(job_id=uid, file_path=str(saved_path))
            else:
                job = enqueue_excel_ingestion(
                    job_id=uid,
                    file_path=str(saved_path),
                    meta=meta_dict or None,
                )
        except Exception as e:
            return {
                "action": "ingest",
                "status": "error",
                "error": f"Queue error: {e}",
            }

        return {
            "action": "ingest",
            "status": "queued",
            "job_id": job.id,
            "uid": uid,
            "filename": file.filename,
            "message": f"File received and queued for {document_kind} ingestion.",
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

        with open(saved_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        try:
            with open(meta_path, "w", encoding="utf-8") as f_meta:
                meta_json = json.loads(meta) if meta else {}
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
                    meta_json["solution"] = canonical_name
                json.dump(meta_json, f_meta, indent=2)
        except Exception as e:
            return {"error": f"Invalid meta JSON: {e}"}

        try:
            job = enqueue_fill_excel(
                job_id=uid, file_path=str(saved_path), meta_path=str(meta_path)
            )
        except Exception as e:
            return {
                "action": "fill_excel",
                "status": "error",
                "error": f"Queue error: {e}",
            }

        return {
            "action": "fill_excel",
            "status": "queued",
            "job_id": job.id,
            "uid": uid,
            "filename": file.filename,
            "message": "Fichier recu et traitement place dans la file.",
        }

    else:
        return {
            "error": f"Unknown action_type: {action_type}. Expected 'search' or 'ingest'."
        }


@router.get("/status/{uid}")
async def get_status(uid: str):
    job = fetch_job(uid)
    if job is None:
        return {"action": "unknown", "status": "not_found"}

    job_type = str(job.meta.get("job_type", "unknown"))
    status = job.get_status(refresh=True)

    if job.is_failed:
        return {"action": job_type, "status": "error", "message": job.exc_info}

    if job.is_finished:
        result = job.result if isinstance(job.result, dict) else {}
        response = {"action": job_type, "status": "done"}
        output_path = result.get("output_path")
        if output_path:
            filename = os.path.basename(output_path)
            response["download_url"] = f"https://sapkb.ngrok.app/static/presentations/{filename}"
        if result:
            response["result"] = result
        return response

    if status in {"started", "queued", "deferred"}:
        return {"action": job_type, "status": "processing"}

    return {"action": job_type, "status": status}





def get_canonical_solution_name(
    user_solution_name: str,
) -> tuple[str, set[str]]:
    # Recherche des solutions existantes dans Qdrant
    # (extraction des valeurs distinctes du champ "main_solution")
    existing_solutions = qdrant_client.scroll(
        collection_name=COLLECTION_NAME,
        limit=1000,
        with_payload=["main_solution", "type"],  # récupère uniquement ces champs
        scroll_filter=None,
    )
    solution_names: set[str] = set()
    for point in existing_solutions[0]:
        payload: dict[str, Any] = point.payload or {}
        if payload.get("type") == "rfp_qa":
            name = payload.get("main_solution")
            if isinstance(name, str) and name:
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
    canonical_name = user_solution_name
    if response.choices:
        first_choice = response.choices[0]
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", None) if message else None
        if isinstance(content, str) and content.strip():
            canonical_name = content.strip()
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
