from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from import_logging import setup_logging
from pathlib import Path

# Configuration
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "sap_kb"
ROOT = Path(__file__).parent.parent.resolve()
LOGS_DIR = ROOT / "logs"
logger = setup_logging(LOGS_DIR, "test_search_qdrant.log")
client = QdrantClient(host="localhost", port=6333)
model = SentenceTransformer(MODEL_NAME)


def search_qdrant(question, solution, top_k=5):
    emb = model.encode([f"passage: Q: {question}"], normalize_embeddings=True)[
        0
    ].tolist()
    search_filter = {"must": [{"key": "main_solution", "match": {"value": solution}}]}
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=emb,
            limit=top_k,
            filter=search_filter,
        )
        logger.info(f"Recherche Qdrant pour '{question}' : {len(results)} résultats")
        return results
    except Exception as e:
        logger.warning(f"Erreur Qdrant pour '{question}': {e}")
        return []


if __name__ == "__main__":
    question = "How many environments are you recommend to implement your solution?"
    solution = "S/4HANA Private Cloud"
    results = search_qdrant(question, solution)
    for r in results:
        payload = r.payload or {}
        text = payload.get("text") if isinstance(payload, dict) else ""
        print(text or "")
