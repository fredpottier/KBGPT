# Enrichissement des paires Q/A avant injection dans Qdrant

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import openpyxl
import pandas as pd
from langdetect import detect
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from import_logging import setup_logging

# === CONFIGURATION ===
ROOT = Path(__file__).parent.parent.resolve()
DOCS_IN = ROOT / "docs_in"
DOCS_DONE = ROOT / "docs_done"
LOGS_DIR = ROOT / "logs"
CACHE_MODELS = ROOT / "models"
os.environ["HF_HOME"] = str(CACHE_MODELS)
logger = setup_logging(LOGS_DIR, "ingest_excel_enriched.log")

# Modèle d'embedding : utilise la même logique que ingest_pptx_via_gpt.py
EMB_MODEL_NAME = os.getenv("EMB_MODEL_NAME", "intfloat/multilingual-e5-base")
GPT_MODEL_CANONICALIZE = "gpt-3.5-turbo-1106"
GPT_MODEL_ENRICH = "gpt-4o"
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "sap_kb")


# Custom HTTP client (optionnel, comme dans ingest_pptx_via_gpt.py)
class CustomHTTPClient(httpx.Client):
    def __init__(self, *args, **kwargs):
        kwargs.pop("proxies", None)
        super().__init__(*args, **kwargs, trust_env=False)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY, http_client=CustomHTTPClient())
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
model = SentenceTransformer(EMB_MODEL_NAME, device="cpu")
embedding_size = model.get_sentence_embedding_dimension()
if embedding_size is None:
    raise RuntimeError("SentenceTransformer returned no embedding dimension")
EMB_SIZE = int(embedding_size)
if not qdrant.collection_exists(COLLECTION_NAME):
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMB_SIZE, distance=Distance.COSINE),
    )

# === UTILITAIRES ===


def standardize_solution_name(raw_solution: str) -> str:
    try:
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are an expert in SAP product naming conventions. Only reply with the official SAP solution name, without quotes, explanations, or any extra text.",
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": f"Here is a solution name or abbreviation: {raw_solution}\nWhat is the official SAP product name? Only reply with the name itself.",
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        response = client.chat.completions.create(
            model=GPT_MODEL_CANONICALIZE,
            messages=messages,
            temperature=0,
            max_tokens=20,
        )
        if not response.choices:
            raise ValueError("Empty completion choices")
        message = getattr(response.choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not isinstance(content, str):
            raise ValueError("Missing completion content")
        name = content.strip()
        return name.split("\n")[0].replace('"', "").replace("'", "").strip()
    except Exception as e:
        logger.warning(f"⚠️ GPT standardization error: {e}")
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
        response = client.chat.completions.create(
            model=GPT_MODEL_ENRICH,
            messages=enrich_messages,
            temperature=0.3,
            max_tokens=1000,
        )
        if not response.choices:
            return 0
        message = getattr(response.choices[0], "message", None)
        content_raw = getattr(message, "content", None) if message else None
        if not isinstance(content_raw, str):
            logger.warning("⚠️ GPT enrich returned no textual content")
            return 0
        content = content_raw.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"```$", "", content)
            content = content.strip()
        parsed = json.loads(content)
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
                "type": "rfp_qa",
                "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "source": xlsx_path.name,
                "client": meta.get("client"),
                "source_date": meta.get("source_date"),
            }
            emb = model.encode([f"passage: Q: {q}\nA: {a}"], normalize_embeddings=True)[
                0
            ].tolist()
            qdrant.upsert(
                collection_name=COLLECTION_NAME,
                points=[PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload)],
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"⚠️ Chunk upsert error: {e}")
    return success_count


def get_visible_sheet_name(xlsx_path: Path) -> Optional[str]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    for sheet in wb.worksheets:
        if sheet.sheet_state == "visible":
            return sheet.title
    return None


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
        response = client.chat.completions.create(
            model=GPT_MODEL_CANONICALIZE,
            messages=reformulate_messages,
            temperature=0,
            max_tokens=100,
        )
        if not response.choices:
            raise ValueError("Empty reformulation response")
        message = getattr(response.choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not isinstance(content, str):
            raise ValueError("Missing reformulation content")
        question = content.strip()
        return question
    except Exception as e:
        logger.warning(f"⚠️ GPT reformulation error: {e}")
        return text


# === TRAITEMENT PRINCIPAL ===


def process_excel_rfp(path: Path, meta: dict[str, Any]) -> None:
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
        return

    solution_value = meta.get("solution")
    question_col_value = meta.get("question_col")
    answer_col_value = meta.get("answer_col")
    if not isinstance(solution_value, str):
        logger.error(f"❌ Meta 'solution' invalide pour {path.name}")
        return
    if not isinstance(question_col_value, str) or not isinstance(
        answer_col_value, str
    ):
        logger.error(f"❌ Colonnes question/réponse invalides pour {path.name}")
        return

    meta["canonical_solution"] = standardize_solution_name(solution_value)
    question_col = question_col_value
    answer_col = answer_col_value
    visible_sheet = get_visible_sheet_name(path)
    if not visible_sheet:
        logger.error(f"❌ Aucun onglet visible dans {path.name}")
        print(f"❌ Aucun onglet visible dans {path.name}")
        return

    try:
        df = pd.read_excel(path, sheet_name=visible_sheet, header=None)
        df = df.fillna("").astype(str)
        q_idx = excel_colname_to_index(question_col)
        a_idx = excel_colname_to_index(answer_col)
        logger.info(f"q_idx={q_idx}, a_idx={a_idx}")
    except Exception as e:
        logger.error(f"❌ Erreur lecture Excel : {e}")
        return

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
