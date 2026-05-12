#!/usr/bin/env python3
"""S3.F-5 — Dump des 21 SUPERSEDES pour analyse / annotation."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=("neo4j", os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")),
)

with driver.session() as s:
    rows = s.run("""
        MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'SUPERSEDES'}]->(b:Claim)
        WHERE a.tenant_id = 'default'
          AND coalesce(r.legacy, false) = false
          AND coalesce(r.derived, false) = false
        RETURN
          a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc, a.publication_date AS a_pub,
          b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc, b.publication_date AS b_pub,
          r.confidence AS confidence, r.strength AS strength, r.reasoning AS reasoning,
          r.derivation_path AS path
        ORDER BY a.doc_id, b.doc_id, r.confidence DESC
    """).data()

print(f"Total SUPERSEDES (non-legacy, non-derived) : {len(rows)}\n")
for i, r in enumerate(rows, 1):
    print(f"=== {i}. CONF={r['confidence']:.2f} ({r['strength']}) ===")
    print(f"  A: [{r['a_doc'][:35]}] (pub: {r['a_pub']})")
    print(f"     {r['a_text'][:300]}")
    print(f"  B: [{r['b_doc'][:35]}] (pub: {r['b_pub']})")
    print(f"     {r['b_text'][:300]}")
    print(f"  Reasoning: {(r['reasoning'] or '')[:400]}")
    print(f"  Derivation: {r['path']}")
    print()

driver.close()

# Save full data for later
out = Path("/data/forensics/supersedes_for_review.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
print(f"Saved : {out}")
