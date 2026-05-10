"""
OSMOSIS V4.1 — Analyzer Cascade (CH-47.4).

Cascade DeBERTa S2 → Analyzer LLM pour rattraper les misclassifications de
l'Analyzer LLM (notamment hypothetical/conditional/multi_hop classés "factual").

Le DeBERTa S2 est un XLM-RoBERTa fine-tuné sur 14 767 questions multi-domaines
(96% datasets externes Mintaka/SQuAD2/HotpotQA/FalseQA + 4% manuel 10 domaines),
**domain-agnostic par construction**.

Logique cascade CONSERVATIVE (validée 2026-05-08 avec Fred) :
  - Si Analyzer LLM dit `factual` (worst case = sous-classement)
  - ET DeBERTa top-1 dans {causal, comparison, temporal} avec confidence ≥ 0.85
  - ET DeBERTa top-1 ≠ factual
  → promouvoir primary_type au DeBERTa top-1
  Sinon → garder Analyzer LLM (Analyzer LLM reste autoritaire en cas de doute)

Garde-fous (cf feedback memory `feedback_no_benchmark_overfit_focus_production.md`) :
  - Pas tied au corpus régulatoire actuel (DeBERTa entraîné sur multi-domaines externes)
  - Cascade conservatrice (seuil 0.85, seulement si LLM=factual)
  - Monitoring `cascade_promotion_rate` pour détecter dérive future
  - Pas de re-train sur corpus client (le classifier reste universel)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Path du modèle XLM-RoBERTa fine-tuné (Sprint S2.A.1.b.1.3)
DEBERTA_MODEL_PATH = os.getenv(
    "ANALYZER_CASCADE_MODEL_PATH",
    "/app/data/router/model",
)

# Configuration cascade
CASCADE_CONFIDENCE_THRESHOLD = float(os.getenv("ANALYZER_CASCADE_THRESHOLD", "0.85"))
# Types vers lesquels la cascade peut PROMOUVOIR (mapping vers reasoning_mode pipeline)
PROMOTABLE_TYPES = {"causal", "comparison", "temporal"}
# Type d'origine LLM qu'on accepte de re-classer (worst-case sous-classement)
DEMOTED_LLM_TYPE = "factual"


@dataclass
class CascadeResult:
    """Résultat de la cascade."""
    final_type: str
    promoted: bool
    llm_type: str
    deberta_top1: Optional[str] = None
    deberta_confidence: Optional[float] = None
    deberta_top2: Optional[str] = None
    deberta_top2_confidence: Optional[float] = None
    promotion_reason: Optional[str] = None
    latency_ms: int = 0


@lru_cache(maxsize=1)
def _load_model():
    """Charge le modèle XLM-RoBERTa fine-tuné (singleton)."""
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch

    path = Path(DEBERTA_MODEL_PATH)
    if not path.exists():
        raise FileNotFoundError(f"DeBERTa cascade model not found: {path}")

    tokenizer = AutoTokenizer.from_pretrained(str(path))
    model = AutoModelForSequenceClassification.from_pretrained(str(path))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    id2label = model.config.id2label
    logger.info("[AnalyzerCascade] Loaded XLM-R from %s on %s (labels: %s)",
                path, device, list(id2label.values()))
    return tokenizer, model, id2label, device


class AnalyzerCascade:
    """Cascade DeBERTa → Analyzer LLM (CH-47.4)."""

    def __init__(
        self,
        confidence_threshold: float = CASCADE_CONFIDENCE_THRESHOLD,
        promotable_types: set = None,
        demoted_llm_type: str = DEMOTED_LLM_TYPE,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.promotable_types = promotable_types or PROMOTABLE_TYPES
        self.demoted_llm_type = demoted_llm_type

    def predict_deberta(self, question: str) -> tuple[str, float, str, float]:
        """Retourne top-1 et top-2 du DeBERTa pour une question."""
        import torch
        tokenizer, model, id2label, device = _load_model()
        inputs = tokenizer(question, return_tensors="pt", truncation=True, max_length=256).to(device)
        with torch.no_grad():
            logits = model(**inputs).logits[0]
            probs = torch.softmax(logits, dim=-1)
        top2 = torch.topk(probs, k=2)
        top1_idx = int(top2.indices[0].item())
        top1_conf = float(top2.values[0].item())
        top2_idx = int(top2.indices[1].item())
        top2_conf = float(top2.values[1].item())
        return id2label[top1_idx], top1_conf, id2label[top2_idx], top2_conf

    def cascade(
        self,
        question: str,
        llm_primary_type: str,
        llm_confidence: float = 0.0,
    ) -> CascadeResult:
        """Applique la cascade : promote si conditions remplies, sinon garde LLM."""
        t0 = time.time()
        try:
            top1, c1, top2, c2 = self.predict_deberta(question)
        except Exception as exc:
            logger.warning("[AnalyzerCascade] DeBERTa failed: %s — keeping LLM type", exc)
            return CascadeResult(
                final_type=llm_primary_type, promoted=False,
                llm_type=llm_primary_type,
                promotion_reason=f"deberta_error: {exc}",
                latency_ms=int((time.time() - t0) * 1000),
            )
        latency_ms = int((time.time() - t0) * 1000)

        # Conditions de promotion (toutes doivent être vraies)
        cond_llm_demoted = (llm_primary_type == self.demoted_llm_type)
        cond_deberta_promotable = (top1 in self.promotable_types)
        cond_confidence = (c1 >= self.confidence_threshold)
        cond_disagree = (top1 != llm_primary_type)

        if cond_llm_demoted and cond_deberta_promotable and cond_confidence and cond_disagree:
            return CascadeResult(
                final_type=top1, promoted=True,
                llm_type=llm_primary_type,
                deberta_top1=top1, deberta_confidence=c1,
                deberta_top2=top2, deberta_top2_confidence=c2,
                promotion_reason=f"llm={llm_primary_type}→deberta={top1} (conf={c1:.2f})",
                latency_ms=latency_ms,
            )

        # Sinon : garder LLM (Analyzer LLM autoritaire en cas de doute)
        return CascadeResult(
            final_type=llm_primary_type, promoted=False,
            llm_type=llm_primary_type,
            deberta_top1=top1, deberta_confidence=c1,
            deberta_top2=top2, deberta_top2_confidence=c2,
            promotion_reason=(
                f"no_promotion: llm_type={llm_primary_type} "
                f"deberta_top1={top1}@{c1:.2f} "
                f"(threshold={self.confidence_threshold}, "
                f"promotable={list(self.promotable_types)})"
            ),
            latency_ms=latency_ms,
        )


# Singleton
_default: Optional[AnalyzerCascade] = None


def get_analyzer_cascade() -> AnalyzerCascade:
    global _default
    if _default is None:
        _default = AnalyzerCascade()
    return _default


def reset_analyzer_cascade() -> None:
    global _default
    _default = None
