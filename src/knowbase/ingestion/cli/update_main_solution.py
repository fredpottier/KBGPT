"""CLI helpers to update the ``main_solution`` field inside Qdrant."""

from __future__ import annotations

import argparse
from typing import Sequence

from qdrant_client.models import FieldCondition, Filter, MatchValue

from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings

DEFAULT_OLD_VALUE = "RISE with SAP Cloud ERP Private"
DEFAULT_NEW_VALUE = "RISE with SAP S/4HANA Cloud, private edition"


def build_parser(default_collection: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace values of the main_solution field in Qdrant"
    )
    parser.add_argument(
        "--old-value",
        default=DEFAULT_OLD_VALUE,
        help=(
            "Value to replace (default: 'RISE with SAP Cloud ERP Private')"
        ),
    )
    parser.add_argument(
        "--new-value",
        default=DEFAULT_NEW_VALUE,
        help=(
            "New value assigned to matching points (default: 'RISE with SAP S/4HANA Cloud, private edition')"
        ),
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
        must=[FieldCondition(key="main_solution", match=MatchValue(value=args.old_value))]
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
        if payload.get("main_solution") == args.old_value:
            client.set_payload(
                collection_name=args.collection,
                payload={"main_solution": args.new_value},
                points=[point.id],
            )
            updated += 1

    print(f"Chunks modifiés : {updated}")


if __name__ == "__main__":
    main()
