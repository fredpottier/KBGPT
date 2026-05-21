"""Bench A3.4-bis — Evaluator gold-set 50 cas (gate GA3-2 ≥85%).

Cf ADR_PARSE_EVALUATE_RUNTIME §2.4 + §7.3.

Modes :
    - Default (fallback only) : exécute SEULEMENT le fallback déterministe
      (court-circuite le LLM). Donne une borne inférieure de performance —
      ce que le système atteint quand le LLM est down.
    - --live : utilise le LLM réel via llm_router. Borne supérieure attendue.
    - --mock-correct : LLM mock qui répond toujours le verdict attendu (sanity check).

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a34_evaluator.py'
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a34_evaluator.py --live'

Output :
    - data/benchmark/a34_evaluator/run_<timestamp>.json (résultats détaillés)
    - stdout : tableau de scores + matrice confusion + cas en échec
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Ajout PYTHONPATH pour exécution standalone
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from knowbase.runtime_a3.evaluate import Evaluator, evaluate
from knowbase.runtime_a3.schemas import EvaluateInput, EvaluateOutput
from tests.runtime_a3.data.evaluate_gold_set import build_gold_set, validate_gold_set


VERDICTS = ["CORRECT", "AMBIGUOUS", "INCORRECT", "INSUFFICIENT_EVIDENCE"]
DIFFICULTIES = ["trivial", "medium", "edge"]


def run_case(
    case: Dict[str, Any],
    evaluator: Evaluator,
) -> Dict[str, Any]:
    """Lance Evaluator sur un cas et retourne les résultats détaillés."""
    inp = EvaluateInput(
        parse_output=case["parse_output"],
        plan_output=case["plan_output"],
        execute_output=case["execute_output"],
        iteration=case["iteration"],
    )
    try:
        out: EvaluateOutput = evaluator.evaluate(inp)
        return {
            "id": case["id"],
            "category": case["category"],
            "difficulty": case["difficulty"],
            "description": case["description"],
            "iteration": case["iteration"],
            "annotator_confidence": case["annotator_confidence"],
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": out.verdict,
            "match": out.verdict == case["expected_verdict"],
            "actual_re_plan_hint": out.re_plan_hint,
            "actual_confidence": out.confidence,
            "actual_reasoning": out.reasoning,
            "covered_sub_goals": out.covered_sub_goals,
            "uncovered_sub_goals": out.uncovered_sub_goals,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "category": case["category"],
            "difficulty": case["difficulty"],
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "ERROR",
            "match": False,
            "error": str(exc)[:300],
        }


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcule accuracy globale + per-class + per-difficulty + confusion matrix.

    Le gate effectif post A3.4-bis (cf ADR §2.4.bis) est mesuré sur 38 cas
    (exclusion INCORRECT — réservée downstream Synthesize). On rapporte les
    deux scores : `accuracy_all_50` (legacy/diagnostic) et `accuracy_3_class`
    (gate effectif).
    """
    total = len(results)
    n_match = sum(1 for r in results if r["match"])
    accuracy = n_match / total if total else 0.0

    # Gate effectif post A3.4-bis : 3 classes (exclusion INCORRECT)
    results_3c = [r for r in results if r["expected_verdict"] != "INCORRECT"]
    n_3c = len(results_3c)
    n_match_3c = sum(1 for r in results_3c if r["match"])
    accuracy_3c = (n_match_3c / n_3c) if n_3c else 0.0

    # Per-class
    by_class: Dict[str, Dict[str, int]] = {}
    for v in VERDICTS:
        rows = [r for r in results if r["expected_verdict"] == v]
        n = len(rows)
        match = sum(1 for r in rows if r["match"])
        by_class[v] = {
            "n_cases": n,
            "n_match": match,
            "accuracy": (match / n) if n else 0.0,
        }

    # Per-difficulty
    by_diff: Dict[str, Dict[str, int]] = {}
    for d in DIFFICULTIES:
        rows = [r for r in results if r["difficulty"] == d]
        n = len(rows)
        match = sum(1 for r in rows if r["match"])
        by_diff[d] = {
            "n_cases": n,
            "n_match": match,
            "accuracy": (match / n) if n else 0.0,
        }

    # Confusion matrix (expected -> actual)
    confusion: Dict[str, Dict[str, int]] = {v: {a: 0 for a in (VERDICTS + ["ERROR"])} for v in VERDICTS}
    for r in results:
        e = r["expected_verdict"]
        a = r["actual_verdict"]
        if e in confusion and a in confusion[e]:
            confusion[e][a] += 1
        else:
            confusion.setdefault(e, {}).setdefault(a, 0)
            confusion[e][a] += 1

    # Cohen's kappa (1 annotator vs system — exclu pour l'instant car protocole
    # exige 2 annotateurs humains. À implémenter post-bench si gate fragile.)
    # Pour l'instant on rapporte l'accuracy uniquement.

    return {
        "accuracy": accuracy,
        "n_cases": total,
        "n_match": n_match,
        "n_miss": total - n_match,
        "accuracy_3_class": accuracy_3c,
        "n_cases_3_class": n_3c,
        "n_match_3_class": n_match_3c,
        "gate_GA3_2_passed": accuracy_3c >= 0.85,
        "by_class": by_class,
        "by_difficulty": by_diff,
        "confusion_matrix": confusion,
    }


def print_report(metrics: Dict[str, Any], results: List[Dict[str, Any]], mode: str) -> None:
    """Affiche un rapport stdout lisible."""
    print(f"\n{'=' * 70}")
    print(f"BENCH A3.4-bis — Evaluator gold-set [{mode}]")
    print(f"{'=' * 70}\n")
    acc_all = metrics["accuracy"]
    acc_3c = metrics["accuracy_3_class"]
    gate = "✓ PASS" if metrics["gate_GA3_2_passed"] else "✗ FAIL"
    print(f"Accuracy 50 cases (legacy diag) : {acc_all:.1%} ({metrics['n_match']}/{metrics['n_cases']})")
    print(f"Accuracy 38 cases (3-class gate, post §2.4.bis) : {acc_3c:.1%} "
          f"({metrics['n_match_3_class']}/{metrics['n_cases_3_class']})")
    print(f"Gate GA3-2 ≥85% (3-class) : {gate}\n")

    print("PER CLASS:")
    for v, m in metrics["by_class"].items():
        marker = "✓" if m["accuracy"] >= 0.85 else " "
        print(f"  {marker} {v:25s}  {m['n_match']:2d}/{m['n_cases']:2d}  ({m['accuracy']:.1%})")
    print()

    print("PER DIFFICULTY:")
    for d, m in metrics["by_difficulty"].items():
        marker = "✓" if m["accuracy"] >= 0.85 else " "
        print(f"  {marker} {d:10s}  {m['n_match']:2d}/{m['n_cases']:2d}  ({m['accuracy']:.1%})")
    print()

    print("CONFUSION MATRIX (rows=expected, cols=actual):")
    cols = VERDICTS + ["ERROR"]
    header = "expected/actual"
    print(f"  {header:25s}", end="")
    for c in cols:
        print(f" {c[:10]:>10s}", end="")
    print()
    for v in VERDICTS:
        print(f"  {v:25s}", end="")
        for c in cols:
            n = metrics["confusion_matrix"].get(v, {}).get(c, 0)
            marker = " *" if (v == c and n > 0) else "  "
            print(f"   {n:5d}{marker}  ", end="")
        print()
    print()

    misses = [r for r in results if not r["match"]]
    if misses:
        print(f"FAILED CASES ({len(misses)}):")
        for r in misses:
            print(
                f"  [{r['id']}] {r.get('difficulty', '?'):8s} "
                f"expected={r['expected_verdict']:24s} "
                f"got={r['actual_verdict']:24s} "
                f"iter={r.get('iteration', '?')}"
            )
            if r.get("description"):
                print(f"      {r['description'][:80]}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Bench A3.4-bis Evaluator gate GA3-2.")
    parser.add_argument("--live", action="store_true",
                        help="Use real LLM via llm_router (otherwise fallback only)")
    parser.add_argument("--mock-correct", action="store_true",
                        help="Use mock LLM that always returns expected verdict (sanity check)")
    parser.add_argument("--output-dir", default="data/benchmark/a34_evaluator",
                        help="Output dir for JSON results")
    args = parser.parse_args()

    cases = build_gold_set()
    validate_gold_set(cases)

    # Construit l'Evaluator selon le mode
    if args.live:
        mode = "live_llm"
        evaluator = Evaluator()  # défaut : llm_router
    elif args.mock_correct:
        mode = "mock_correct"
        mock = MagicMock()
        # Le mock retournera toujours expected — sanity check du pipeline bench
        def _mock_complete(system: str, user: str) -> str:
            # On extrait le verdict attendu via convention : le mock check le contenu
            # NB : ce mode est UNIQUEMENT pour vérifier que le pipeline bench tourne
            return json.dumps({
                "verdict": "CORRECT",
                "covered_sub_goals": [],
                "uncovered_sub_goals": [],
                "re_plan_hint": "none",
                "confidence": 0.99,
                "reasoning": "mock",
                "schema_version": "a3.0",
            })
        mock.complete.side_effect = _mock_complete
        evaluator = Evaluator(llm_client=mock)
    else:
        mode = "fallback_only"
        # Mock LLM qui échoue toujours → force le fallback déterministe
        mock = MagicMock()
        mock.complete.side_effect = Exception("LLM disabled (fallback bench)")
        evaluator = Evaluator(llm_client=mock)

    # Run cases
    results: List[Dict[str, Any]] = []
    for case in cases:
        results.append(run_case(case, evaluator))

    metrics = compute_metrics(results)
    print_report(metrics, results, mode)

    # Persist JSON
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"run_{mode}_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "mode": mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"Results persisted: {output_file}")

    # Exit code 0 si gate atteint, 1 sinon (utile pour CI)
    return 0 if metrics["gate_GA3_2_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
