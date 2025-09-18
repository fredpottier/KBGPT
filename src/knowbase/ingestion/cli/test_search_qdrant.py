"""Utility CLI to perform ad-hoc searches against Qdrant."""

from __future__ import annotations

import argparse
from typing import Sequence

from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings


def build_parser(default_collection: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search documents stored in Qdrant")
    parser.add_argument(
        "--question",
        default="How many environments are you recommend to implement your solution?",
        help="Question to embed and search for",
    )
    parser.add_argument(
        "--solution",
        default="S/4HANA Private Cloud",
        help="Value matched against the filter field",
    )
    parser.add_argument(
        "--filter-field",
        default="main_solution",
        help="Payload field used in the filter (default: main_solution)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to retrieve",
    )
    parser.add_argument(
        "--collection",
        default=default_collection,
        help="Collection name to query (default: value from settings)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    settings = get_settings()
    parser = build_parser(settings.qdrant_collection)
    args = parser.parse_args(list(argv) if argv is not None else None)

    logger = setup_logging(settings.logs_dir, "test_search_qdrant.log", "test_search_qdrant")
    client = get_qdrant_client()
    model = get_sentence_transformer()

    query = f"passage: Q: {args.question}"
    embedding = model.encode([query], normalize_embeddings=True)[0].tolist()
    search_filter = {
        "must": [
            {
                "key": args.filter_field,
                "match": {"value": args.solution},
            }
        ]
    }

    try:
        results = client.search(
            collection_name=args.collection,
            query_vector=embedding,
            limit=args.top_k,
            filter=search_filter,
        )
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning("Erreur Qdrant pour %s: %s", args.question, exc)
        print("Aucune réponse récupérée.")
        return

    logger.info("Recherche Qdrant pour %s : %d resultats", args.question, len(results))
    if not results:
        print("Aucun résultat trouvé.")
        return

    for idx, result in enumerate(results, start=1):
        payload = getattr(result, "payload", None) or {}
        text = payload.get("text") if isinstance(payload, dict) else ""
        source = payload.get("source_file_url") if isinstance(payload, dict) else ""
        score = getattr(result, "score", "-")
        print(f"#{idx} | Score={score} | Source={source}\n{text or ''}\n")


if __name__ == "__main__":
    main()
