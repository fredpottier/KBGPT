"""Diagnostic POC : pourquoi temporal_op a déclenché seulement 2/5 ?"""
import json
import os
from pathlib import Path
from neo4j import GraphDatabase

from knowbase.runtime_v4_poc.operators import TemporalActiveVersionOperator

# Charger le bench POC pour identifier les questions temporal et leurs layers
POC_RESULTS = json.loads(Path("/app/data/audit/ch49_poc_bench_30q.json").read_text(encoding="utf-8"))
rows = POC_RESULTS["rows"]
GOLD = json.loads(Path("/app/benchmark/questions/gold_set_v5.json").read_text(encoding="utf-8"))
gv5_by_sid = {q["source_id"]: q for q in GOLD}

temporal_rows = [r for r in rows if r["primary_type"] == "temporal"]
print(f"=== Bench POC : 5 questions temporal ===\n")
print(f"{'oid':25s} | layer                  | poc_struct | v41_struct")
print("-" * 75)
for r in temporal_rows:
    print(f"{r['oid']:25s} | {r['poc_layer']:22s} | {r['poc_struct']:.3f}      | {r['v41_struct_v5']:.3f}")

# Identifier les misses (layer0 au lieu de layer1_temporal_active)
misses = [r for r in temporal_rows if r["poc_layer"] != "layer1_temporal_active"]
print(f"\n=== {len(misses)} MISSES (operator pas déclenché) ===\n")

# Re-tester l'intent detection pour ces 3
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")),
)
op = TemporalActiveVersionOperator(neo4j_driver=driver)

for r in misses:
    g = gv5_by_sid[r["oid"]]
    q = g["question"]
    print(f"--- {r['oid']} ---")
    print(f"Q: {q[:160]}")
    print(f"GOLD answer: {(g['ground_truth'].get('answer') or '')[:200]}")
    intent = op.detect_intent(q)
    print(f"Intent detection: {json.dumps(intent, indent=2, ensure_ascii=False)}")
    if intent.get("is_temporal_active"):
        # Cypher
        kw = intent.get("subject_keywords") or []
        cands = op.query_versions(kw)
        print(f"Cypher hits: {len(cands)} (keywords={kw})")
        for c in cands[:3]:
            print(f"  - {c.get('doc_id')} ({c.get('publication_date')}) subject={c.get('primary_subject')}")
    print()

driver.close()
