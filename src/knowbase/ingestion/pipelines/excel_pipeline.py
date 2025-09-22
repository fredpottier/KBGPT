# Enrichissement des paires Q/A avant injection dans Qdrant

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import openpyxl
import pandas as pd
from langdetect import detect
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from qdrant_client.models import PointStruct
from knowbase.common.clients import (
    ensure_qdrant_collection,
    ensure_qa_collection,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.common.llm_router import LLMRouter, TaskType

from knowbase.common.logging import setup_logging
from knowbase.config.paths import ensure_directories
from knowbase.config.settings import get_settings
from knowbase.api.services.sap_solutions import get_sap_solutions_manager

# === CONFIGURATION ===
settings = get_settings()

DOCS_IN = settings.docs_in_dir
DOCS_DONE = settings.docs_done_dir
LOGS_DIR = settings.logs_dir
ensure_directories([DOCS_IN, DOCS_DONE, LOGS_DIR])
logger = setup_logging(LOGS_DIR, "ingest_excel_enriched.log")

# Modèle d'embedding : utilise la même logique que ingest_pptx_via_gpt.py
EMB_MODEL_NAME = settings.embeddings_model
GPT_MODEL_CANONICALIZE = "gpt-3.5-turbo-1106"
GPT_MODEL_ENRICH = "gpt-4o"
QA_COLLECTION_NAME = settings.qdrant_qa_collection


llm_router = LLMRouter()
qdrant_client = get_qdrant_client()
model = get_sentence_transformer(EMB_MODEL_NAME, device="cpu")
embedding_size = model.get_sentence_embedding_dimension()
if embedding_size is None:
    raise RuntimeError("SentenceTransformer returned no embedding dimension")
EMB_SIZE = int(embedding_size)
ensure_qa_collection(EMB_SIZE)

# === UTILITAIRES ===


def standardize_solution_name(raw_solution: str) -> str:
    """
    Standardise le nom d'une solution SAP en utilisant le nouveau gestionnaire de solutions.
    Remplace l'ancienne logique LLM par une approche basée sur le dictionnaire YAML.
    """
    try:
        canonical_name, solution_id = get_sap_solutions_manager().resolve_solution(raw_solution)
        logger.info(f"📋 Solution standardisée: '{raw_solution}' → '{canonical_name}' (ID: {solution_id})")
        return canonical_name
    except Exception as e:
        logger.warning(f"⚠️ Erreur standardisation solution: {e}")
        return raw_solution.strip()


def enrich_and_ingest_chunks(
    input_text: str, answer: str, meta: dict[str, Any], xlsx_path: Path
) -> int:
    if not input_text or not answer or len(answer.split()) < 3 or len(input_text) < 5:
        return 0

    content = ""  # <-- Ajout ici
    try:
        prompt = f"""
You are an assistant specialized in SAP RFP document processing.

You receive a customer input (which can be a question or a statement) and its corresponding answer.

Your task is to:
1. If the input is not a well-formed question, reformulate it into 1 to 3 clear questions.
2. Detect if the answer covers several different sub-topics, and split accordingly.
3. For each sub-topic or reformulated question, generate:
   - A clear standalone question
   - A concise standalone answer, based solely on the original answer content.

🛡️ Important rules:
- If the question or answer contains the name of a company (e.g., "{meta.get("client", "")}"), replace it by a neutral placeholder:
   - In French: use "le client"
   - In English: use "the customer"
   - Choose based on the language of the text.
- Do NOT add explanations or summaries.
- ❌ If the answer is only a reference to another question/answer (e.g., "please refer to question XX", "vous reporter à la réponse YY", "see our answer to question XX", etc.), then IGNORE this input completely and return an **empty JSON array**.

Return the result as a JSON array like:
[
  {{ "question": "...", "answer": "..." }},
  ...
]

Original Input:
{input_text}

Original Answer:
{answer}
"""
        enrich_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": prompt,
        }
        enrich_messages: list[ChatCompletionMessageParam] = [enrich_message]
        content_raw = llm_router.complete(TaskType.SHORT_ENRICHMENT, enrich_messages)
        if not isinstance(content_raw, str):
            logger.warning("⚠️ LLM enrich returned no textual content")
            return 0
        content = content_raw.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"```$", "", content)
            content = content.strip()

        # Nettoyer le contenu JSON pour éviter les erreurs de parsing
        import json as json_module

        def clean_json_content(content: str) -> str:
            """Nettoie le contenu JSON en supprimant/échappant les caractères de contrôle."""
            # Supprimer tous les caractères de contrôle sauf \n, \r, \t qui seront échappés
            content = ''.join(char for char in content if ord(char) >= 32 or char in '\n\r\t')

            # Échapper les caractères de contrôle restants dans les valeurs JSON
            content = re.sub(r'(?<!\\)\n', '\\n', content)
            content = re.sub(r'(?<!\\)\r', '\\r', content)
            content = re.sub(r'(?<!\\)\t', '\\t', content)
            return content

        try:
            parsed = json_module.loads(content)
        except json_module.JSONDecodeError:
            # Tentative de correction automatique pour les caractères de contrôle
            content_cleaned = clean_json_content(content)
            try:
                parsed = json_module.loads(content_cleaned)
            except json_module.JSONDecodeError as e:
                logger.warning(f"⚠️ JSON parsing failed even after cleaning: {e}")
                logger.warning(f"⚠️ Problematic content (first 200 chars): {content_cleaned[:200]!r}")
                return 0
        if not isinstance(parsed, list):
            logger.warning("⚠️ GPT enrich result is not a list")
            return 0
        chunks: list[dict[str, Any]] = [
            chunk for chunk in parsed if isinstance(chunk, dict)
        ]
    except Exception as e:
        logger.warning(f"⚠️ GPT enrich error: {e} | content={content}")
        return 0

    success_count = 0
    canonical_value = meta.get("canonical_solution")
    canonical_solution = (
        canonical_value if isinstance(canonical_value, str) else ""
    )

    for chunk in chunks:
        raw_question = chunk.get("question")
        raw_answer = chunk.get("answer")
        q = raw_question.strip() if isinstance(raw_question, str) else ""
        a = raw_answer.strip() if isinstance(raw_answer, str) else ""
        if len(q) < 5 or len(a.split()) < 3:
            continue
        try:
            payload = {
                "title": f"RFP {meta.get('client','')} - {canonical_solution}",
                "document_type": "Customer RFP",
                "main_solution": canonical_solution,
                "solutions": [canonical_solution],
                "rfp_question": q,
                "rfp_answer": a,
                "text": f"Q: {q}\nA: {a}",
                "language": detect(f"{q} {a}").lower()[:2],
                "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "source": xlsx_path.name,
                "client": meta.get("client"),
                "source_date": meta.get("source_date"),
            }
            emb = model.encode([f"passage: Q: {q}\nA: {a}"], normalize_embeddings=True)[
                0
            ].tolist()
            qdrant_client.upsert(
                collection_name=QA_COLLECTION_NAME,
                points=[PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload)],
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"⚠️ Chunk upsert error: {e}")
    return success_count


def get_visible_sheet_name(xlsx_path: Path) -> Optional[str]:
    """Fonction legacy pour retrouver le premier onglet visible."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    for sheet in wb.worksheets:
        if sheet.sheet_state == "visible":
            return sheet.title
    return None


def get_target_sheet_name(xlsx_path: Path, meta: dict[str, Any]) -> Optional[str]:
    """Détermine l'onglet cible : soit celui spécifié dans les meta, soit le premier visible."""
    # Si l'utilisateur a spécifié un onglet via la nouvelle interface
    if "sheet_name" in meta and isinstance(meta["sheet_name"], str):
        specified_sheet = meta["sheet_name"].strip()
        if specified_sheet:
            # Vérifier que l'onglet existe et est visible
            wb = openpyxl.load_workbook(xlsx_path, read_only=True)
            for sheet in wb.worksheets:
                if sheet.title == specified_sheet and sheet.sheet_state == "visible":
                    logger.info(f"📋 Utilisation de l'onglet spécifié : {specified_sheet}")
                    return specified_sheet
            logger.warning(f"⚠️ Onglet spécifié '{specified_sheet}' non trouvé ou invisible, fallback automatique")

    # Fallback : utiliser le premier onglet visible (comportement legacy)
    fallback_sheet = get_visible_sheet_name(xlsx_path)
    if fallback_sheet:
        logger.info(f"📋 Utilisation de l'onglet par défaut : {fallback_sheet}")
    return fallback_sheet


def excel_colname_to_index(colname: str) -> int:
    colname = colname.upper()
    index = 0
    for c in colname:
        index = index * 26 + (ord(c) - ord("A") + 1)
    return index - 1


def reformulate_as_question(text: str) -> str:
    prompt = f"""
You are an assistant. Reformulate the following instruction or statement into a clear, standalone question in the same language. Only reply with the question, nothing else.

Instruction:
{text}
"""
    try:
        reformulate_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": prompt,
        }
        reformulate_messages: list[ChatCompletionMessageParam] = [
            reformulate_message
        ]
        content = llm_router.complete(TaskType.CANONICALIZATION, reformulate_messages)
        if not isinstance(content, str):
            raise ValueError("Missing reformulation content")
        question = content.strip()
        return question
    except Exception as e:
        logger.warning(f"⚠️ GPT reformulation error: {e}")
        return text


# === TRAITEMENT PRINCIPAL ===


def process_excel_rfp(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    print(f"▶️ Fichier : {path.name}")
    meta_path = path.with_suffix(".meta.json")
    user_meta = {}
    if meta_path.exists():
        try:
            user_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            logger.info(f"📎 Meta utilisateur détectée pour {path.name}")
        except Exception as e:
            logger.warning(f"⚠️ Meta invalide pour {path.name}: {e}")
    meta = {**meta, **user_meta}
    required_keys = ["solution", "question_col", "answer_col"]
    missing = [k for k in required_keys if not meta.get(k)]
    if missing:
        logger.error(
            f"❌ Fichier {path.name} ignoré : meta manquante pour {', '.join(missing)}"
        )
        print(f"❌ Fichier ignoré : meta manquante pour {', '.join(missing)}")
        return {"status": "failed", "chunks_inserted": 0, "error": f"Meta manquante pour {', '.join(missing)}"}

    solution_value = meta.get("solution")
    question_col_value = meta.get("question_col")
    answer_col_value = meta.get("answer_col")
    if not isinstance(solution_value, str):
        logger.error(f"❌ Meta 'solution' invalide pour {path.name}")
        return {"status": "failed", "chunks_inserted": 0, "error": "Meta 'solution' invalide"}
    if not isinstance(question_col_value, str) or not isinstance(
        answer_col_value, str
    ):
        logger.error(f"❌ Colonnes question/réponse invalides pour {path.name}")
        return {"status": "failed", "chunks_inserted": 0, "error": "Colonnes question/réponse invalides"}

    meta["canonical_solution"] = standardize_solution_name(solution_value)
    question_col = question_col_value
    answer_col = answer_col_value

    # Utiliser la nouvelle logique de sélection d'onglet
    target_sheet = get_target_sheet_name(path, meta)
    if not target_sheet:
        logger.error(f"❌ Aucun onglet approprié trouvé dans {path.name}")
        print(f"❌ Aucun onglet approprié trouvé dans {path.name}")
        return {"status": "failed", "chunks_inserted": 0, "error": "Aucun onglet approprié trouvé"}

    try:
        df = pd.read_excel(path, sheet_name=target_sheet, header=None)
        df = df.fillna("").astype(str)
        q_idx = excel_colname_to_index(question_col)
        a_idx = excel_colname_to_index(answer_col)
        logger.info(f"q_idx={q_idx}, a_idx={a_idx}")
    except Exception as e:
        logger.error(f"❌ Erreur lecture Excel : {e}")
        return {"status": "failed", "chunks_inserted": 0, "error": f"Erreur lecture Excel : {e}"}

    total = 0
    for i in df.index:
        raw_input = str(df.iat[i, q_idx]).strip()
        answer = str(df.iat[i, a_idx]).strip()

        # Nouveau contrôle pour ignorer les titres/entêtes
        skip_keywords = {
            "requirements",
            "explanation",
            "comment",
            "section",
            "header",
            "title",
        }
        if (
            len(raw_input) < 5
            or len(answer.split()) < 3
            or raw_input.lower() in skip_keywords
            or answer.lower() in skip_keywords
            or raw_input.isupper()
        ):
            continue

        # Reformule systématiquement en question
        question = reformulate_as_question(raw_input)

        added = enrich_and_ingest_chunks(question, answer, meta, path)
        if added:
            print(f"👉 Ligne {i} — {added} chunks ajoutés pour input : {question}")
            total += added

    print(f"✅ Terminé : {total} chunks enrichis injectés")
    try:
        DOCS_DONE.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(DOCS_DONE / path.name))
        if meta_path.exists():
            shutil.move(str(meta_path), str(DOCS_DONE / meta_path.name))
        print(f"📦 Déplacé dans docs_done : {path.name}")
    except Exception as e:
        print(f"⚠️ Déplacement échoué : {e}")

    return {"status": "completed", "chunks_inserted": total}


def main() -> None:
    for file in DOCS_IN.glob("*.xlsx"):
        meta_path = file.with_suffix(".meta.json")
        if not meta_path.exists():
            logger.error(f"❌ Fichier ignoré : meta {meta_path.name} absent")
            print(f"❌ Fichier ignoré : meta {meta_path.name} absent")
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"❌ Fichier ignoré : meta {meta_path.name} invalide ({e})")
            print(f"❌ Fichier ignoré : meta {meta_path.name} invalide ({e})")
            continue
        process_excel_rfp(file, meta)


if __name__ == "__main__":
    main()
