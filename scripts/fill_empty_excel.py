import os
import json
import uuid
from pathlib import Path
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from openpyxl import load_workbook
from import_logging import setup_logging  # Ajout gestion des logs

# === CONFIGURATION ===
ROOT = Path(__file__).parent.parent.resolve()
LOGS_DIR = ROOT / "logs"
REJECT_LOG = LOGS_DIR / "rejected_chunks.log"
NO_MATCH_LOG = LOGS_DIR / "questions_no_match.log"
logger = setup_logging(LOGS_DIR, "fill_empty_excel_debug.log")
MODEL_NAME = "sentence-transformers/paraphrase-xlm-r-multilingual-v1"
COLLECTION_NAME = "sap_kb"
GPT_MODEL = "gpt-4o"
client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
model = SentenceTransformer(MODEL_NAME)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def load_meta(meta_path):
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def search_qdrant(question, solution, top_k=5):
    emb = model.encode([f"passage: Q: {question}"], normalize_embeddings=True)[
        0
    ].tolist()
    # search_filter = Filter(
    #     must=[FieldCondition(key="main_solution", match=MatchValue(value=solution))]
    # )
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=emb,
            limit=top_k,
            # query_filter=search_filter,  # <-- filtre désactivé pour test
        )
        logger.info(f"Recherche Qdrant pour '{question}' : {len(results)} résultats")
        return results
    except Exception as e:
        logger.warning(f"Erreur Qdrant pour '{question}': {e}")
        return []


def build_gpt_answer(question, context_chunks):
    context = "\n\n".join([chunk.payload.get("text", "") for chunk in context_chunks])
    prompt = (
        f"Voici une question métier SAP :\n{question}\n\n"
        f"Voici des extraits de documents pouvant aider à répondre :\n{context}\n\n"
        "Utilise uniquement ces informations pour rédiger une réponse claire et concise à la question. "
        "Réponds uniquement dans la langue de la question. "
        "Si aucune information pertinente n'est trouvée, réponds uniquement par 'Aucune réponse trouvée'."
    )
    try:
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=512,
        )
        answer = response.choices[0].message.content.strip()
        logger.info(f"Réponse GPT pour '{question}': {answer[:80]}...")
        return answer
    except Exception as e:
        logger.warning(f"Erreur GPT pour '{question}': {e}")
        return "Aucune réponse trouvée"


def excel_col_letter_to_index(col_letter):
    col_letter = col_letter.upper()
    col_idx = 0
    for i, c in enumerate(reversed(col_letter)):
        col_idx += (ord(c) - ord("A") + 1) * (26**i)
    return col_idx - 1


def write_answers_to_excel(original_path, df, a_col_letter, a_col_idx):
    wb = load_workbook(original_path)
    ws = wb.active

    for idx, row in df.iterrows():
        answer = row[a_col_idx]
        if pd.notna(answer):
            excel_row = idx + 2  # +2 pour header + 1-index Excel
            ws.cell(row=excel_row, column=a_col_idx + 1, value=answer)  # index 1-based

    output_path = (
        Path(original_path).parent / f"{Path(original_path).stem}_answered.xlsx"
    )
    wb.save(output_path)
    print(f"✅ Fichier enrichi avec styles préservés : {output_path}")
    logger.info(f"✅ Fichier enrichi avec styles préservés : {output_path}")


def filter_chunks_with_gpt(question, chunks):
    prompt_template = (
        "Question : {question}\n\n"
        "Voici un extrait de document :\n\n"
        "{chunk}\n\n"
        "Est-ce que cet extrait est pertinent pour répondre à cette question ? Réponds uniquement par : OUI ou NON."
    )

    filtered = []
    rejected = []
    for chunk in chunks:
        chunk_text = chunk.payload.get("text", "")
        prompt = prompt_template.format(question=question, chunk=chunk_text)
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5,
            )
            if "oui" in response.choices[0].message.content.lower():
                filtered.append(chunk)
            else:
                rejected.append(chunk_text)
        except Exception as e:
            logger.warning(f"ChunkRAG GPT error: {e}")

    if rejected:
        with open(REJECT_LOG, "a", encoding="utf-8") as rej_log:
            for text in rejected:
                rej_log.write(
                    f"---\nQUESTION: {question}\nCHUNK NON RETENU:\n{text}\n\n"
                )

    return filtered


def clarify_question_with_gpt(question):
    prompt = (
        f"Voici une question métier posée dans un fichier Excel :\n\n"
        f"{question}\n\n"
        "Reformule cette question de façon claire et directe, comme si elle était posée dans un appel d'offre SAP."
        "Tu dois reformuler dans la même langue que la question d'origine."
    )
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Erreur clarification GPT : {e}")
        return question.strip()


def main(xlsx_path, meta_path):
    meta = load_meta(meta_path)
    df = pd.read_excel(
        xlsx_path, header=None
    )  # Pas de header pour éviter les problèmes de colonnes mergées
    solution = meta["solution"]

    logger.info(f"Traitement du fichier : {xlsx_path} ({len(df)} lignes)")

    wb = load_workbook(xlsx_path)
    visible_sheets = [
        sheet for sheet in wb.sheetnames if wb[sheet].sheet_state == "visible"
    ]
    if not visible_sheets:
        logger.error("Aucun onglet visible dans le fichier Excel.")
        return
    ws = wb[visible_sheets[0]]

    df = pd.read_excel(xlsx_path, header=None, sheet_name=visible_sheets[0])

    merged_cells = set()
    for rng in ws.merged_cells.ranges:
        for cell in rng.cells:
            merged_cells.add(ws.cell(row=cell[0], column=cell[1]).coordinate)

    q_idx = excel_col_letter_to_index(meta["question_col"])
    a_idx = excel_col_letter_to_index(meta["answer_col"])

    logger.debug(f"Colonnes du DataFrame : {df.columns}")
    logger.debug(f"q_idx calculé : {q_idx}")

    questions_analyzed = 0
    answers_inserted = 0

    for idx in df.index:
        # Affiche le contenu brut de la ligne
        logger.debug(f"Ligne {idx} brute : {df.iloc[idx].to_dict()}")
        try:
            question = str(df.iat[idx, q_idx]).strip()
        except Exception as e:
            logger.debug(f"⏭️ Ligne {idx} ignorée : erreur accès cellule ({e})")
            continue

        if (
            pd.isna(question)
            or question == ""
            or question.lower() == "nan"
            or question.count("\n") > 3
            or len(question) < 15
            or question.lower().startswith(("section", "1.", "2.", "3."))
        ):
            logger.debug(f"⏭️ Ligne ignorée : '{question}' (non question)")
            continue

        questions_analyzed += 1
        logger.info(f"💬 Question détectée : {question}")

        clarified_question = clarify_question_with_gpt(question)
        logger.info(f"Question clarifiée : {clarified_question}")

        results = search_qdrant(clarified_question, solution)
        if not results:
            logger.info(f"Aucun chunk trouvé pour la question : {clarified_question}")
            with open(NO_MATCH_LOG, "a", encoding="utf-8") as nomatch_log:
                nomatch_log.write(f"{clarified_question}\n")
            continue

        filtered_chunks = filter_chunks_with_gpt(clarified_question, results)
        if not filtered_chunks:
            logger.info(
                f"Aucun chunk pertinent pour la question : {clarified_question}"
            )
            with open(NO_MATCH_LOG, "a", encoding="utf-8") as nomatch_log:
                nomatch_log.write(f"{clarified_question}\n")
            continue

        gpt_answer = build_gpt_answer(clarified_question, filtered_chunks)
        if gpt_answer.lower().startswith("aucune réponse trouvée"):
            logger.info(
                f"Aucune réponse pertinente pour la question : {clarified_question}"
            )
            with open(NO_MATCH_LOG, "a", encoding="utf-8") as nomatch_log:
                nomatch_log.write(f"{clarified_question}\n")
            continue

        wb = load_workbook(xlsx_path)
        ws = wb.active
        excel_row = idx + 1  # +1 car pas de header
        ws.cell(row=excel_row, column=a_idx + 1, value=gpt_answer)
        wb.save(xlsx_path)
        answers_inserted += 1
        logger.info(
            f"Réponse écrite dans Excel à la ligne {excel_row}, colonne {a_idx + 1}"
        )

        # Adaptation pour sauvegarder les réponses dans le bon fichier
        # write_answers_to_excel(xlsx_path, df, meta["answer_col"], a_idx)
    logger.info(
        f"Résumé du traitement : {questions_analyzed} questions analysées, {answers_inserted} réponses insérées"
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python fillEmptyExcel.py <questions.xlsx> <meta.json>")
        logger.error("Usage: python fillEmptyExcel.py <questions.xlsx> <meta.json>")
    else:
        main(sys.argv[1], sys.argv[2])
