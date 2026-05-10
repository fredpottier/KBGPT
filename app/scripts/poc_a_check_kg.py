"""POC-A — vérifie l'état du Document Structure Graph existant dans Neo4j.

Compte les nodes SectionContext, DocItem, etc. par doc_id pour les 5 PDFs cibles.
"""
import sys, os
sys.path.insert(0, "/app/src")
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))

TARGET_DOCS = [
    "dualuse_reg_2021_821_original_65eef5dc",
    "cs25_amdt_22_8e69026c",
    "cs25_amdt_23_0869bab2",
    "cs25_amdt_28_32f1a9ac",
    "dualuse_del_2023_996_3616a044",
]

with driver.session() as s:
    print("=== Inventaire Document Structure Graph par doc cible ===\n")
    for doc_id in TARGET_DOCS:
        # Sections
        sec = s.run(
            "MATCH (s:SectionContext {tenant_id:'default'}) "
            "WHERE s.doc_version_id CONTAINS $d OR s.doc_id = $d "
            "RETURN count(s) AS n, collect(DISTINCT s.section_level) AS levels, "
            "min(s.section_level) AS lmin, max(s.section_level) AS lmax",
            d=doc_id,
        ).single()
        # DocItems
        di = s.run(
            "MATCH (i:DocItem {tenant_id:'default'}) "
            "WHERE i.doc_id = $d OR i.doc_version_id CONTAINS $d "
            "RETURN count(i) AS n, collect(DISTINCT i.type)[..10] AS types",
            d=doc_id,
        ).single()
        # Sample section
        sample = s.run(
            "MATCH (s:SectionContext) WHERE s.doc_id = $d OR s.doc_version_id CONTAINS $d "
            "RETURN s.section_path AS path, s.section_level AS lvl, s.title AS title "
            "ORDER BY s.section_level, s.section_path LIMIT 8",
            d=doc_id,
        ).data()
        print(f"--- {doc_id} ---")
        print(f"  SectionContext: {sec['n']} sections (levels {sec['lmin']}-{sec['lmax']})")
        print(f"  DocItem: {di['n']} items, types: {di['types']}")
        if sample:
            print(f"  Sample sections:")
            for ss in sample:
                t = (ss.get('title') or '')[:50]
                print(f"    L{ss['lvl']:>2} | {ss['path'][:60]:<60} | {t}")
        print()

    # Global counts
    g = s.run(
        "MATCH (s:SectionContext {tenant_id:'default'}) RETURN count(s) AS n_sections"
    ).single()
    g2 = s.run(
        "MATCH (i:DocItem {tenant_id:'default'}) RETURN count(i) AS n_items"
    ).single()
    g3 = s.run(
        "MATCH (d:DocumentVersion {tenant_id:'default'}) RETURN count(d) AS n_docs"
    ).single()
    print(f"=== TOTAL KG ===")
    print(f"  Sections: {g['n_sections']}")
    print(f"  DocItems: {g2['n_items']}")
    print(f"  DocumentVersions: {g3['n_docs']}")

    # Relations between sections
    rel = s.run(
        "MATCH (a:SectionContext)-[r]->(b:SectionContext) "
        "WHERE a.tenant_id='default' "
        "RETURN type(r) AS rtype, count(*) AS n LIMIT 10"
    ).data()
    print(f"  Relations Section-Section: {rel}")

driver.close()
