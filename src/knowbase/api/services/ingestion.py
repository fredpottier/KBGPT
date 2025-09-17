from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, DefaultDict
from urllib.parse import quote, unquote

from fastapi import UploadFile
from knowbase.common.clients import (
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import Settings
from knowbase.ingestion.queue import (
    enqueue_excel_ingestion,
    enqueue_fill_excel,
    enqueue_pdf_ingestion,
    enqueue_pptx_ingestion,
)
from qdrant_client.models import FieldCondition, Filter, MatchValue


PUBLIC_URL = os.getenv("PUBLIC_URL", "sapkb.ngrok.app")
TOP_K = 10
SCORE_THRESHOLD = 0.5


def normalize_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    name = re.sub(r"[^\w\-]", "_", name)
    return f"{name}{ext}"


def urlify_image_url(url_or_name: str) -> str:
    if "/" in url_or_name:
        parts = url_or_name.split("/")
        parts[-1] = quote(parts[-1])
        return "/".join(parts)
    return quote(url_or_name)


def get_canonical_solution_name(
    user_solution_name: str,
    *,
    settings: Settings,
) -> tuple[str, set[str]]:
    qdrant_client = get_qdrant_client()
    existing_solutions = qdrant_client.scroll(
        collection_name=settings.qdrant_collection,
        limit=1000,
        with_payload=["main_solution", "type"],
        scroll_filter=None,
    )
    solution_names: set[str] = set()
    for point in existing_solutions[0]:
        payload: dict[str, Any] = point.payload or {}
        if payload.get("type") == "rfp_qa":
            name = payload.get("main_solution")
            if isinstance(name, str) and name:
                solution_names.add(name)

    prompt = (
        f"L'utilisateur a saisi le nom de solution suivant : '{user_solution_name}'.\n"
        f"Voici la liste des solutions connues :\n{list(solution_names)}\n"
        "Donne uniquement le nom canonique le plus proche, ou une liste de suggestions si aucune correspondance parfaite."
    )
    openai_client = get_openai_client()
    response = openai_client.chat.completions.create(
        model=os.getenv("GPT_MODEL", "gpt-4o"),
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


def _build_markdown_from_results(results, *, logger) -> dict[str, Any]:
    from knowbase.common.clients import get_sentence_transformer

    thumbnails_md = "## 📸 Aperçus\n\n"
    filtered_thumbs = [
        r
        for r in results
        if r.payload
        and r.payload.get("slide_image_url")
        and r.payload.get("slide_index")
        and r.payload.get("source_file_url")
    ]
    filtered_thumbs = sorted(filtered_thumbs, key=lambda r: r.score, reverse=True)[:4]

    for r in filtered_thumbs:
        payload = r.payload or {}
        slide_image_url = payload.get("slide_image_url", "")
        image_name = os.path.basename(slide_image_url) if slide_image_url else ""
        slide_num = payload.get("slide_index", "?")
        thumb_url = f"https://{PUBLIC_URL}/static/thumbnails/{urlify_image_url(image_name)}"
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
    sources_map: DefaultDict[str, dict[str, Any]] = defaultdict(
        lambda: {"slides": [], "file_url": "", "type": "pptx"}
    )

    for r in results:
        payload = r.payload or {}
        source_file_url = payload.get("source_file_url", "")
        file_url = f"https://{PUBLIC_URL}/static/presentations/{urlify_image_url(os.path.basename(source_file_url))}"
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
        source_md += f"- [{title}]({source_meta['file_url']}) — {source_meta['type'].upper()}\n"

    answer_markdown = f"{thumbnails_md}{text_md}{source_md}"
    logger.debug(f"[SEARCH] Markdown généré pour la réponse :\n{answer_markdown}")
    return {"answer_markdown": answer_markdown, "status": "success", "action": "search"}


def handle_dispatch(
    *,
    request,
    action_type: str | None,
    document_type: str | None,
    question: str | None,
    file: UploadFile | None,
    meta: str | None,
    settings: Settings,
    logger,
) -> dict[str, Any]:
    qdrant_client = get_qdrant_client()
    embedding_model = get_sentence_transformer()

    if action_type == "search":
        if not question:
            return {"error": "Missing 'question' for action_type=search"}
        vector = embedding_model.encode(question)
        if hasattr(vector, 'tolist'):
            vector = vector.tolist()
        elif hasattr(vector, 'numpy'):
            vector = vector.numpy().tolist()
        vector = [float(x) for x in vector]
        results = qdrant_client.search(
            collection_name=settings.qdrant_collection,
            query_vector=vector,
            limit=TOP_K,
            with_payload=True,
            query_filter=Filter(
                must_not=[FieldCondition(key="type", match=MatchValue(value="rfp_qa"))]
            ),
        )
        filtered = [r for r in results if r.score >= SCORE_THRESHOLD]
        if not filtered:
            return {
                "action": "search",
                "status": "no_results",
                "answer_markdown": "Aucune information pertinente n’a été trouvée dans la base de connaissance.",
            }
        return _build_markdown_from_results(filtered, logger=logger)

    if action_type == "ingest":
        if not file or not document_type:
            return {"error": "Missing 'file' or 'document_type' for action_type=ingest"}

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = normalize_filename(file.filename or "uploaded")
        base_name = Path(safe_filename).stem if safe_filename else "uploaded"
        uid = f"{base_name}__{now}"
        docs_in = settings.docs_in_dir
        docs_in.mkdir(parents=True, exist_ok=True)

        document_kind = document_type.lower()
        if document_kind not in {"pptx", "pdf", "xlsx"}:
            return {"error": f"Unsupported document_type: {document_type}"}

        saved_path = docs_in / f"{uid}.{document_kind}"
        with open(saved_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        meta_dict: dict[str, Any] = {}
        meta_path: Path | None = None
        if meta:
            meta_dict = json.loads(meta)
            meta_path = docs_in / f"{uid}.meta.json"
            with open(meta_path, "w", encoding="utf-8") as f_meta:
                json.dump(meta_dict, f_meta, indent=2)

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

        return {
            "action": "ingest",
            "status": "queued",
            "job_id": job.id,
            "uid": uid,
            "filename": file.filename,
            "message": f"File received and queued for {document_kind} ingestion.",
        }

    if action_type == "fill_excel":
        if not file:
            return {"error": "Missing 'file' for action_type=fill_excel"}
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(file.filename).stem if file.filename else "questions"
        uid = f"{base_name}__{now}"

        docs_in = settings.docs_in_dir
        docs_in.mkdir(parents=True, exist_ok=True)
        saved_path = docs_in / f"{uid}.xlsx"
        meta_path = docs_in / f"{uid}.meta.json"

        with open(saved_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        meta_json: dict[str, Any] = json.loads(meta) if meta else {}
        user_solution = meta_json.get("solution")
        if user_solution:
            canonical_name, solution_names = get_canonical_solution_name(
                user_solution, settings=settings
            )
            if canonical_name not in solution_names:
                return {
                    "action": "fill_excel",
                    "status": "error",
                    "message": f"Aucune correspondance parfaite pour '{user_solution}'. Suggestions : {canonical_name}",
                }
            meta_json["solution"] = canonical_name
        with open(meta_path, "w", encoding="utf-8") as f_meta:
            json.dump(meta_json, f_meta, indent=2)

        job = enqueue_fill_excel(
            job_id=uid, file_path=str(saved_path), meta_path=str(meta_path)
        )
        return {
            "action": "fill_excel",
            "status": "queued",
            "job_id": job.id,
            "uid": uid,
            "filename": file.filename,
            "message": "Fichier recu et traitement place dans la file.",
        }

    return {"error": f"Unknown action_type: {action_type}. Expected 'search' or 'ingest'."}


__all__ = ["handle_dispatch"]







