import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pathlib import Path
import shutil
import uuid
from datetime import datetime, timezone

from langdetect import detect
from qdrant_client.models import Distance, PointStruct
from utils.shared_clients import (
    ensure_qdrant_collection,
    get_qdrant_client,
    get_sentence_transformer,
)

from utils.parsers import parse_document

# === CONFIGURATION ===
COLLECTION_NAME = "sap_kb"
DOCS_IN = Path(r"C:\SAP_KB\docs_in")
DOCS_DONE = Path(r"C:\SAP_KB\docs_done")
CACHE_MODELS = Path(r"C:\SAP_KB\models")  # HF_HOME already points here; repeated for clarity
MODEL_NAME = "intfloat/multilingual-e5-base"  # better FR/EN coverage than MiniLM

# === INITIALISATION ===
qdrant_client = get_qdrant_client()
model = get_sentence_transformer(MODEL_NAME, cache_folder=str(CACHE_MODELS))
EMB_SIZE = model.get_sentence_embedding_dimension()
ensure_qdrant_collection(COLLECTION_NAME, EMB_SIZE, distance=Distance.COSINE)

def _chunk_text(text: str, max_chars: int = 500, overlap: int = 120):
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks

def ingest_file(file_path: Path):
    records = parse_document(file_path)  # [{text, meta}, ...] selon nouveau parsers
    points = []

    for rec in records:
        raw_text = (rec.get("text") or "").strip()
        if len(raw_text) < 20:
            continue

        # chunking semantique simple par longueur
        for chunk in _chunk_text(raw_text, max_chars=500, overlap=120):
            if len(chunk) < 20:
                continue
            try:
                # e5: passage prefix + normalisation
                emb = model.encode([f"passage: {chunk}"], normalize_embeddings=True)[0].tolist()

                # langue (best effort sur chunk)
                try:
                    lang = detect(chunk)
                except Exception:
                    lang = "unknown"

                meta = {
                    "source": file_path.name,
                    "text": chunk,
                    "language": lang,
                    "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                # merge meta parsers
                meta.update(rec.get("meta", {}))

                points.append(
                    PointStruct(id=str(uuid.uuid4()), vector=emb, payload=meta)
                )
            except Exception as e:
                print(f"[warn] Chunk ignore (encode): {e}")

    if points:
        qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"[info] {file_path.name} -> {len(points)} chunks")
    else:
        print(f"[info] Aucun chunk indexe pour {file_path.name}")

    # Deplacement du fichier traite
    destination = DOCS_DONE / file_path.name
    try:
        shutil.move(str(file_path), str(destination))
        print(f"[info] Deplace vers : {destination}")
    except Exception as e:
        print(f"[warn] Impossible de deplacer {file_path} -> {e}")

def main():
    DOCS_DONE.mkdir(parents=True, exist_ok=True)
    if not DOCS_IN.exists():
        print(f"[error] Dossier introuvable: {DOCS_IN}")
        return
    for file in DOCS_IN.iterdir():
        if file.is_file() and file.suffix.lower() in [".pdf", ".pptx", ".docx", ".xlsx"]:
            try:
                ingest_file(file)
            except Exception as e:
                print(f"[error] Erreur sur {file.name} : {e}")

if __name__ == "__main__":
    main()
