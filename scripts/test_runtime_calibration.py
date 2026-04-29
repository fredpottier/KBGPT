#!/usr/bin/env python3
"""R7 — Test E2E de la calibration runtime (bypass HTTP, appel direct)."""
import json
import sys

sys.path.insert(0, "/app/src")

PAYLOAD = {
    "persona": "explorer",
    "items": [
        {
            "question": "What contradictions exist on dual-use frequency changers?",
            "human_score": 0.95,
            "expected_mode": "CONFLICT_RISK",
            "expected_regime": "KG_LED",
        },
        {
            "question": "What was the rule for Halon 1301 in 2018?",
            "human_score": 0.45,
            "expected_mode": "SNAPSHOT_TEMPORAL",
            "expected_regime": "KG_LED",
        },
        {
            "question": "Which rules apply to lasers above 0.002 J per pulse?",
            "human_score": 0.85,
            "expected_mode": "APPLICABILITY_QUERY",
            "expected_regime": "KG_LED",
        },
        {
            "question": "List exceptions defined for ETOPS",
            "human_score": 0.55,
            "expected_mode": "EXPLORATION_RELATIONAL",
            "expected_regime": "KG_LED",
        },
        {
            "question": "What changed in dual-use export controls between 2009 and 2021?",
            "human_score": 0.75,
            "expected_mode": "DIFF_EVOLUTION",
            "expected_regime": "KG_LED",
        },
        {
            "question": "Summarize the dual-use export controls regulation",
            "human_score": 0.7,
            "expected_mode": "SYNTHESIS_SUMMARY",
            "expected_regime": "HYBRID",
        },
        {
            "question": "Quel est le code couleur du tapis rouge ?",
            "human_score": 0.05,
            "expected_mode": "LOOKUP_FACTUAL",
            "expected_regime": "RAG_LED",
        },
    ],
}


def main() -> int:
    """Appel direct du runtime pour calibration (bypass HTTP/auth)."""
    from knowbase.runtime.orchestrator import RuntimeOrchestrator
    from knowbase.api.routers.runtime_calibration import _pearson_correlation

    orch = RuntimeOrchestrator(tenant_id="default")
    items_results = []
    persona_hints = {"persona": PAYLOAD["persona"]}

    print(f"Running calibration on {len(PAYLOAD['items'])} items")
    try:
        for item in PAYLOAD["items"]:
            try:
                composed = orch.query(
                    question=item["question"],
                    persona_hints=persona_hints,
                    synthesize=False,
                )
                detected_mode = composed.mode.value if composed.mode else "UNKNOWN"
                detected_regime = composed.regime or "UNKNOWN"
                items_results.append({
                    "question": item["question"],
                    "human_score": item["human_score"],
                    "kg_trust": composed.confidence.score if composed.confidence else 0.0,
                    "trust_level": composed.confidence.level.value if composed.confidence else "FALLBACK",
                    "detected_mode": detected_mode,
                    "expected_mode": item.get("expected_mode"),
                    "mode_correct": detected_mode == item.get("expected_mode") if item.get("expected_mode") else None,
                    "detected_regime": detected_regime,
                    "expected_regime": item.get("expected_regime"),
                    "regime_correct": detected_regime == item.get("expected_regime") if item.get("expected_regime") else None,
                    "n_evidence": len(composed.evidence),
                })
            except Exception as e:
                print(f"  ERROR on item: {e}")
                items_results.append({
                    "question": item["question"],
                    "human_score": item["human_score"],
                    "kg_trust": 0.0,
                    "trust_level": "FALLBACK",
                    "detected_mode": "ERROR",
                    "detected_regime": "ERROR",
                    "n_evidence": 0,
                    "expected_mode": item.get("expected_mode"),
                    "mode_correct": False,
                    "expected_regime": item.get("expected_regime"),
                    "regime_correct": False,
                })
    finally:
        orch.close()

    # Aggregates
    pearson_r = _pearson_correlation(
        [r["human_score"] for r in items_results],
        [r["kg_trust"] for r in items_results],
    )
    n = len(items_results)
    n_high_wrong = sum(1 for r in items_results if r["kg_trust"] >= 0.85 and r["human_score"] < 0.5)
    n_low_correct = sum(1 for r in items_results if r["kg_trust"] < 0.65 and r["human_score"] >= 0.5)
    avg_trust = sum(r["kg_trust"] for r in items_results) / max(n, 1)
    avg_human = sum(r["human_score"] for r in items_results) / max(n, 1)

    n_with_mode = sum(1 for r in items_results if r["mode_correct"] is not None)
    mode_acc = sum(1 for r in items_results if r["mode_correct"]) / max(n_with_mode, 1) if n_with_mode else None

    n_with_regime = sum(1 for r in items_results if r["regime_correct"] is not None)
    regime_acc = sum(1 for r in items_results if r["regime_correct"]) / max(n_with_regime, 1) if n_with_regime else None

    distribution = {}
    for r in items_results:
        distribution[r["trust_level"]] = distribution.get(r["trust_level"], 0) + 1

    print("\n" + "=" * 70)
    print("CALIBRATION RESULTS")
    print("=" * 70)
    print(json.dumps({
        "pearson_r": round(pearson_r, 4),
        "n_items": n,
        "n_high_confidence_wrong": n_high_wrong,
        "n_low_confidence_correct": n_low_correct,
        "avg_kg_trust": round(avg_trust, 3),
        "avg_human_score": round(avg_human, 3),
        "mode_accuracy": round(mode_acc, 3) if mode_acc is not None else None,
        "regime_accuracy": round(regime_acc, 3) if regime_acc is not None else None,
        "trust_level_distribution": distribution,
    }, indent=2))

    print("\nPer-item details:")
    for it in items_results:
        delta = it["kg_trust"] - it["human_score"]
        mode_status = "OK" if it.get("mode_correct") else ("KO" if it.get("mode_correct") is False else "n/a")
        print(f"  - human={it['human_score']:.2f} trust={it['kg_trust']:.2f} delta={delta:+.2f} "
              f"mode={it['detected_mode']} ({mode_status}) | "
              f"{it['question'][:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
