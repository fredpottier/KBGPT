#!/usr/bin/env python3
"""Audit qualité des chaînes CHAINS_TO et des SF enrichis."""
from neo4j import GraphDatabase
import json
from collections import Counter

SUSPECT_KEYS = {
    "sap", "integration", "users", "customers", "sales", "items",
    "monitoring", "patches", "procurement", "business processes",
    "master data", "xml",
}

driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))

with driver.session() as s:
    # --- 1. Join keys suspects ---
    print("=" * 80)
    print("1. JOIN KEYS SUSPECTS (trop génériques)")
    print("=" * 80)
    result = s.run("""
        MATCH ()-[r:CHAINS_TO]->()
        RETURN r.join_key AS jk, count(r) AS cnt
        ORDER BY cnt DESC
    """)
    total = 0
    suspect_count = 0
    all_keys = []
    for rec in result:
        total += rec["cnt"]
        all_keys.append((rec["jk"], rec["cnt"]))
        if rec["jk"] in SUSPECT_KEYS:
            suspect_count += rec["cnt"]

    print("  Total edges: %d" % total)
    pct = suspect_count / total * 100 if total else 0
    print("  Edges via join_keys suspects: %d (%.1f%%)" % (suspect_count, pct))
    print()
    print("  Détail join keys suspects:")
    for jk, cnt in all_keys:
        if jk in SUSPECT_KEYS:
            print("    %-30s %3d edges" % (jk, cnt))

    # --- 2. Exemples chaînes transitives ---
    print()
    print("=" * 80)
    print("2. EXEMPLE CHAINE TRANSITIVE LONGUE (>= 4 maillons)")
    print("=" * 80)
    result = s.run("""
        MATCH path = (c1:Claim)-[:CHAINS_TO*3..5]->(cn:Claim)
        WITH path, length(path) AS len
        ORDER BY len DESC
        LIMIT 3
        WITH path, len,
             [i IN range(0, length(path)-1) |
                {step: i,
                 src_sf: nodes(path)[i].structured_form_json,
                 tgt_sf: nodes(path)[i+1].structured_form_json,
                 jk: relationships(path)[i].join_key}
             ] AS steps
        RETURN len, steps
    """)
    for rec in result:
        print("\n  --- Chaîne de longueur %d ---" % rec["len"])
        for step in rec["steps"]:
            src = json.loads(step["src_sf"]) if step["src_sf"] else {}
            tgt = json.loads(step["tgt_sf"]) if step["tgt_sf"] else {}
            print("    Step %d: [%s] --%s--> [%s]  ==(%s)==>  [%s] --%s--> [%s]" % (
                step["step"],
                src.get("subject", "?")[:25],
                src.get("predicate", "?"),
                src.get("object", "?")[:25],
                step["jk"],
                tgt.get("subject", "?")[:25],
                tgt.get("predicate", "?"),
                tgt.get("object", "?")[:25],
            ))

    # --- 3. Distribution prédicats dans les SF ---
    print()
    print("=" * 80)
    print("3. DISTRIBUTION DES PREDICATS (tous les SF)")
    print("=" * 80)
    result = s.run("""
        MATCH (c:Claim {tenant_id: "default"})
        WHERE c.structured_form_json IS NOT NULL
        RETURN c.structured_form_json AS sf
    """)
    pred_dist = Counter()
    total_sf = 0
    for rec in result:
        sf = json.loads(rec["sf"])
        pred_dist[sf.get("predicate", "?")] += 1
        total_sf += 1

    print("  Total SF: %d" % total_sf)
    for pred, cnt in pred_dist.most_common():
        print("    %-20s %5d (%.1f%%)" % (pred, cnt, cnt / total_sf * 100))

    # --- 4. Top subjects/objects trop fréquents (potentiel bruit) ---
    print()
    print("=" * 80)
    print("4. TOP 20 SUBJECTS (détection hubs)")
    print("=" * 80)
    result = s.run("""
        MATCH (c:Claim {tenant_id: "default"})
        WHERE c.structured_form_json IS NOT NULL
        RETURN c.structured_form_json AS sf
    """)
    subj_dist = Counter()
    obj_dist = Counter()
    for rec in result:
        sf = json.loads(rec["sf"])
        subj_dist[sf.get("subject", "?")] += 1
        obj_dist[sf.get("object", "?")] += 1

    for subj, cnt in subj_dist.most_common(20):
        print("    %-45s %4d" % (subj[:45], cnt))

    print()
    print("  TOP 20 OBJECTS:")
    for obj, cnt in obj_dist.most_common(20):
        print("    %-45s %4d" % (obj[:45], cnt))

    # --- 5. Edges impliquant PROVIDES/SUPPORTS + join_key générique ---
    print()
    print("=" * 80)
    print("5. CHAINES SUSPECTES: PROVIDES/SUPPORTS + join_key générique")
    print("=" * 80)
    result = s.run("""
        MATCH (c1:Claim)-[r:CHAINS_TO]->(c2:Claim)
        WHERE c1.structured_form_json IS NOT NULL AND c2.structured_form_json IS NOT NULL
        RETURN c1.structured_form_json AS src_sf,
               c2.structured_form_json AS tgt_sf,
               r.join_key AS jk
    """)
    suspect_chains = []
    for rec in result:
        src = json.loads(rec["src_sf"])
        tgt = json.loads(rec["tgt_sf"])
        if rec["jk"] in SUSPECT_KEYS:
            if src.get("predicate") in ("PROVIDES", "SUPPORTS") or tgt.get("predicate") in ("PROVIDES", "SUPPORTS"):
                suspect_chains.append((src, tgt, rec["jk"]))

    print("  Count: %d" % len(suspect_chains))
    for src, tgt, jk in suspect_chains[:10]:
        print("    [%s] --%s--> [%s]  ==(%s)==>  [%s] --%s--> [%s]" % (
            src.get("subject", "?")[:20],
            src.get("predicate", "?"),
            src.get("object", "?")[:20],
            jk,
            tgt.get("subject", "?")[:20],
            tgt.get("predicate", "?"),
            tgt.get("object", "?")[:20],
        ))

driver.close()
