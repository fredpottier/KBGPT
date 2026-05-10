#!/usr/bin/env python3
"""
Bench micro latence ListComposer — comparaison modèles DeepInfra.

Le ListComposer fait du FORMATAGE pur (D-FF4) : il reçoit une liste structurée
d'items et produit la prose finale. Pas besoin de raisonnement profond → un
modèle 8B-12B devrait suffire et tourner 3-5× plus vite que Qwen2.5-72B.

Test 5 questions × 4 modèles :
  - Qwen/Qwen2.5-72B-Instruct           (baseline, ~30-40s)
  - meta-llama/Llama-3.3-70B-Instruct-Turbo
  - google/gemma-3-12b-it
  - meta-llama/Meta-Llama-3.1-8B-Instruct

Métrique : latence p50/p95 + verifier_passed_rate (qualité maintenue).

Usage (depuis container) :
  docker cp scripts/bench_composer_models.py knowbase-app:/app/scripts/
  docker exec knowbase-app python /app/scripts/bench_composer_models.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from copy import deepcopy
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if (PROJECT_ROOT / "src").exists():
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

OUTPUT_PATH = PROJECT_ROOT / "data" / "benchmark" / "calibration" / "bench_composer_models.json"


COMPOSER_CANDIDATES = [
    "Qwen/Qwen2.5-72B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "google/gemma-3-12b-it",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
]


def make_test_facts_first(idx: int) -> dict:
    """5 facts_first list samples basés sur le bench live."""
    samples = [
        {
            "subject": "EU 2021/821 export authorisation types",
            "items": [
                {"item_id": "I1", "label": "Individual export authorisation", "item_type": "category"},
                {"item_id": "I2", "label": "Global export authorisation", "item_type": "category"},
                {"item_id": "I3", "label": "Union general export authorisation", "item_type": "category"},
                {"item_id": "I4", "label": "Large project authorisation", "item_type": "category"},
            ],
            "language": "en",
        },
        {
            "subject": "exigences procédurales 2021/821",
            "items": [
                {"item_id": "I1", "label": "Délivrance par voie électronique sur formulaires standardisés", "item_type": "procedural_requirement"},
                {"item_id": "I2", "label": "Délivrance par l'autorité compétente de l'État membre", "item_type": "procedural_requirement"},
                {"item_id": "I3", "label": "Validité sur l'ensemble du territoire douanier de l'Union", "item_type": "procedural_requirement"},
            ],
            "language": "fr",
        },
        {
            "subject": "CS-25 take-off performance paragraphs",
            "items": [
                {"item_id": "I1", "label": "CS 25.107 — Take-off speeds", "item_type": "paragraph"},
                {"item_id": "I2", "label": "CS 25.109 — Accelerate-stop distance", "item_type": "paragraph"},
                {"item_id": "I3", "label": "CS 25.111 — Take-off path", "item_type": "paragraph"},
                {"item_id": "I4", "label": "CS 25.113 — Take-off distance", "item_type": "paragraph"},
                {"item_id": "I5", "label": "CS 25.115 — Net take-off flight path", "item_type": "paragraph"},
            ],
            "language": "en",
        },
        {
            "subject": "Annex I dual-use entry codes referenced",
            "items": [
                {"item_id": f"I{i+1}", "label": lbl, "item_type": "annex_i_entry"}
                for i, lbl in enumerate([
                    "0B005 — Plant for nuclear reactor fuel",
                    "0C004 — Graphite high purity",
                    "0D001 — Software Category 0",
                    "2D002 — NC device software",
                    "2D351 — Software for 2B351",
                    "3A003 — Spray cooling thermal management",
                    "3A102 — Thermal batteries for missiles",
                    "3D004 — Software for 3A003",
                    "3D006 — ECAD GAAFET",
                    "5D101 — Software for 5A101",
                    "6B008 — Pulse radar measurement",
                    "7A117 — Missile guidance sets",
                ])
            ],
            "language": "en",
        },
        {
            "subject": "Annex I exclusion notes",
            "items": [
                {"item_id": "I1", "label": "1A002 Note 1 — Composite structures civil aircraft", "item_type": "exclusion_note"},
                {"item_id": "I2", "label": "1A002 Note 2 — Semi-finished civilian items", "item_type": "exclusion_note"},
                {"item_id": "I3", "label": "1A005 Note 1 — Body armour personal use", "item_type": "exclusion_note"},
                {"item_id": "I4", "label": "1A006 Note — Equipment with operator", "item_type": "exclusion_note"},
                {"item_id": "I5", "label": "2B001 Note 1 — Gear machine tools", "item_type": "exclusion_note"},
                {"item_id": "I6", "label": "2B001 Note 2 — Other special purpose machine tools", "item_type": "exclusion_note"},
            ],
            "language": "en",
        },
    ]
    s = samples[idx % len(samples)]
    items_full = []
    for it in s["items"]:
        items_full.append({
            "item_id": it["item_id"],
            "label": it["label"],
            "item_type": it["item_type"],
            "source": {
                "doc_id": "test_doc", "claim_id": f"c_{it['item_id']}",
                "chunk_id": None, "page_no": None, "section_id": None,
                "quote": "synthetic source quote long enough to satisfy schema validation min 10 chars",
            },
            "confidence": 0.9,
        })
    return {
        "schema_version": "facts_first_v1",
        "primary_type": "list",
        "answerability": "answerable",
        "coverage_state": "complete",
        "language": s["language"],
        "extracted_at": "2026-05-06T00:00:00Z",
        "extraction_model": "test@mock",
        "list_specific": {
            "list_subject": s["subject"],
            "list_scope": None,
            "items": items_full,
            "enumeration_quality": {
                "expected_exhaustive": True, "coverage_state": "complete",
                "evidence_count": len(items_full), "deduped_count": len(items_full),
                "deduplication_notes": None,
            },
        },
    }


def run_one_model(model_name: str, n_samples: int = 5) -> dict:
    """Bench un modèle DeepInfra sur n samples ListComposer."""
    from knowbase.runtime_v3.llm_client import RuntimeLLMClient
    from knowbase.facts_first.list_composer import ListComposer
    from knowbase.facts_first.list_verifier import Channel1ListVerifier
    import os

    # Force le model_override sur DeepInfra
    os.environ["DEEPINFRA_RUNTIME_MODEL"] = model_name
    # Reset client pour prendre la nouvelle config
    from knowbase.runtime_v3.llm_client import reset_runtime_llm_client
    reset_runtime_llm_client()

    llm = RuntimeLLMClient(timeout=60.0)
    composer = ListComposer(llm=llm)
    verifier = Channel1ListVerifier()

    latencies = []
    n_verifier_passed = 0
    errors = 0
    for i in range(n_samples):
        ff = make_test_facts_first(i)
        t0 = time.time()
        try:
            res = composer.compose(ff)
            elapsed = time.time() - t0
            verifier_report = verifier.verify(
                question="test",
                facts_first=ff,
                composer_output=res.to_dict(),
            )
            if verifier_report.passed:
                n_verifier_passed += 1
            latencies.append(elapsed * 1000)
            logger.info("[%s] sample %d : %.1fs, verifier=%s, model_used=%s",
                        model_name, i, elapsed, verifier_report.passed, res.model)
        except Exception as exc:
            errors += 1
            logger.warning("[%s] sample %d failed: %s", model_name, i, exc)

    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p95 = latencies_sorted[max(0, int(len(latencies_sorted) * 0.95) - 1)]
        mean = sum(latencies) / len(latencies)
    else:
        p50 = p95 = mean = None

    return {
        "model": model_name,
        "n_samples": n_samples,
        "n_succeeded": len(latencies),
        "n_errors": errors,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_mean_ms": mean,
        "verifier_passed_rate": n_verifier_passed / max(1, len(latencies)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-samples", type=int, default=5)
    parser.add_argument("--models", nargs="*", default=COMPOSER_CANDIDATES)
    args = parser.parse_args()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for model in args.models:
        logger.info("=== Testing model: %s ===", model)
        try:
            r = run_one_model(model, args.n_samples)
            results.append(r)
        except Exception as exc:
            logger.error("Model %s failed entirely: %s", model, exc)
            results.append({"model": model, "error": str(exc)})

    OUTPUT_PATH.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Persisted %s", OUTPUT_PATH)

    print()
    print("=== COMPOSER MODEL LATENCY BENCH ===")
    print(f"{'model':<55} {'p50_ms':>10} {'p95_ms':>10} {'mean_ms':>10} {'verifier_pass':>14} {'errors':>7}")
    for r in results:
        if r.get("error"):
            print(f"{r['model']:<55} ERROR: {r['error'][:80]}")
            continue
        p50 = f"{r['latency_p50_ms']:.0f}" if r.get('latency_p50_ms') else "n/a"
        p95 = f"{r['latency_p95_ms']:.0f}" if r.get('latency_p95_ms') else "n/a"
        mean = f"{r['latency_mean_ms']:.0f}" if r.get('latency_mean_ms') else "n/a"
        vp = f"{r['verifier_passed_rate']:.2f}"
        print(f"{r['model']:<55} {p50:>10} {p95:>10} {mean:>10} {vp:>14} {r['n_errors']:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
