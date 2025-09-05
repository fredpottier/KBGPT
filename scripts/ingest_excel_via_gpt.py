# Enrichissement des paires Q/A avant injection dans Qdrant

import os
import uuid
import json
import shutil
import logging
import re
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from langdetect import detect
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import OpenAI
import openpyxl
from import_logging import setup_logging

# === CONFIGURATION ===
ROOT = Path(__file__).parent.parent.resolve()
DOCS_IN = ROOT / "docs_in"
DOCS_DONE = ROOT / "docs_done"
LOGS_DIR = ROOT / "logs"
CACHE_MODELS = ROOT / "models"
COLLECTION_NAME = "sap_kb"
# EMB_MODEL_NAME = "intfloat/multilingual-e5-base"
GPT_MODEL_CANONICALIZE = "gpt-3.5-turbo-1106"
GPT_MODEL_ENRICH = "gpt-4o"

os.environ["HF_HOME"] = str(CACHE_MODELS)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = setup_logging(LOGS_DIR, "ingest_excel_enriched.log")

# === QDRANT SETUP ===
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
MODEL_NAME = "sentence-transformers/paraphrase-xlm-r-multilingual-v1"
model = SentenceTransformer(MODEL_NAME, device="cpu")
EMB_SIZE = model.get_sentence_embedding_dimension()
if not qdrant.collection_exists(COLLECTION_NAME):
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMB_SIZE, distance=Distance.COSINE),
    )

# === UTILITAIRES ===


def standardize_solution_name(raw_solution: str) -> str:
    try:
        messages = [
            {
                "role": "system",
                "content": "You are an expert in SAP product naming conventions. Only reply with the official SAP solution name, without quotes, explanations, or any extra text.",
            },
            {
                "role": "user",
                "content": f"Here is a solution name or abbreviation: {raw_solution}\nWhat is the official SAP product name? Only reply with the name itself.",
            },
        ]
        response = client.chat.completions.create(
            model=GPT_MODEL_CANONICALIZE,
            messages=messages,
            temperature=0,
            max_tokens=20,
        )
        name = response.choices[0].message.content.strip()
        return name.split("\n")[0].replace('"', "").replace("'", "").strip()
    except Exception as e:
        logger.warning(f"⚠️ GPT standardization error: {e}")
        return raw_solution.strip()


def enrich_and_ingest_chunks(input_text, answer, meta, xlsx_path):
    if not input_text or not answer or len(answer.split()) < 3 or len(input_text) < 5:
        return 0

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

🛡️ Important:
- If the question or answer contains the name of a company (e.g., "{meta.get("client", "")}"), replace it by a neutral placeholder:
   - In French: use "le client"
   - In English: use "the customer"
   - Choose based on the language of the text.
- Do NOT add explanations or summaries.

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
        response = client.chat.completions.create(
            model=GPT_MODEL_ENRICH,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"```$", "", content)
            content = content.strip()
        chunks = json.loads(content)
    except Exception as e:
        logger.warning(f"⚠️ GPT enrich error: {e}")
        return 0

    success_count = 0
    canonical_solution = meta.get("canonical_solution", "")

    for chunk in chunks:
        q = chunk.get("question", "").strip()
        a = chunk.get("answer", "").strip()
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
                "type": "rfp_qa_enriched",
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


def get_visible_sheet_name(xlsx_path: Path) -> str:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    for sheet in wb.worksheets:
        if sheet.sheet_state == "visible":
            return sheet.title
    return None


def excel_colname_to_index(colname):
    colname = colname.upper()
    index = 0
    for c in colname:
        index = index * 26 + (ord(c) - ord("A") + 1)
    return index - 1


def reformulate_as_question(text):
    prompt = f"""
You are an assistant. Reformulate the following instruction or statement into a clear, standalone question in the same language. Only reply with the question, nothing else.

Instruction:
{text}
"""
    try:
        response = client.chat.completions.create(
            model=GPT_MODEL_CANONICALIZE,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        )
        question = response.choices[0].message.content.strip()
        return question
    except Exception as e:
        logger.warning(f"⚠️ GPT reformulation error: {e}")
        return text


# === TRAITEMENT PRINCIPAL ===


def process_excel_rfp(path: Path, meta: dict):
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

    meta["canonical_solution"] = standardize_solution_name(meta["solution"])
    question_col = meta["question_col"]
    answer_col = meta["answer_col"]
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
        raw_input = df.iat[i, q_idx].strip()
        answer = df.iat[i, a_idx].strip()

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


def main():
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
