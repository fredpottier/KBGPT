"""V5 Verifier thresholds par shape (CH-52.8.4 / S7.4).

ADR V1.5 §3f : `verifier_thresholds.yaml` versionné. Méthode calibration :
Youden's J statistic sur validation set OSMOSIS. Recalibration trimestrielle.
Split train/test strict (holdout 30% intouché).

Cas particulier `shape=unanswerable` : sémantique inversée (score bas = abstention valide).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Default thresholds V1.5 — à recalibrer post Phase 1 bench
# Valeurs initiales : balance favorable au support (0.5 ≈ neutral, 0.7 = high confidence)
DEFAULT_THRESHOLDS_BY_SHAPE = {
    "factual": {"support": 0.65, "contradict": 0.25, "inverted": False},
    "factual_simple": {"support": 0.65, "contradict": 0.25, "inverted": False},
    "listing": {"support": 0.55, "contradict": 0.20, "inverted": False},
    "multi_hop": {"support": 0.55, "contradict": 0.20, "inverted": False},
    "lifecycle": {"support": 0.60, "contradict": 0.25, "inverted": False},
    "causal": {"support": 0.55, "contradict": 0.20, "inverted": False},
    "comparison": {"support": 0.60, "contradict": 0.25, "inverted": False},
    "quantitative": {"support": 0.70, "contradict": 0.25, "inverted": False},
    "contextual": {"support": 0.55, "contradict": 0.20, "inverted": False},
    # Cas inverted : pour `unanswerable`/`false_premise`, on s'attend à une
    # ABSTENTION → un score "supported" haut est suspect (réponse hallucinée),
    # un score bas = abstention valide.
    "unanswerable": {"support": 0.55, "contradict": 0.25, "inverted": True},
    "false_premise": {"support": 0.55, "contradict": 0.25, "inverted": True},
    "negation": {"support": 0.60, "contradict": 0.25, "inverted": False},
}

# Default fallback (multi_hop = profil moyen)
DEFAULT_FALLBACK = {"support": 0.55, "contradict": 0.20, "inverted": False}


@dataclass(frozen=True)
class ShapeThreshold:
    support: float
    contradict: float
    inverted: bool = False

    def validate(self) -> None:
        if not (0.0 <= self.contradict <= self.support <= 1.0):
            raise ValueError(
                f"Invalid thresholds: contradict={self.contradict}, "
                f"support={self.support} — must satisfy 0 ≤ contradict ≤ support ≤ 1"
            )


def get_threshold(answer_shape: Optional[str]) -> ShapeThreshold:
    """Retourne le seuil pour un shape (fallback default)."""
    if not answer_shape:
        d = DEFAULT_FALLBACK
    else:
        d = DEFAULT_THRESHOLDS_BY_SHAPE.get(answer_shape.lower(), DEFAULT_FALLBACK)
    t = ShapeThreshold(
        support=d["support"],
        contradict=d["contradict"],
        inverted=d.get("inverted", False),
    )
    t.validate()
    return t


def youden_j_calibrate(
    scores_positive: list[float],
    scores_negative: list[float],
) -> tuple[float, float]:
    """Calibration Youden's J : threshold qui maximise (TPR - FPR).

    Args:
        scores_positive : scores des vrais positifs (claims SUPPORTED réels)
        scores_negative : scores des vrais négatifs (claims CONTRADICTED réels)

    Returns:
        (best_threshold, best_J_value)
    """
    if not scores_positive or not scores_negative:
        raise ValueError("Need both positive and negative samples for Youden's J")
    # Test seuils espacés de 0.01
    all_scores = sorted(set(round(s, 2) for s in (scores_positive + scores_negative)))
    best_threshold = 0.5
    best_j = -1.0
    for t in all_scores:
        tpr = sum(1 for s in scores_positive if s >= t) / len(scores_positive)
        fpr = sum(1 for s in scores_negative if s >= t) / len(scores_negative)
        j = tpr - fpr
        if j > best_j:
            best_j = j
            best_threshold = t
    return best_threshold, best_j
