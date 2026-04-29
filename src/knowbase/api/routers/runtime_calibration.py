"""
R7 — Endpoint admin pour calibration kg_trust.

Permet d'évaluer la corrélation entre kg_trust et un eval humain (golden set).

Workflow :
1. POST /api/admin/runtime/calibration/run : lance le runtime sur N questions
   et retourne le jobId. Le golden set est passé avec une note humaine pour
   chaque question (score 0-1) ou un boolean correct/incorrect.
2. GET /api/admin/runtime/calibration/result : retourne le rapport :
   - Pearson correlation kg_trust vs human eval
   - Distribution des trust levels (AUTHORITATIVE / RELIABLE / PARTIAL / FALLBACK)
   - Taux de hallucination (réponse confiante mais human=incorrect)
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from knowbase.api.dependencies import get_tenant_id
from knowbase.runtime.orchestrator import RuntimeOrchestrator

logger = logging.getLogger("[OSMOSE] runtime_calibration")

router = APIRouter(prefix="/admin/runtime", tags=["admin", "runtime", "calibration"])


# ============================================================================
# Schemas
# ============================================================================

class CalibrationItem(BaseModel):
    question: str
    human_score: float = Field(..., ge=0.0, le=1.0, description="Score humain 0-1")
    expected_mode: Optional[str] = None
    expected_regime: Optional[str] = None
    notes: Optional[str] = None


class CalibrationRunRequest(BaseModel):
    items: list[CalibrationItem]
    persona: Optional[str] = "explorer"


class CalibrationItemResult(BaseModel):
    question: str
    human_score: float
    kg_trust: float
    trust_level: str
    detected_mode: str
    expected_mode: Optional[str] = None
    mode_correct: Optional[bool] = None
    detected_regime: str
    expected_regime: Optional[str] = None
    regime_correct: Optional[bool] = None
    n_evidence: int


class CalibrationResultResponse(BaseModel):
    pearson_r: float
    """Pearson correlation kg_trust vs human_score."""

    n_items: int
    n_high_confidence_wrong: int
    """Réponses confiantes (kg_trust >= 0.85) mais human_score < 0.5 — risque hallucination."""

    n_low_confidence_correct: int
    """Réponses peu confiantes (kg_trust < 0.65) mais human_score >= 0.5 — sous-confiance."""

    avg_kg_trust: float
    avg_human_score: float

    mode_accuracy: Optional[float] = None
    regime_accuracy: Optional[float] = None

    trust_level_distribution: dict[str, int]

    items: list[CalibrationItemResult]


# ============================================================================
# Endpoint
# ============================================================================

@router.post("/calibration/run", response_model=CalibrationResultResponse)
async def run_calibration(
    req: CalibrationRunRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> CalibrationResultResponse:
    """
    Run le runtime sur le golden set et calcule la corrélation Pearson.

    Le caller fournit une human_score (0-1) pour chaque question. On lance
    le runtime, on récupère kg_trust, et on compute Pearson.
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="No calibration items provided")

    persona_hints = {"persona": req.persona} if req.persona else {}
    orch = RuntimeOrchestrator(tenant_id=tenant_id)

    item_results: list[CalibrationItemResult] = []
    try:
        for item in req.items:
            try:
                composed = orch.query(
                    question=item.question,
                    persona_hints=persona_hints,
                    synthesize=False,  # skip LLM pour speed
                )
                detected_mode = composed.mode.value if composed.mode else "UNKNOWN"
                detected_regime = composed.regime or "UNKNOWN"

                item_results.append(CalibrationItemResult(
                    question=item.question,
                    human_score=item.human_score,
                    kg_trust=composed.confidence.score if composed.confidence else 0.0,
                    trust_level=composed.confidence.level.value if composed.confidence else "FALLBACK",
                    detected_mode=detected_mode,
                    expected_mode=item.expected_mode,
                    mode_correct=(detected_mode == item.expected_mode) if item.expected_mode else None,
                    detected_regime=detected_regime,
                    expected_regime=item.expected_regime,
                    regime_correct=(detected_regime == item.expected_regime) if item.expected_regime else None,
                    n_evidence=len(composed.evidence),
                ))
            except Exception as e:
                logger.exception(f"[Calibration] item failed: {item.question[:80]}: {e}")
                item_results.append(CalibrationItemResult(
                    question=item.question,
                    human_score=item.human_score,
                    kg_trust=0.0,
                    trust_level="FALLBACK",
                    detected_mode="ERROR",
                    detected_regime="ERROR",
                    n_evidence=0,
                ))
    finally:
        orch.close()

    # Compute aggregate metrics
    pearson_r = _pearson_correlation(
        [r.human_score for r in item_results],
        [r.kg_trust for r in item_results],
    )

    n_items = len(item_results)
    n_high_conf_wrong = sum(1 for r in item_results if r.kg_trust >= 0.85 and r.human_score < 0.5)
    n_low_conf_correct = sum(1 for r in item_results if r.kg_trust < 0.65 and r.human_score >= 0.5)

    avg_kg_trust = sum(r.kg_trust for r in item_results) / max(n_items, 1)
    avg_human = sum(r.human_score for r in item_results) / max(n_items, 1)

    mode_acc = None
    n_with_expected_mode = sum(1 for r in item_results if r.mode_correct is not None)
    if n_with_expected_mode > 0:
        mode_acc = sum(1 for r in item_results if r.mode_correct) / n_with_expected_mode

    regime_acc = None
    n_with_expected_regime = sum(1 for r in item_results if r.regime_correct is not None)
    if n_with_expected_regime > 0:
        regime_acc = sum(1 for r in item_results if r.regime_correct) / n_with_expected_regime

    distribution: dict[str, int] = {}
    for r in item_results:
        distribution[r.trust_level] = distribution.get(r.trust_level, 0) + 1

    return CalibrationResultResponse(
        pearson_r=round(pearson_r, 4),
        n_items=n_items,
        n_high_confidence_wrong=n_high_conf_wrong,
        n_low_confidence_correct=n_low_conf_correct,
        avg_kg_trust=round(avg_kg_trust, 3),
        avg_human_score=round(avg_human, 3),
        mode_accuracy=round(mode_acc, 3) if mode_acc is not None else None,
        regime_accuracy=round(regime_acc, 3) if regime_acc is not None else None,
        trust_level_distribution=distribution,
        items=item_results,
    )


# ============================================================================
# Pearson helper
# ============================================================================

def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation classique. Retourne 0.0 si dégénéré (variance nulle)."""
    n = len(xs)
    if n < 2:
        return 0.0
    if len(ys) != n:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sum_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    sum_x2 = sum((xs[i] - mean_x) ** 2 for i in range(n))
    sum_y2 = sum((ys[i] - mean_y) ** 2 for i in range(n))
    denom = math.sqrt(sum_x2 * sum_y2)
    if denom == 0.0:
        return 0.0
    return sum_xy / denom


__all__ = ["router"]
