#!/usr/bin/env python3
"""Test la synthèse mode-aware avec préambule structurel."""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.orchestrator import RuntimeOrchestrator

orch = RuntimeOrchestrator(tenant_id="default")
try:
    composed = orch.query(
        "Énumérez toutes les relations ÉQUIVALENTES définies dans le corpus",
        synthesize=True,
    )
    print(f"Mode    : {composed.mode.value if composed.mode else '?'}")
    print(f"Regime  : {composed.regime}")
    print(f"Trust   : {composed.confidence.score:.2f} ({composed.confidence.level.value})")
    print(f"\nShort answer:\n{composed.short_answer}")
    print(f"\nBusiness block type : {composed.business_block.get('type')}")
    print(f"N relations evidenced : {len(composed.evidence)}")
finally:
    orch.close()
