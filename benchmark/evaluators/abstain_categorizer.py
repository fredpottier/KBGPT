"""Abstain categorizer (CH-49 Phase 1, Cap5 Amendment 1).

Calcule la 3-catégorie abstain post-hoc en croisant la décision pipeline
avec le gold-set v5 (answerability annotation).

3 catégories ChatGPT (Amendment 1) :
  - aligned : decision=ANSWER (que l'answer soit correcte ou pas — autre métrique)
  - misaligned_abstain_correct : decision=ABSTAIN ET gold dit unanswerable / partial
  - misaligned_but_answerable : decision=ABSTAIN ET gold dit answerable
    → ALERTE qualité (threshold 5% production)

Usage offline :
    cat = categorize(decision="ABSTAIN", gold_answerability="answerable")
    # → AbstainCategory.MISALIGNED_BUT_ANSWERABLE

Usage agrégat :
    summary = summarize(per_sample_results)
    # → {"counts": {...}, "false_abstain_rate": 0.04, "alert": False}
"""
from __future__ import annotations

from typing import Any, Optional


# Reuse l'enum runtime pour cohérence des labels
try:
    from knowbase.runtime_v4_2.models import AbstainCategory
    LABELS = {
        "aligned": AbstainCategory.ALIGNED.value,
        "abstain_correct": AbstainCategory.MISALIGNED_ABSTAIN_CORRECT.value,
        "abstain_but_answerable": AbstainCategory.MISALIGNED_BUT_ANSWERABLE.value,
        "unknown": AbstainCategory.UNKNOWN.value,
    }
except Exception:  # noqa: BLE001
    # Fallback si module runtime_v4_2 absent (utilisable hors knowbase env)
    LABELS = {
        "aligned": "aligned",
        "abstain_correct": "misaligned_abstain_correct",
        "abstain_but_answerable": "misaligned_but_answerable",
        "unknown": "unknown",
    }


# Threshold alerte production (Amendment 1)
FALSE_ABSTAIN_THRESHOLD = 0.05


def categorize(
    decision: str,
    gold_answerability: Optional[str] = None,
) -> str:
    """Détermine la 3-catégorie abstain à partir de la décision + gold.

    Args:
        decision: "ANSWER" | "ABSTAIN" (du pipeline)
        gold_answerability: "answerable" | "partial" | "unanswerable" (gold v5)

    Returns:
        Label (string) parmi {aligned, misaligned_abstain_correct,
        misaligned_but_answerable, unknown}.
    """
    d = (decision or "").upper()
    a = (gold_answerability or "").lower()

    if d == "ANSWER":
        return LABELS["aligned"]

    if d == "ABSTAIN":
        if a in ("unanswerable", "partial"):
            return LABELS["abstain_correct"]
        if a == "answerable":
            return LABELS["abstain_but_answerable"]
        return LABELS["unknown"]

    return LABELS["unknown"]


def summarize(per_sample: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcul agrégat sur N samples.

    Args:
        per_sample: liste de dicts contenant au moins :
            - "decision" : ANSWER|ABSTAIN
            - "gold_answerability" : answerable|partial|unanswerable

    Returns:
        {
            "n": int,
            "counts": {aligned, misaligned_abstain_correct,
                       misaligned_but_answerable, unknown},
            "rates": idem en proportion,
            "false_abstain_rate": float (= misaligned_but_answerable / n),
            "alert": bool (true si false_abstain_rate > 0.05),
        }
    """
    counts = {label: 0 for label in LABELS.values()}
    for s in per_sample:
        cat = categorize(
            decision=s.get("decision", ""),
            gold_answerability=s.get("gold_answerability", ""),
        )
        counts[cat] = counts.get(cat, 0) + 1

    n = len(per_sample) or 1
    rates = {k: round(v / n, 4) for k, v in counts.items()}
    false_abstain_rate = rates.get(LABELS["abstain_but_answerable"], 0.0)

    return {
        "n": len(per_sample),
        "counts": counts,
        "rates": rates,
        "false_abstain_rate": false_abstain_rate,
        "alert": false_abstain_rate > FALSE_ABSTAIN_THRESHOLD,
        "threshold": FALSE_ABSTAIN_THRESHOLD,
    }
