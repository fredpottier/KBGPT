"""
CH-47.3 — Calibration Channel 2 NLI seuils par inference_strength.

Charge les 24 reasoning_steps réels produits par le prototype CH-47.1+47.2 (10q),
calcule entailment NLI mDeBERTa pour chaque step (premise = evidence quotes,
hypothesis = inference), et produit la distribution des scores par inference_strength.

Output :
  - Distribution des scores par strength
  - Histogramme console (texte)
  - Recommandation de seuils calibrés
  - data/audit/ch47_3_nli_calibration.json
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/app/src")

from knowbase.runtime_v3.nli_judge import _get_nli_model

PROTOTYPE = Path("/app/data/audit/ch47_prototype_10q_v2.json")
OUT = Path("/app/data/audit/ch47_3_nli_calibration_v2.json")


def build_premise(step: dict, facts_first: dict) -> str:
    """Concatène les evidence_quote des evidence_ids + relation_id."""
    parts = []
    atomic = {f["id"]: f for f in facts_first.get("atomic_facts", [])}
    relational = {r["id"]: r for r in facts_first.get("relational_facts", [])}

    for eid in step.get("evidence_ids", []) or []:
        f = atomic.get(eid)
        if f:
            q = ((f.get("source") or {}).get("quote") or "")[:500]
            if q:
                parts.append(q)

    rid = step.get("relation_id")
    if rid:
        r = relational.get(rid)
        if r:
            q = (r.get("evidence_quote") or "")[:500]
            if q and q not in parts:
                parts.append(q)

    return " ".join(parts)


def main():
    data = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    print(f"Loaded {len(data)} prototype questions")

    nli_model = _get_nli_model()
    print("NLI model loaded")

    # Collecte tous les steps
    pairs = []  # (qid, step_idx, premise, hypothesis, strength, type)
    for q in data:
        if "error" in q:
            continue
        ff = q.get("facts_first_v2") or {}
        steps = (q.get("reasoning_output") or {}).get("reasoning_steps") or []
        for step in steps:
            premise = build_premise(step, ff)
            hypothesis = step.get("inference") or ""
            if not premise or not hypothesis:
                continue
            pairs.append({
                "qid": q.get("id"),
                "category": q.get("category"),
                "step_no": step.get("step"),
                "step_type": step.get("type"),
                "strength": step.get("inference_strength") or "unknown",
                "premise": premise,
                "hypothesis": hypothesis,
                "evidence_ids": step.get("evidence_ids"),
                "relation_id": step.get("relation_id"),
            })

    print(f"Collected {len(pairs)} reasoning_steps to evaluate")

    # NLI batch
    pairs_for_nli = [(p["premise"], p["hypothesis"]) for p in pairs]
    print(f"Running NLI on {len(pairs_for_nli)} pairs...")
    scores_raw = nli_model.predict(pairs_for_nli, apply_softmax=True, show_progress_bar=True)
    # mDeBERTa-v3 xnli output : [ENTAILMENT, NEUTRAL, CONTRADICTION]
    # (cf nli_judge.py:173 comment + ligne 178)
    for i, p in enumerate(pairs):
        entail, neutral, contra = scores_raw[i]
        p["entailment"] = float(entail)
        p["neutral"] = float(neutral)
        p["contradiction"] = float(contra)

    # Distribution par strength
    by_strength = defaultdict(list)
    for p in pairs:
        by_strength[p["strength"]].append(p)

    print(f"\n=== DISTRIBUTION ENTAILMENT PAR INFERENCE_STRENGTH ===\n")
    print(f"{'strength':<12} {'n':>3} {'min':>6} {'p25':>6} {'p50':>6} {'p75':>6} {'p95':>6} {'max':>6} {'mean':>6}")
    for s in ["direct", "probable", "speculative", "unknown"]:
        items = by_strength.get(s, [])
        if not items:
            continue
        scores = sorted([x["entailment"] for x in items])
        n = len(scores)
        def pct(p): return scores[max(0, min(n - 1, int(n * p)))]
        print(f"{s:<12} {n:>3} {scores[0]:.3f} {pct(0.25):.3f} {pct(0.5):.3f} {pct(0.75):.3f} {pct(0.95):.3f} {scores[-1]:.3f} {sum(scores)/n:.3f}")

    print(f"\n=== HISTOGRAMME ENTAILMENT (granularité 0.1) ===\n")
    bins = [(round(b * 0.1, 1), round((b + 1) * 0.1, 1)) for b in range(10)]
    for s in ["direct", "probable", "speculative", "unknown"]:
        items = by_strength.get(s, [])
        if not items:
            continue
        print(f"\n{s} (n={len(items)}):")
        for b_low, b_high in bins:
            n_in_bin = sum(1 for x in items if b_low <= x["entailment"] < b_high)
            bar = "█" * n_in_bin
            print(f"  [{b_low:.1f}-{b_high:.1f}) {bar} {n_in_bin}")

    print(f"\n=== STEPS DÉTAILLÉS ===\n")
    print(f"{'qid':<6} {'step':<4} {'strength':<12} {'entail':>7} {'contra':>7} {'neutral':>8}  inference (preview)")
    for p in sorted(pairs, key=lambda x: (x["strength"], -x["entailment"])):
        print(f"{p['qid']:<6} {p['step_no']:<4} {p['strength']:<12} {p['entailment']:>7.3f} {p['contradiction']:>7.3f} {p['neutral']:>8.3f}  {p['hypothesis'][:90]}")

    print(f"\n=== RECOMMANDATION SEUILS ===\n")
    direct_scores = sorted([x["entailment"] for x in by_strength.get("direct", [])])
    probable_scores = sorted([x["entailment"] for x in by_strength.get("probable", [])])
    if direct_scores:
        # Seuil direct : on veut que ≥ 80% des direct passent → percentile 20
        p20_direct = direct_scores[max(0, int(len(direct_scores) * 0.20))]
        print(f"direct (n={len(direct_scores)}): p20 = {p20_direct:.3f}")
        print(f"  → seuil suggéré : {p20_direct - 0.05:.2f} (marge de sécurité, vise recall ~85%)")
        print(f"  → ADR initial proposait 0.85 ; à comparer.")
    if probable_scores:
        p20_prob = probable_scores[max(0, int(len(probable_scores) * 0.20))]
        print(f"probable (n={len(probable_scores)}): p20 = {p20_prob:.3f}")
        print(f"  → seuil suggéré : {p20_prob - 0.05:.2f}")
        print(f"  → ADR initial proposait 0.70")

    # Persist
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUT}")


if __name__ == "__main__":
    main()
