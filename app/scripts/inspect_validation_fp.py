"""Inspecte les false_positives non détectés dans la validation pack 50q."""
import json

data = json.load(open("/app/data/benchmark/calibration/multi_view_scorer_validation.json"))
fps_missed = [r for r in data["per_case"] if r["category"] == "false_positive" and not r["passed_dominant"]]
print(f"Restants false_positive non-detected ({len(fps_missed)}/10):")
for r in fps_missed:
    print(
        f"  {r['case_id']:7s} | dominant={r['actual_dominant']:9s} | "
        f"exact={r['actual_exact']:.3f} fuzzy={r['actual_fuzzy']:.3f} sem={r['actual_semantic']:.3f}"
    )

fuzzy_missed = [r for r in data["per_case"] if r["category"] == "fuzzy" and not r["passed_dominant"]]
print(f"\nFuzzy mis-classed ({len(fuzzy_missed)}/10):")
for r in fuzzy_missed:
    print(
        f"  {r['case_id']:8s} | got={r['actual_dominant']:9s} | "
        f"exact={r['actual_exact']:.3f} fuzzy={r['actual_fuzzy']:.3f} sem={r['actual_semantic']:.3f}"
    )
