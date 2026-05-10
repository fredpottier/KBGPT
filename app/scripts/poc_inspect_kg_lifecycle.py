"""Inspect Neo4j schema pour comprendre LIFECYCLE_RELATION."""
import os
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

queries = [
    ("Relations types globales",
     "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"),
    ("LIFECYCLE rels count",
     """MATCH ()-[r]->() WHERE type(r) CONTAINS 'LIFECYCLE' OR type(r) IN ['SUPERSEDES','EVOLVES_FROM','REAFFIRMS','REPLACES']
        RETURN type(r) AS rtype, count(r) AS n ORDER BY n DESC LIMIT 20"""),
    ("Sample SUPERSEDES",
     """MATCH (a)-[r:SUPERSEDES]->(b)
        RETURN labels(a)[0] AS la, a.id AS a_id, a.publication_date AS a_pub,
               labels(b)[0] AS lb, b.id AS b_id, b.publication_date AS b_pub
        LIMIT 5"""),
    ("Sample EVOLVES_FROM",
     """MATCH (a)-[r:EVOLVES_FROM]->(b)
        RETURN labels(a)[0] AS la, a.id AS a_id, a.publication_date AS a_pub,
               labels(b)[0] AS lb, b.id AS b_id, b.publication_date AS b_pub
        LIMIT 5"""),
    ("Document props sample",
     """MATCH (d:Document) WHERE d.id CONTAINS 'cs25_amdt' OR d.id CONTAINS 'dualuse_reg'
        RETURN d.id AS id, properties(d) AS props LIMIT 5"""),
    ("DocumentContext / lifecycle status",
     """MATCH (d:DocumentContext)
        RETURN d.id, d.lifecycle_status, d.publication_date, d.effective_date, d.deprecated_at LIMIT 10"""),
]

with driver.session(database="neo4j") as session:
    for label, q in queries:
        print(f"\n=== {label} ===")
        try:
            result = list(session.run(q))
            for rec in result[:10]:
                print(f"  {dict(rec)}")
            if not result:
                print("  (no results)")
        except Exception as exc:
            print(f"  ERROR: {exc}")

driver.close()
