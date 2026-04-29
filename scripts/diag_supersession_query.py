#!/usr/bin/env python3
"""Diag : pourquoi la question 428/2009 supersession est ratée ?"""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.orchestrator import RuntimeOrchestrator
from knowbase.runtime.evidence_planner import RetrievalPlan, Regime
from knowbase.runtime.query_resolver import ResponseMode

orch = RuntimeOrchestrator(tenant_id="default")
try:
    q = "Le règlement (CE) n° 428/2009 a-t-il été remplacé ? Si oui, quel impact sur les références utilisées dans nos contrats existants ?"

    # 1. Que dit le LLM classifier ?
    resolved = orch.query_resolver.resolve(q)
    print(f"=== Mode classification ===")
    print(f"  Mode    : {resolved.mode.value}")
    print(f"  Conf    : {resolved.confidence:.2f}")
    print(f"  Intent  : {resolved.intent}")
    print(f"  Entities: {resolved.entities}")

    # 2. Qdrant top 15
    plan = RetrievalPlan(mode=resolved.mode, regime=Regime.KG_LED, initial_regime=Regime.KG_LED, qdrant_top_k=15)
    chunks = orch._retrieve_qdrant(q, plan)
    print(f"\n=== Qdrant top 15 (sur la query exacte) ===")
    for i, c in enumerate(chunks[:15], 1):
        text = (c.get("text") or "").replace("\n", " ")[:130]
        print(f"  {i}. score={c.get('score', 0):.3f} doc={c.get('doc_id', '?')[:35]} | {text}")

    # 3. Y a-t-il une SUPERSEDES dans le KG ?
    print(f"\n=== Recherche LOGICAL_RELATION SUPERSEDES dans le KG ===")
    with orch.neo4j_driver.session() as s:
        rows = s.run("""
            MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'SUPERSEDES'}]->(b:Claim)
            WHERE a.tenant_id = 'default' AND coalesce(r.legacy, false) = false
            RETURN count(r) AS n
        """).single()
        print(f"  Total SUPERSEDES (non-legacy) : {rows['n']}")

        # Specifically about 428/2009
        rows = s.run("""
            MATCH (a:Claim)-[r:LOGICAL_RELATION]-(b:Claim)
            WHERE a.tenant_id = 'default' AND coalesce(r.legacy, false) = false
              AND (a.text CONTAINS '428/2009' OR b.text CONTAINS '428/2009'
                   OR a.text CONTAINS '2021/821' OR b.text CONTAINS '2021/821')
            RETURN r.type AS type, count(r) AS n ORDER BY n DESC
        """).data()
        print(f"  Relations touchant 428/2009 OR 2021/821 :")
        for row in rows:
            print(f"    - {row['type']}: {row['n']}")
finally:
    orch.close()
