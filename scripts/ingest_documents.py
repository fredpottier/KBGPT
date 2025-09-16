import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pathlib import Path
import shutil
import uuid
from datetime import datetime, timezone

from langdetect import detect
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

from utils.parsers import parse_document

# === CONFIGURATION ===
COLLECTION_NAME = "sap_kb"
DOCS_IN = Path(r"C:\SAP_KB\docs_in")
DOCS_DONE = Path(r"C:\SAP_KB\docs_done")
CACHE_MODELS = Path(r"C:\SAP_KB\models")     # HF_HOME déjà pointé ici, on redonde pour clarté
MODEL_NAME = "intfloat/multilingual-e5-base" # ⚡️ meilleur FR↔EN que MiniLM

# === INITIALISATION ===
client = QdrantClient(host="localhost", port=6333)
model = SentenceTransformer(MODEL_NAME, cache_folder=str(CACHE_MODELS))

EMB_SIZE = model.get_sentence_embedding_dimension()

# === CRÉER/MAJ LA COLLECTION ===
if not client.collection_exists(COLLECTION_NAME):
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMB_SIZE, distance=Distance.COSINE),
    )
else:
    # vérifie et avertit si la taille ne correspond pas
    info = client.get_collection(COLLECTION_NAME)
    try:
        existing = info.vectors_count  # ping collection
    except Exception:
        pass
    # (Optionnel) on pourrait vérifier la dim en allant lire les params via HTTP API si nécessaire.

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

        # chunking sémantique simple par longueur
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

                points.append(PointStruct(
                    id=str(uuid.uuid4()),
                    vector=emb,
                    payload=meta
                ))
            except Exception as e:
                print(f"⚠️ Chunk ignoré (encode): {e}")

    if points:
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"📄 {file_path.name} → {len(points)} chunks")
    else:
        print(f"ℹ️ Aucun chunk indexé pour {file_path.name}")

    # Déplacement du fichier traité
    destination = DOCS_DONE / file_path.name
    try:
        shutil.move(str(file_path), str(destination))
        print(f"📦 Déplacé vers : {destination}")
    except Exception as e:
        print(f"⚠️ Impossible de déplacer {file_path} → {e}")

def main():
    DOCS_DONE.mkdir(parents=True, exist_ok=True)
    if not DOCS_IN.exists():
        print(f"❌ Dossier introuvable: {DOCS_IN}")
        return
    for file in DOCS_IN.iterdir():
        if file.is_file() and file.suffix.lower() in [".pdf", ".pptx", ".docx", ".xlsx"]:
            try:
                ingest_file(file)
            except Exception as e:
                print(f"❌ Erreur sur {file.name} : {e}")

if __name__ == "__main__":
    main()
