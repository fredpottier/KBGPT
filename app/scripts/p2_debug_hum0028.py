"""P2 Option ε — Debug HUM_0028 : voir top-5 réel envoyé à Synthesize.

Lance UNE seule question via Orchestrator avec V6_DEBUG_SYNTHESIZE_TOP5=1
pour comprendre pourquoi Synthesize choisit CGSADM au lieu de CG5Z.

Usage:
    docker exec -e V6_HYBRID_RETRIEVAL=rrf \\
                -e V6_CROSS_ENCODER_RERANK=1 \\
                -e V6_PARSE_LLM_DEEPSEEK=1 \\
                -e V6_DEBUG_SYNTHESIZE_TOP5=1 \\
        knowbase-app sh -c 'cd /app && python -u scripts/p2_debug_hum0028.py'
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Logger en INFO pour capturer les [SYNTHESIZE_TOP5] et [CROSS_ENCODER]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("p2_debug")


def main():
    from knowbase.runtime_a3.orchestrator import Orchestrator

    question = "Quelle transaction est utilisee pour le WWI Monitor dans SAP EHS ?"
    expected_answer = "CG5Z (transaction du WWI Monitor)"
    expected_claim_id = "claim_5bebb77ee026"

    print("=" * 70)
    print("P2 Option ε — Debug HUM_0028")
    print("=" * 70)
    print(f"\nQuestion: {question}")
    print(f"Expected: {expected_answer}")
    print(f"Expected claim_id: {expected_claim_id}")
    print()

    orch = Orchestrator()
    result = orch.run(
        question=question,
        tenant_id="default",
        as_of_date=datetime.now(timezone.utc),
        response_mode="structured",
    )

    print("\n" + "=" * 70)
    print("RÉPONSE PIPELINE")
    print("=" * 70)
    synth = result.synthesize_output
    print(f"Mode: {synth.mode}")
    print(f"Answer: {synth.answer_text}")
    print(f"N cited claims: {len(synth.cited_claims)}")
    print("\nCited claims:")
    for cc in synth.cited_claims:
        print(f"  - {cc.claim_id}")
        print(f"    verbatim: {cc.claim_verbatim[:200]}")
    print()
    print(f"Verdict Evaluate: {result.evaluate_output.verdict if result.evaluate_output else 'N/A'}")


if __name__ == "__main__":
    main()
