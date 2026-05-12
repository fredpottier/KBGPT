#!/usr/bin/env python3
"""Verify SUPERSEDES relations are now present after S3.F-4."""
import sys
sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase
import os

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")))

with driver.session() as s:
    print("=== Distribution V3.3 par type (post-S3.F-4) ===")
    rows = s.run("""
        MATCH ()-[r:LOGICAL_RELATION]->()
        WHERE coalesce(r.legacy, false) = false
        RETURN r.type AS type, count(r) AS n
        ORDER BY n DESC
    """).data()
    for r in rows:
        marker = "🆕" if r['type'] in ('SUPERSEDES', 'EVOLVES_FROM', 'REAFFIRMS', 'DISJOINT') else ""
        print(f"  {r['type']:20s} : {r['n']:5d}  {marker}")

    print("\n=== SUPERSEDES touchant 428/2009 ===")
    rows = s.run("""
        MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'SUPERSEDES'}]->(b:Claim)
        WHERE a.tenant_id = 'default'
          AND coalesce(r.legacy, false) = false
          AND (a.text CONTAINS '428/2009' OR b.text CONTAINS '428/2009')
        RETURN a.doc_id AS doc_a, substring(a.text, 0, 120) AS text_a,
               b.doc_id AS doc_b, substring(b.text, 0, 120) AS text_b,
               r.confidence AS conf
        LIMIT 10
    """).data()
    print(f"  → {len(rows)} relations trouvées")
    for r in rows:
        print(f"  [{r['conf']:.2f}] {r['doc_a'][:30]} → {r['doc_b'][:30]}")
        print(f"    A: {r['text_a']}")
        print(f"    B: {r['text_b']}\n")

driver.close()
