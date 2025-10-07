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

from fastapi import UploadFile, HTTPException
import openpyxl
import pandas as pd
import tempfile
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
from knowbase.api.services.import_history_redis import get_redis_import_history_service
from qdrant_client.models import FieldCondition, Filter, MatchValue


PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")
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
        with_payload=["main_solution", "solution", "type"]
    )
    solution_names: set[str] = set()
    for point in existing_solutions[0]:
        payload: dict[str, Any] = point.payload or {}
        if payload.get("type") == "rfp_qa":
            # Nouveau format: solution.main
            if "solution" in payload and isinstance(payload["solution"], dict):
                solution_main = payload["solution"].get("main")
                if isinstance(solution_main, str) and solution_main.strip():
                    solution_names.add(solution_main.strip())

            # Ancien format: main_solution (pour rétrocompatibilité)
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
    document_type_id: str | None = None,
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

        # Enregistrer dans l'historique Redis
        history_service = get_redis_import_history_service()
        history_service.add_import_record(
            uid=uid,
            filename=file.filename or safe_filename,
            client=meta_dict.get("client"),
            topic=meta_dict.get("topic"),
            document_type=meta_dict.get("document_type"),
            language=meta_dict.get("language"),
            source_date=meta_dict.get("source_date"),
            solution=meta_dict.get("client"),  # Pour les documents PPTX/PDF, utiliser client comme solution
            import_type="document"
        )

        # Passer document_type_id si fourni, sinon fallback sur document_type legacy
        doc_type_for_pipeline = document_type_id if document_type_id else meta_dict.get("document_type", "default")

        if document_kind == "pptx":
            job = enqueue_pptx_ingestion(
                job_id=uid,
                file_path=str(saved_path),
                document_type_id=doc_type_for_pipeline,
                meta_path=str(meta_path) if meta_path else None,
            )
        elif document_kind == "pdf":
            job = enqueue_pdf_ingestion(
                job_id=uid,
                file_path=str(saved_path),
                document_type_id=doc_type_for_pipeline
            )
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


async def handle_excel_qa_upload(
    *,
    file: UploadFile,
    meta_file: UploadFile | None,
    settings: Settings,
    logger,
) -> dict[str, Any]:
    """Handle Excel Q/A upload for RFP collection."""

    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Fichier Excel (.xlsx/.xls) requis")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = normalize_filename(file.filename)
    base_name = Path(safe_filename).stem
    uid = f"{base_name}_qa_{now}"

    docs_in = settings.docs_in_dir
    docs_in.mkdir(parents=True, exist_ok=True)

    # Sauvegarder le fichier Excel
    saved_path = docs_in / f"{uid}.xlsx"
    with open(saved_path, "wb") as f_out:
        shutil.copyfileobj(file.file, f_out)

    # Sauvegarder le fichier meta si fourni
    meta_path = None
    if meta_file:
        meta_path = docs_in / f"{uid}.meta.json"
        with open(meta_path, "wb") as f_meta:
            shutil.copyfileobj(meta_file.file, f_meta)

    # Enregistrer dans l'historique Redis
    meta_dict = {}
    if meta_path and meta_path.exists():
        try:
            meta_dict = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Erreur lecture meta: {e}")

    history_service = get_redis_import_history_service()
    history_service.add_import_record(
        uid=uid,
        filename=file.filename,
        client=meta_dict.get("client"),
        topic="RFP Q/A",
        document_type="Excel Q/A",
        language=meta_dict.get("language"),
        source_date=meta_dict.get("source_date"),
        solution=meta_dict.get("solution"),  # Pour les Excel Q/A, utiliser solution des métadonnées
        import_type="excel_qa"
    )

    # Lancer le job d'import Q/A
    job = enqueue_excel_ingestion(
        job_id=uid,
        file_path=str(saved_path),
        meta=meta_dict or None,
    )

    return {
        "action": "excel_qa_upload",
        "status": "queued",
        "job_id": job.id,
        "uid": uid,
        "filename": file.filename,
        "message": "Fichier Excel Q/A reçu et mis en file pour traitement.",
    }


async def handle_excel_rfp_fill(
    *,
    file: UploadFile,
    meta_file: UploadFile | None,
    settings: Settings,
    logger,
) -> dict[str, Any]:
    """Handle Excel RFP fill request."""

    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Fichier Excel (.xlsx/.xls) requis")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = normalize_filename(file.filename)
    base_name = Path(safe_filename).stem
    uid = f"{base_name}_rfp_{now}"

    docs_in = settings.docs_in_dir
    docs_in.mkdir(parents=True, exist_ok=True)

    # Sauvegarder le fichier Excel
    saved_path = docs_in / f"{uid}.xlsx"
    with open(saved_path, "wb") as f_out:
        shutil.copyfileobj(file.file, f_out)

    # Sauvegarder le fichier meta si fourni
    meta_path = docs_in / f"{uid}.meta.json"
    if meta_file:
        with open(meta_path, "wb") as f_meta:
            shutil.copyfileobj(meta_file.file, f_meta)
    else:
        # Créer un meta par défaut
        default_meta = {
            "solution": "",
            "client": "",
            "source_date": datetime.now().isoformat().split('T')[0]
        }
        with open(meta_path, "w", encoding="utf-8") as f_meta:
            json.dump(default_meta, f_meta, indent=2)

    # Lire les métadonnées pour validation
    meta_dict = {}
    try:
        meta_dict = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Erreur lecture meta: {e}")

    # Enregistrer dans l'historique Redis
    history_service = get_redis_import_history_service()
    history_service.add_import_record(
        uid=uid,
        filename=file.filename,
        client=meta_dict.get("client"),
        topic="RFP Fill",
        document_type="Excel RFP",
        language=meta_dict.get("language"),
        source_date=meta_dict.get("source_date"),
        solution=meta_dict.get("solution"),  # Pour les Excel RFP, utiliser solution des métadonnées
        import_type="fill_rfp"
    )

    # Lancer le job de remplissage RFP
    job = enqueue_fill_excel(
        job_id=uid,
        file_path=str(saved_path),
        meta_path=str(meta_path)
    )

    return {
        "action": "excel_rfp_fill",
        "status": "queued",
        "job_id": job.id,
        "uid": uid,
        "filename": file.filename,
        "message": "Fichier RFP reçu et mis en file pour remplissage automatique.",
    }


async def analyze_excel_file(
    *,
    file: UploadFile,
    settings: Settings,
    logger,
) -> dict[str, Any]:
    """Analyse un fichier Excel pour identifier les onglets et colonnes disponibles."""

    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Fichier Excel (.xlsx/.xls) requis")

    try:
        # Sauvegarder temporairement le fichier
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp_file:
            contents = await file.read()
            temp_file.write(contents)
            temp_path = temp_file.name

        # Analyser les onglets avec openpyxl
        workbook = openpyxl.load_workbook(temp_path, read_only=True)
        sheets_info = []

        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]

            # Vérifier si l'onglet est visible
            if sheet.sheet_state == 'visible':
                # Analyser les colonnes avec contenu en utilisant pandas
                try:
                    df = pd.read_excel(temp_path, sheet_name=sheet_name, header=None, nrows=50)
                    df = df.fillna('')

                    # Identifier les colonnes avec contenu (au moins 1 cellule non vide pour permettre sélection colonnes vides pour RFP)
                    available_columns = []
                    sample_data = []

                    for col_idx in range(min(24, len(df.columns))):  # Limiter à 24 colonnes (A-X)
                        col_letter = chr(ord('A') + col_idx)
                        non_empty_count = (df.iloc[:, col_idx].astype(str).str.strip() != '').sum()

                        # Inclure toutes les colonnes qui ne sont pas complètement vides OU qui font partie des premières colonnes
                        # Cela permet de sélectionner des colonnes vides pour les réponses RFP
                        if non_empty_count >= 1 or col_idx < 10:  # Au moins 1 cellule avec contenu OU dans les 10 premières colonnes
                            available_columns.append({
                                'letter': col_letter,
                                'index': col_idx,
                                'non_empty_count': int(non_empty_count),
                                'is_mostly_empty': bool(non_empty_count < 3)  # Convertir en booléen Python natif
                            })

                    # Extraire les 50 premières lignes pour prévisualisation
                    for row_idx in range(min(50, len(df))):
                        row_data = []
                        for col_idx in range(min(24, len(df.columns))):
                            cell_value = str(df.iloc[row_idx, col_idx]).strip()
                            row_data.append(cell_value if cell_value != 'nan' else '')
                        sample_data.append(row_data)

                    sheets_info.append({
                        'name': sheet_name,
                        'available_columns': available_columns,
                        'sample_data': sample_data,
                        'total_rows': len(df),
                        'total_columns': min(24, len(df.columns))
                    })

                except Exception as e:
                    logger.warning(f"Erreur analyse onglet {sheet_name}: {e}")
                    continue

        # Nettoyer le fichier temporaire
        Path(temp_path).unlink()

        if not sheets_info:
            return {
                'error': 'Aucun onglet analysable trouvé dans le fichier Excel',
                'sheets': []
            }

        return {
            'success': True,
            'filename': file.filename,
            'sheets': sheets_info,
            'column_headers': [chr(ord('A') + i) for i in range(24)]  # A-X
        }

    except Exception as e:
        logger.error(f"Erreur analyse Excel: {e}")
        # Nettoyer le fichier temporaire en cas d'erreur
        try:
            Path(temp_path).unlink()
        except:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'analyse du fichier Excel: {str(e)}"
        )


__all__ = ["handle_dispatch", "handle_excel_qa_upload", "handle_excel_rfp_fill", "analyze_excel_file"]







