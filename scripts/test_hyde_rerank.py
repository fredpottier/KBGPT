#!/usr/bin/env python3
"""Test HyDE + cross-encoder reranker sur le cas 428/2009."""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.orchestrator import RuntimeOrchestrator

orch = RuntimeOrchestrator(tenant_id="default")
try:
    q = "Le règlement (CE) n° 428/2009 a-t-il été remplacé ? Si oui, quel impact sur les références utilisées dans nos contrats existants ?"

    print(f"Query : {q}\n")
    composed = orch.query(q, persona_hints={"persona": "explorer"}, synthesize=True)
    print(f"Mode    : {composed.mode.value}")
    print(f"Régime  : {composed.regime}")
    print(f"Trust   : {composed.confidence.score:.2f} ({composed.confidence.level.value})")
    print(f"\nShort answer:\n{composed.short_answer}\n")
    print(f"Top 5 evidence:")
    for e in composed.evidence[:5]:
        text = (e.text or "").replace("\n", " ")[:150]
        print(f"  - [{e.doc_id[:35]}] {text}")
finally:
    orch.close()
