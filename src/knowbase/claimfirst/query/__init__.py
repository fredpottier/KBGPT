# src/knowbase/claimfirst/query/__init__.py
"""
Module de requêtes avec scoping (INV-8).

Query-time scoping obligatoire pour réponses épistémiquement honnêtes.
"""

from knowbase.claimfirst.query.scoped_query import (
    ScopedQueryEngine,
    QueryResponse,
    QueryContext,
)

__all__ = [
    "ScopedQueryEngine",
    "QueryResponse",
    "QueryContext",
]
