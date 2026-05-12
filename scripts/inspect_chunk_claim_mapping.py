#!/usr/bin/env python3
"""Inspect mapping chunk_id <-> claim_id in Neo4j."""
import os
import sys
sys.path.insert(0, "/app/src")
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
with driver.session() as s:
    # Look at chunk_3f069dc36422 - is there a node?
    print("=== Chunk node 'chunk_3f069dc36422' ===")
    rows = s.run("""
        MATCH (n) WHERE n.chunk_id = 'chunk_3f069dc36422' OR n.id = 'chunk_3f069dc36422'
        RETURN labels(n) AS labels, keys(n) AS keys LIMIT 3
    """).data()
    for r in rows:
        print(f"  labels={r['labels']}, keys={r['keys']}")

    # Look at relations chunk -> claim
    print("\n=== Relations from chunk to claim ===")
    rows = s.run("""
        MATCH (n) WHERE n.chunk_id = 'chunk_3f069dc36422' OR n.id = 'chunk_3f069dc36422'
        MATCH (n)-[r]-(m) RETURN type(r) AS rel, labels(m) AS m_labels, count(*) AS n
        LIMIT 10
    """).data()
    for r in rows:
        print(f"  -[:{r['rel']}]- {r['m_labels']} : {r['n']}")

    # Check claim_id pattern
    print("\n=== Sample claim_ids in 2021/821 ===")
    rows = s.run("""
        MATCH (c:Claim) WHERE c.doc_id = 'dualuse_reg_2021_821_original_65eef5dc'
        RETURN c.claim_id AS cid, keys(c) AS keys LIMIT 3
    """).data()
    for r in rows:
        print(f"  cid={r['cid']} keys={r['keys'][:15]}")

    # See if there's a chunk_id property on claims
    print("\n=== claims.chunk_id property exists? ===")
    rows = s.run("""
        MATCH (c:Claim)
        WHERE c.tenant_id = 'default' AND c.chunk_id IS NOT NULL
        RETURN count(c) AS n
    """).single()
    print(f"  claims with chunk_id: {rows['n']}")

    # And linked_chunks ?
    rows = s.run("""
        MATCH (c:Claim)-[r]-(ch)
        WHERE c.tenant_id = 'default' AND any(l IN labels(ch) WHERE l = 'Chunk' OR l = 'TypeAwareChunk')
        RETURN type(r) AS rel, labels(ch) AS chunk_labels, count(*) AS n
        LIMIT 5
    """).data()
    print(f"\n=== Claim -[*]- Chunk relations ===")
    for r in rows:
        print(f"  -[:{r['rel']}]- {r['chunk_labels']} : {r['n']}")

driver.close()
