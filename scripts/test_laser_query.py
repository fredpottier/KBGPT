#!/usr/bin/env python3
"""Diag : pourquoi la query laser ne trouve pas les chunks 6A005 ?"""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.orchestrator import RuntimeOrchestrator

orch = RuntimeOrchestrator(tenant_id="default")
try:
    q = "Quelles sont les règles d'export contrôlé applicables à un laser embarqué dont l'énergie de sortie est de 0.003 J par impulsion à 100 picosecondes ?"

    # Étape 1 : que retourne Qdrant directement ?
    from knowbase.runtime.evidence_planner import RetrievalPlan, Regime
    from knowbase.runtime.query_resolver import ResponseMode
    plan = RetrievalPlan(mode=ResponseMode.APPLICABILITY_QUERY, regime=Regime.KG_LED, initial_regime=Regime.KG_LED, qdrant_top_k=10)
    rag_chunks = orch._retrieve_qdrant(q, plan)
    print(f"=== Qdrant (top 10 sémantique) ===")
    for c in rag_chunks[:10]:
        print(f"  - score={c.get('score', 0):.3f} doc={c.get('doc_id')[:40]} txt={(c.get('text') or '')[:120]}")

    # Étape 2 : query EN — différence multilingue ?
    q_en = "Which export control rules apply to an embedded laser with output energy of 0.003 J per pulse at 100 picoseconds?"
    print(f"\n=== Qdrant query EN ===")
    rag_chunks_en = orch._retrieve_qdrant(q_en, plan)
    for c in rag_chunks_en[:10]:
        print(f"  - score={c.get('score', 0):.3f} doc={c.get('doc_id')[:40]} txt={(c.get('text') or '')[:120]}")

    # Étape 3 : full pipeline result
    print(f"\n=== Full pipeline (FR) ===")
    composed = orch.query(q, synthesize=False)
    print(f"  Mode/Régime: {composed.mode.value}/{composed.regime}")
    print(f"  N evidence: {len(composed.evidence)}")
    print(f"  Top 3 evidence:")
    for e in composed.evidence[:3]:
        print(f"    - [{e.doc_id}] {e.text[:140]}")
finally:
    orch.close()
