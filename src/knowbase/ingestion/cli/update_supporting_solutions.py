"""CLI to append a supporting solution to selected Qdrant points."""

from __future__ import annotations

import argparse
from typing import Sequence

from qdrant_client.models import FieldCondition, Filter, MatchValue

from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings


def build_parser(default_collection: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add a supporting solution to points filtered by source_file_url"
    )
    parser.add_argument(
        "source_file_url",
        help="URL stored in the source_file_url payload field",
    )
    parser.add_argument(
        "solution_to_add",
        help="Solution string appended to supporting_solutions",
    )
    parser.add_argument(
        "--collection",
        default=default_collection,
        help="Collection name (default: value from settings)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximum number of points retrieved during the scroll",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    settings = get_settings()
    parser = build_parser(settings.qdrant_collection)
    args = parser.parse_args(list(argv) if argv is not None else None)

    client = get_qdrant_client()
    scroll_filter = Filter(
        must=[
            FieldCondition(
                key="source_file_url",
                match=MatchValue(value=args.source_file_url),
            )
        ]
    )
    points, _ = client.scroll(
        collection_name=args.collection,
        scroll_filter=scroll_filter,
        with_payload=True,
        with_vectors=False,
        limit=args.limit,
    )

    print(f"Chunks trouvés : {len(points)}")
    updated = 0
    for point in points:
        payload = point.payload or {}
        raw_supporting = payload.get("supporting_solutions", [])
        if isinstance(raw_supporting, list):
            supporting = list(raw_supporting)
        elif raw_supporting:
            supporting = [raw_supporting]
        else:
            supporting = []

        if args.solution_to_add not in supporting:
            supporting.append(args.solution_to_add)
            client.set_payload(
                collection_name=args.collection,
                payload={"supporting_solutions": supporting},
                points=[point.id],
            )
            updated += 1

    print(f"Chunks modifiés : {updated}")


if __name__ == "__main__":
    main()
