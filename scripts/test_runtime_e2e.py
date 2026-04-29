#!/usr/bin/env python3
"""
R1+R2 — Test E2E du runtime V1.1 sur 3-4 questions types.

Lance le pipeline complet sans passer par l'API HTTP (donc bypass auth).
Affiche le résultat structuré pour validation.

Usage :
    docker exec knowbase-app python /tmp/test_runtime_e2e.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

from knowbase.runtime.orchestrator import RuntimeOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# Questions types couvrant 4 modes V1.1
TEST_QUERIES = [
    {
        "question": "What is the impact energy required for a 51mm diameter ball test?",
        "expected_mode": "LOOKUP_FACTUAL",
        "expected_regime": "RAG_LED",
    },
    {
        "question": "Which rules apply to lasers with output energy above 0.002 J per pulse?",
        "expected_mode": "APPLICABILITY_QUERY",
        "expected_regime": "KG_LED",
    },
    {
        "question": "What contradictions exist in the corpus on ETOPS deviations?",
        "expected_mode": "CONFLICT_RISK",
        "expected_regime": "KG_LED",
    },
    {
        "question": "What was the rule for Halon 1301 in 2018?",
        "expected_mode": "SNAPSHOT_TEMPORAL",
        "expected_regime": "KG_LED",
    },
    {
        "question": "What changed in dual-use export controls between 2009 and 2021?",
        "expected_mode": "DIFF_EVOLUTION",
        "expected_regime": "KG_LED",
    },
    {
        "question": "List all the exceptions defined in the corpus for ETOPS",
        "expected_mode": "EXPLORATION_RELATIONAL",
        "expected_regime": "KG_LED",
    },
]


def run_test(orch: RuntimeOrchestrator, query: dict, idx: int) -> dict:
    """Lance une query, retourne le résumé structuré."""
    logger.info("=" * 70)
    logger.info(f"Test {idx}: {query['question']}")
    logger.info("=" * 70)
    logger.info(f"  Expected mode: {query['expected_mode']} | regime: {query['expected_regime']}")

    composed = orch.query(query["question"], synthesize=True)

    logger.info(f"\n  ✓ Mode detected     : {composed.mode.value if composed.mode else 'UNKNOWN'}")
    logger.info(f"  ✓ Regime           : {composed.regime}")
    logger.info(f"  ✓ Trust score      : {composed.confidence.score:.2f} ({composed.confidence.level.value})")
    logger.info(f"  ✓ N chunks evidenced: {len(composed.evidence)}")
    logger.info(f"  ✓ Escalation       : {composed.debug_info.get('escalation_triggered', False)}")
    logger.info(f"\n  Short answer:")
    for line in composed.short_answer.splitlines()[:5]:
        logger.info(f"    {line}")

    if composed.conditions:
        logger.info(f"\n  Conditions:")
        for c in composed.conditions[:3]:
            logger.info(f"    - {c}")

    logger.info(f"\n  Top 3 evidence:")
    for e in composed.evidence[:3]:
        logger.info(f"    - [{e.doc_id}] {e.text[:120]}")

    if composed.business_block:
        logger.info(f"\n  Business block ({composed.business_block.get('type')}):")
        bb_str = json.dumps(composed.business_block, default=str, ensure_ascii=False)[:500]
        logger.info(f"    {bb_str}")

    return {
        "question": query["question"],
        "expected_mode": query["expected_mode"],
        "actual_mode": composed.mode.value if composed.mode else None,
        "mode_correct": composed.mode.value == query["expected_mode"] if composed.mode else False,
        "expected_regime": query["expected_regime"],
        "actual_regime": composed.regime,
        "regime_correct": composed.regime == query["expected_regime"],
        "trust_score": composed.confidence.score,
        "trust_level": composed.confidence.level.value,
        "n_evidence": len(composed.evidence),
        "escalation": composed.debug_info.get("escalation_triggered", False),
        "short_answer": composed.short_answer,
    }


def main() -> int:
    logger.info("R1+R2 — Test E2E du runtime V1.1")

    orch = RuntimeOrchestrator(tenant_id="default")
    results = []
    try:
        for i, q in enumerate(TEST_QUERIES, 1):
            try:
                result = run_test(orch, q, i)
                results.append(result)
            except Exception as e:
                logger.exception(f"Test {i} failed: {e}")
                results.append({"question": q["question"], "error": str(e)})
    finally:
        orch.close()

    # Synthèse
    logger.info("\n" + "=" * 70)
    logger.info("Synthèse")
    logger.info("=" * 70)
    mode_correct = sum(1 for r in results if r.get("mode_correct"))
    regime_correct = sum(1 for r in results if r.get("regime_correct"))
    avg_trust = sum(r.get("trust_score", 0) for r in results) / max(len(results), 1)
    logger.info(f"  Mode detection : {mode_correct}/{len(results)} correct")
    logger.info(f"  Regime mapping : {regime_correct}/{len(results)} correct")
    logger.info(f"  Avg trust      : {avg_trust:.2f}")

    # Output JSON pour rapport
    out = Path("/data/forensics/test_runtime_e2e.json") if Path("/data").exists() else Path("data/forensics/test_runtime_e2e.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"\n✅ Results : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
