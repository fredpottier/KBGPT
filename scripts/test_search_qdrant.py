from pathlib import Path

from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

# Configuration
settings = get_settings()
COLLECTION_NAME = settings.qdrant_collection
ROOT = Path(__file__).parent.parent.resolve()
LOGS_DIR = ROOT / "logs"
logger = setup_logging(LOGS_DIR, "test_search_qdrant.log")
client = get_qdrant_client()
model = get_sentence_transformer()


def search_qdrant(question: str, solution: str, top_k: int = 5):
    emb = model.encode([f"passage: Q: {question}"], normalize_embeddings=True)[0].tolist()
    search_filter = {"must": [{"key": "main_solution", "match": {"value": solution}}]}
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=emb,
            limit=top_k,
            filter=search_filter,
        )
        logger.info("Recherche Qdrant pour %s : %d résultats", question, len(results))
        return results
    except Exception as exc:
        logger.warning("Erreur Qdrant pour %s: %s", question, exc)
        return []


if __name__ == "__main__":
    question = "How many environments are you recommend to implement your solution?"
    solution = "S/4HANA Private Cloud"
    results = search_qdrant(question, solution)
    for r in results:
        payload = r.payload or {}
        text = payload.get("text") if isinstance(payload, dict) else ""
        print(text or "")
