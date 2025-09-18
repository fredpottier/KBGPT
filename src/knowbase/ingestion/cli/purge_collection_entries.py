"""Delete entries inside a Qdrant collection matching a specific condition."""

from __future__ import annotations

import argparse
from typing import Sequence

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import get_settings


def build_parser(default_collection: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete points from a Qdrant collection using field filters"
    )
    parser.add_argument(
        "--collection",
        default=default_collection,
        help="Name of the collection to target (default: value from settings)",
    )
    parser.add_argument(
        "--field",
        default="type",
        help="Payload field used for the deletion filter (default: type)",
    )
    parser.add_argument(
        "--value",
        nargs="+",
        default=("rfp_qa",),
        metavar="VALUE",
        help="Value(s) that must match for deletion (default: rfp_qa)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    settings = get_settings()
    parser = build_parser(settings.qdrant_collection)
    args = parser.parse_args(list(argv) if argv is not None else None)

    client = get_qdrant_client()
    values = list(args.value)
    if len(values) == 1:
        match = MatchValue(value=values[0])
    else:
        match = MatchAny(any=values)
    delete_filter = Filter(must=[FieldCondition(key=args.field, match=match)])

    result = client.delete(collection_name=args.collection, points_selector=delete_filter)
    count = getattr(result, "operation_count", None)
    if count is None:
        print(f"Suppression demandée pour '{args.field}'={values}. Résultat : {result}")
    else:
        print(
            "✅ Suppression effectuée",
            f"Collection={args.collection}",
            f"Champ={args.field}",
            f"Valeurs={values}",
            f"Points supprimés={count}",
        )


if __name__ == "__main__":
    main()
