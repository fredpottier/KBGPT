#!/usr/bin/env python3
"""S3.F-5 cleanup : supprime les SUPERSEDES créées par S3.F-4 (anchor sub-optimal).

Identifie via la propriété derivation_path qui contient 'S3F-4 succession:'.
"""
import os
import sys
sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=("neo4j", os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")),
)

with driver.session() as s:
    # Compter avant
    before = s.run("""
        MATCH ()-[r:LOGICAL_RELATION]->()
        WHERE coalesce(r.legacy, false) = false
          AND r.derivation_path STARTS WITH 'S3F-4 succession'
        RETURN r.type AS type, count(r) AS n
        ORDER BY n DESC
    """).data()
    total = sum(r["n"] for r in before)
    print(f"Avant cleanup : {total} relations S3F-4")
    for r in before:
        print(f"  {r['type']}: {r['n']}")

    # Cleanup
    deleted = s.run("""
        MATCH ()-[r:LOGICAL_RELATION]->()
        WHERE coalesce(r.legacy, false) = false
          AND r.derivation_path STARTS WITH 'S3F-4 succession'
        DELETE r
        RETURN count(r) AS n
    """).single()
    print(f"\n✓ Deleted : {deleted['n']} relations")

driver.close()
