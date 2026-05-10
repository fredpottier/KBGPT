"""
OSMOSIS V4 — HHEM-2.1 NLI Judge (CH-41 Channel 2 alternative).

Vectara HHEM-2.1-Open : DeBERTa-v3-large fine-tuned pour faithfulness, mieux
calibré que mDeBERTa-XNLI sur les paraphrases verbatim (audit Channel 2 a
montré que mDeBERTa rate les paraphrases : 4/10 UNFAITHFUL = paraphrases
correctes mal classées).

Référence : `reference_rag_faithfulness_state_of_art_2025_2026.md` :
> HHEM-2.1-Open : 600MB CPU, multilingue FR/EN/DE, état de l'art 2025

API : prend (premise, hypothesis), retourne score 0-1 (1.0 = entailed, 0.0 = contradicted).

Utilisable via Channel2NLIVerifier en switchant `NLI_BACKEND=hhem` (default `mdeberta`).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)

HHEM_MODEL = os.getenv("HHEM_MODEL", "vectara/hallucination_evaluation_model")
HHEM_DEVICE = os.getenv("HHEM_DEVICE", "cuda")  # cuda|cpu
HHEM_THRESHOLD = float(os.getenv("HHEM_THRESHOLD", "0.5"))


@dataclass
class HhemClaimVerdict:
    claim: str
    verdict: str  # SUPPORTED | UNSUPPORTED | NEUTRAL
    score: float = 0.0
    best_evidence_idx: Optional[int] = None


@dataclass
class HhemFaithfulnessReport:
    overall_score: float = 1.0
    overall_verdict: str = "FAITHFUL"
    n_claims: int = 0
    n_supported: int = 0
    n_unsupported: int = 0
    n_neutral: int = 0
    claim_verdicts: list[HhemClaimVerdict] = field(default_factory=list)
    diagnostic: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _get_hhem_model():
    """Lazy-load HHEM-2.1 (singleton)."""
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch

        device = HHEM_DEVICE
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("[HHEM] CUDA unavailable, fallback CPU")
            device = "cpu"
        logger.info("[HHEM] Loading %s on %s", HHEM_MODEL, device)
        tokenizer = AutoTokenizer.from_pretrained(HHEM_MODEL, trust_remote_code=True)
        model = AutoModelForSequenceClassification.from_pretrained(HHEM_MODEL, trust_remote_code=True)
        model.to(device)
        model.eval()
        return tokenizer, model, device, torch
    except Exception as exc:
        logger.warning("[HHEM] failed to load: %s", exc)
        return None


def _split_into_atomic_claims(answer: str, max_claims: int = 8) -> list[str]:
    """Split answer en phrases (réutilise la même heuristique que mDeBERTa nli_judge)."""
    import re
    if not answer:
        return []
    # Split sur ponctuation forte, garder ≥ 5 mots
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer.strip())
    out = []
    for s in sentences:
        s = s.strip()
        if not s or len(s.split()) < 3:
            continue
        if s.startswith("- ") or s.startswith("* "):
            s = s[2:].strip()
        if len(s) > 10:
            out.append(s)
    return out[:max_claims]


def judge_faithfulness_hhem(
    answer: str,
    claims: list[Any],
    max_claims_in_eval: int = 8,
    max_evidence_chars: int = 500,
) -> HhemFaithfulnessReport:
    """Évalue faithfulness via HHEM-2.1.

    Args:
        answer: réponse synthétisée
        claims: liste d'objets avec .text (ou dict avec 'text')
    """
    report = HhemFaithfulnessReport()

    if not answer or len(answer.strip()) < 30:
        report.diagnostic["skip_reason"] = "answer_too_short"
        return report

    if not claims:
        report.overall_score = 0.0
        report.overall_verdict = "UNFAITHFUL"
        report.diagnostic["skip_reason"] = "no_evidence"
        return report

    atomic_claims = _split_into_atomic_claims(answer, max_claims_in_eval)
    if not atomic_claims:
        report.diagnostic["skip_reason"] = "no_atomic_claims"
        return report

    evidence_texts = []
    for c in claims[:10]:
        text = getattr(c, "text", None) if not isinstance(c, dict) else c.get("text")
        if text:
            evidence_texts.append(text[:max_evidence_chars])

    if not evidence_texts:
        report.overall_score = 0.0
        report.overall_verdict = "UNFAITHFUL"
        report.diagnostic["skip_reason"] = "no_evidence_text"
        return report

    loaded = _get_hhem_model()
    if loaded is None:
        report.diagnostic["skip_reason"] = "hhem_load_failed"
        report.overall_verdict = "SKIPPED"
        return report
    tokenizer, model, device, torch = loaded

    pairs = []
    pair_meta = []
    for ci, claim in enumerate(atomic_claims):
        for ei, ev in enumerate(evidence_texts):
            pairs.append((ev, claim))
            pair_meta.append((ci, ei))

    try:
        # HHEM format : "[premise]\n[hypothesis]"
        formatted = [f"{p}\n{h}" for p, h in pairs]
        with torch.no_grad():
            inputs = tokenizer(formatted, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(device) for k, v in inputs.items()}
            outputs = model(**inputs)
            # HHEM-2.1 output : sigmoid score (0-1)
            scores = torch.sigmoid(outputs.logits).squeeze(-1).cpu().numpy().tolist()
    except Exception as exc:
        logger.warning("[HHEM] inference failed: %s", exc)
        report.diagnostic["skip_reason"] = f"hhem_error: {exc}"
        report.overall_verdict = "SKIPPED"
        return report

    # Aggregate per claim : max score across evidence
    claim_best: dict[int, tuple[float, int]] = {}
    for (ci, ei), score in zip(pair_meta, scores):
        cur = claim_best.get(ci, (0.0, -1))
        if score > cur[0]:
            claim_best[ci] = (float(score), ei)

    n_supported = n_unsupported = n_neutral = 0
    for ci, claim in enumerate(atomic_claims):
        best_score, best_ei = claim_best.get(ci, (0.0, -1))
        if best_score >= HHEM_THRESHOLD:
            verdict = "SUPPORTED"; n_supported += 1
        elif best_score < (1 - HHEM_THRESHOLD):
            verdict = "UNSUPPORTED"; n_unsupported += 1
        else:
            verdict = "NEUTRAL"; n_neutral += 1
        report.claim_verdicts.append(HhemClaimVerdict(
            claim=claim, verdict=verdict, score=best_score, best_evidence_idx=best_ei,
        ))

    n_total = len(atomic_claims)
    report.n_claims = n_total
    report.n_supported = n_supported
    report.n_unsupported = n_unsupported
    report.n_neutral = n_neutral
    if n_total > 0:
        report.overall_score = n_supported / n_total
        if n_supported / n_total >= 0.7:
            report.overall_verdict = "FAITHFUL"
        elif n_unsupported / n_total >= 0.5:
            report.overall_verdict = "UNFAITHFUL"
        else:
            report.overall_verdict = "PARTIAL"
    return report
