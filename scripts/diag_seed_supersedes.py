#!/usr/bin/env python3
"""Diag : voir ce qu'OSMOSIS retrouve et si SUPERSEDES devrait déclencher escalation."""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.orchestrator import RuntimeOrchestrator
from knowbase.runtime.evidence_planner import RetrievalPlan, Regime
from knowbase.runtime.query_resolver import ResponseMode

orch = RuntimeOrchestrator(tenant_id="default")
try:
    q = "Le règlement (CE) n° 428/2009 a-t-il été remplacé ? Si oui, quel impact sur les références utilisées dans nos contrats existants ?"

    # Récupérer en RAG_LED ce qui sort, avec les claim_ids
    plan = RetrievalPlan(mode=ResponseMode.LOOKUP_FACTUAL, regime=Regime.RAG_LED, initial_regime=Regime.RAG_LED, qdrant_top_k=15)
    chunks = orch._retrieve_qdrant(q, plan)
    seed_ids = [c.get("claim_id") for c in chunks if c.get("claim_id")]
    print(f"=== Top {len(chunks)} retrieved (post-HyDE+reranker) ===")
    for i, c in enumerate(chunks[:15], 1):
        text = (c.get("text") or "").replace("\n", " ")[:130]
        print(f"  {i}. doc={c.get('doc_id', '?')[:30]:30s} | {text}")

    print(f"\n=== _kg_lookup_for_signals sur les top claim_ids ===")
    kg = orch._kg_lookup_for_signals(seed_ids[:10])
    print(f"  Conflicts        : {len(kg.get('conflicts', []))}")
    print(f"  Supersedes IN    : {len(kg.get('supersedes_in', []))}")
    print(f"  Supersedes OUT   : {len(kg.get('supersedes_out', []))}")
    for c in kg.get('supersedes_in', [])[:5]:
        print(f"    SUP IN  : claim={c['claim_id']} n_in={c['n_in']}")
    for c in kg.get('supersedes_out', [])[:5]:
        print(f"    SUP OUT : claim={c['claim_id']} n_out={c['n_out']}")
finally:
    orch.close()
