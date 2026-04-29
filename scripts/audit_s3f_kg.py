#!/usr/bin/env python3
"""S3.F-1 — Audit KG read-only : paires régulatoires non tranchées + état SUPERSEDES."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

audit = {"timestamp": datetime.utcnow().isoformat() + "Z", "tenant_id": "default"}

with driver.session() as s:
    # 1. Compteurs globaux par type V3.3
    print("=== 1. Distribution LOGICAL_RELATION par type (non-legacy) ===")
    rows = s.run("""
        MATCH ()-[r:LOGICAL_RELATION]->()
        WHERE coalesce(r.legacy, false) = false
        RETURN r.type AS type, count(r) AS n,
               sum(CASE WHEN coalesce(r.derived, false) THEN 1 ELSE 0 END) AS derived,
               avg(coalesce(r.confidence, 0.0)) AS avg_conf
        ORDER BY n DESC
    """).data()
    audit["logical_relation_distribution"] = rows
    for r in rows:
        print(f"  {r['type']:20s} : count={r['n']:5d} derived={r['derived']:4d} avg_conf={r['avg_conf']:.2f}")

    # 2. Compteurs legacy
    print("\n=== 2. Edges legacy V0 (CONTRADICTS/REFINES/QUALIFIES) ===")
    rows = s.run("""
        MATCH ()-[r]->()
        WHERE r.legacy = true
        RETURN type(r) AS type, count(r) AS n
        ORDER BY n DESC
    """).data()
    audit["legacy_edges"] = rows
    for r in rows:
        print(f"  {r['type']:20s} : count={r['n']:5d}")

    # 3. Claims totaux par doc régulatoire (focus succession)
    print("\n=== 3. Claims par doc régulatoire (succession candidates) ===")
    regulatory_docs = [
        "dualuse_reg_428_2009_original_372b7ac3",
        "dualuse_reg_2021_821_original_65eef5dc",
        "dualuse_del_2023_66_cdc2b691",
        "dualuse_del_2023_996_3616a044",
        "dualuse_del_2024_2025_908a03cf",
        "dualuse_del_2024_2547_cb08f84b",
        "cs25_amdt_22_8e69026c",
        "cs25_amdt_23_0869bab2",
        "cs25_amdt_24_86b11545",
        "cs25_amdt_25_a41bdc85",
        "cs25_amdt_26_6450b31e",
        "cs25_amdt_27_992260a7",
        "cs25_amdt_28_32f1a9ac",
    ]
    rows = s.run("""
        MATCH (c:Claim)
        WHERE c.tenant_id = $tid AND c.doc_id IN $docs
        RETURN c.doc_id AS doc, count(c) AS n
        ORDER BY n DESC
    """, tid="default", docs=regulatory_docs).data()
    audit["regulatory_doc_claims"] = rows
    for r in rows:
        print(f"  {r['doc'][:50]:50s} : {r['n']} claims")

    # 4. Paires cross-doc parmi ces docs régulatoires (sans LOGICAL_RELATION non-legacy)
    print("\n=== 4. Cross-doc pairs candidates (regulatory) ===")
    print("    Existing relations between these docs (non-legacy) :")
    rows = s.run("""
        MATCH (a:Claim)-[r:LOGICAL_RELATION]->(b:Claim)
        WHERE a.tenant_id = $tid AND a.doc_id IN $docs AND b.doc_id IN $docs
          AND a.doc_id <> b.doc_id
          AND coalesce(r.legacy, false) = false
        RETURN r.type AS type,
               a.doc_id AS doc_a, b.doc_id AS doc_b,
               count(r) AS n
        ORDER BY n DESC
        LIMIT 30
    """, tid="default", docs=regulatory_docs).data()
    audit["existing_cross_doc_relations"] = rows
    for r in rows:
        a = r['doc_a'][:30]
        b = r['doc_b'][:30]
        print(f"  {r['type']:15s} : {a} → {b} : {r['n']}")

    # 5. Paires C4_SCANNED / C12_SCANNED markers (idempotence cache)
    print("\n=== 5. Markers de scan ===")
    rows = s.run("""
        MATCH (c:Claim) WHERE c.tenant_id = $tid
        RETURN
          sum(CASE WHEN c.C4_SCANNED IS NOT NULL THEN 1 ELSE 0 END) AS c4_scanned,
          sum(CASE WHEN c.C6_SCANNED IS NOT NULL THEN 1 ELSE 0 END) AS c6_scanned,
          sum(CASE WHEN c.C12_SCANNED IS NOT NULL THEN 1 ELSE 0 END) AS c12_scanned,
          count(c) AS total
    """, tid="default").single()
    audit["scan_markers"] = dict(rows)
    print(f"  Total claims  : {rows['total']}")
    print(f"  C4_SCANNED   : {rows['c4_scanned']}")
    print(f"  C6_SCANNED   : {rows['c6_scanned']}")
    print(f"  C12_SCANNED  : {rows['c12_scanned']}")

    # 6. Sample : claims dans 2021/821 qui parlent de 428/2009 (smoking gun pour SUPERSEDES)
    print("\n=== 6. Smoking gun : claims dans 2021/821 qui mentionnent 428/2009 ===")
    rows = s.run("""
        MATCH (c:Claim)
        WHERE c.tenant_id = $tid AND c.doc_id = 'dualuse_reg_2021_821_original_65eef5dc'
          AND c.text CONTAINS '428/2009'
        RETURN c.claim_id AS claim_id, substring(c.text, 0, 200) AS text_excerpt
        LIMIT 10
    """, tid="default").data()
    audit["smoking_gun_2021_mentions_428"] = rows
    print(f"  → {len(rows)} claim(s) trouvés")
    for r in rows[:5]:
        print(f"    [{r['claim_id'][:30]}] {r['text_excerpt']}")

driver.close()

# Output JSON pour rapport machine-readable
out = Path("/data/forensics/audit_s3f_" + datetime.utcnow().strftime("%Y%m%dT%H%M%S") + ".json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
print(f"\n✅ Rapport JSON : {out}")
