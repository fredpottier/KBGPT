"""Command line utility to delete a Qdrant collection."""

from __future__ import annotations

import argparse
from typing import Sequence

from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings


def build_parser(default_collection: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete a Qdrant collection")
    parser.add_argument(
        "--collection",
        default=default_collection,
        help="Name of the collection to delete (default: value from settings)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    settings = get_settings()
    parser = build_parser(settings.qdrant_collection)
    args = parser.parse_args(list(argv) if argv is not None else None)

    collection = args.collection
    client = get_qdrant_client()
    if client.collection_exists(collection):
        client.delete_collection(collection)
        print(f"✅ Collection '{collection}' supprimée.")
    else:
        print(f"ℹ️ Collection '{collection}' introuvable.")


if __name__ == "__main__":
    main()
