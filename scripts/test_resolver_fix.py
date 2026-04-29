#!/usr/bin/env python3
"""Quick smoke test du fix EXPLORATION_RELATIONAL."""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.query_resolver import QueryResolver

resolver = QueryResolver()
test_queries = [
    "Énumérez toutes les relations ÉQUIVALENTES définies dans le corpus",
    "Listez tous les SUBSET dans le corpus",
    "List all the EXCEPTIONS defined in the corpus",
    "Quelles sont les CONFLICT entre les documents ?",
    "What rules apply to lasers above 0.002 J?",
    "Summarize the dual-use regulation",
]

for q in test_queries:
    r = resolver.resolve(q)
    print(f"  mode={r.mode.value:30s} conf={r.confidence:.2f} | {q[:70]}")
