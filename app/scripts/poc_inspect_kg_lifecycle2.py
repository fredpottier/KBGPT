"""Approfondir LIFECYCLE_RELATION."""
import os, json
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass"))
)

queries = [
    ("LIFECYCLE_RELATION détail",
     """MATCH (a)-[r:LIFECYCLE_RELATION]->(b)
        RETURN labels(a) AS la, properties(a) AS pa,
               type(r) AS rtype, properties(r) AS pr,
               labels(b) AS lb, properties(b) AS pb"""),
    ("DocumentContext labels + sample",
     """MATCH (d:DocumentContext)
        RETURN d LIMIT 3"""),
    ("Document nodes (any label) sample",
     """MATCH (n) WHERE 'Document' IN labels(n) OR 'DocumentContext' IN labels(n)
        RETURN labels(n) AS labels, n.id AS id, n.title AS title, n.publication_date AS pubd,
               n.lifecycle_status AS status, n.is_deprecated AS depr LIMIT 10"""),
    ("CS-25 amdt Documents",
     """MATCH (d) WHERE d.id CONTAINS 'cs25_amdt'
        RETURN labels(d) AS labels, d.id AS id, d.publication_date AS pubd,
               d.lifecycle_status AS status, d.is_deprecated AS depr,
               d.effective_date AS eff_date LIMIT 20"""),
    ("DualUse regs Documents",
     """MATCH (d) WHERE d.id CONTAINS 'dualuse_reg' OR d.id CONTAINS 'dualuse_del'
        RETURN labels(d) AS labels, d.id AS id, d.publication_date AS pubd,
               d.lifecycle_status AS status, d.is_deprecated AS depr,
               d.effective_date AS eff_date,
               d.applies_until AS until,
               d.successor_id AS successor LIMIT 20"""),
    ("Toute relation entre 2 documents",
     """MATCH (a)-[r]->(b) WHERE a.id IS NOT NULL AND b.id IS NOT NULL
        AND (a.id CONTAINS 'cs25' OR a.id CONTAINS 'dualuse')
        RETURN type(r) AS rtype, count(*) AS n ORDER BY n DESC LIMIT 15"""),
]

with driver.session(database="neo4j") as session:
    for label, q in queries:
        print(f"\n=== {label} ===")
        try:
            result = list(session.run(q))
            for rec in result[:15]:
                d = dict(rec)
                # Truncate long values
                for k, v in list(d.items()):
                    if isinstance(v, str) and len(v) > 200:
                        d[k] = v[:200] + "..."
                    elif isinstance(v, dict):
                        d[k] = {kk: (vv[:80] + "..." if isinstance(vv, str) and len(vv) > 80 else vv)
                                for kk, vv in v.items()}
                print(f"  {d}")
            if not result:
                print("  (no results)")
        except Exception as exc:
            print(f"  ERROR: {exc}")

driver.close()
