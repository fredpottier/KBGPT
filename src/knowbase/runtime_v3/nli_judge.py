"""
NLI Faithfulness Judge — CH-39.1.

Multilingual NLI cross-encoder for hallucination detection.
Replaces the LLM-as-judge pattern (faithfulness_judge.py + premise_validator.py
+ hallucination_guard.py from runtime_v2) with a single specialized model.

Why a specialized NLI model :
- 2026 SOTA : Lynx (Patronus 8B) bat GPT-4o sur HaluBench
- Galileo Luna (DeBERTa 440M) : -97% coût / -91% latence vs GPT-3.5
- HHEM-2.1-Open : 600MB CPU, multilingue
- LLM-as-judge fail souvent sur reasoning tasks complexes

Implementation :
- Model : MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
  (278M params, multilingue 100+ langues, transformers 5.x compatible)
- Latence : ~0.3-0.6s pour 5-30 paires sur GPU
- Score : entailment - contradiction probability per claim×evidence pair

Domain-agnostic par construction (NLI universel, pas de regex/listes).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Multilingual NLI model — supports FR/EN/DE/ES/IT/100+ languages
NLI_MODEL = os.getenv("RUNTIME_V3_NLI_MODEL", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
NLI_DEVICE = os.getenv("RUNTIME_V3_NLI_DEVICE", "cuda")  # cuda|cpu
# Seuils interpretation (sur softmax probabilities)
ENTAILMENT_THRESHOLD = float(os.getenv("RUNTIME_V3_NLI_ENTAIL_THRESHOLD", "0.5"))
CONTRADICTION_THRESHOLD = float(os.getenv("RUNTIME_V3_NLI_CONTRA_THRESHOLD", "0.5"))


@dataclass
class ClaimVerdict:
    """Verdict NLI pour un atomic claim de la réponse."""
    claim: str
    verdict: str  # SUPPORTED | UNSUPPORTED | NEUTRAL
    entailment: float = 0.0
    contradiction: float = 0.0
    best_evidence_idx: Optional[int] = None  # index du chunk evidence le plus support


@dataclass
class FaithfulnessReport:
    """Rapport faithfulness sur la réponse complète."""
    overall_score: float = 1.0
    overall_verdict: str = "FAITHFUL"  # FAITHFUL | PARTIAL | UNFAITHFUL
    n_claims: int = 0
    n_supported: int = 0
    n_unsupported: int = 0
    n_neutral: int = 0
    claim_verdicts: list[ClaimVerdict] = field(default_factory=list)
    diagnostic: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _get_nli_model():
    """Singleton du modèle NLI."""
    from sentence_transformers import CrossEncoder
    import torch
    device = NLI_DEVICE
    if device == "cuda" and not torch.cuda.is_available():
        logger.warning("[NLI_JUDGE] CUDA unavailable, fallback CPU")
        device = "cpu"
    model = CrossEncoder(NLI_MODEL, device=device)
    logger.info("[NLI_JUDGE] Loaded %s on %s", NLI_MODEL, device)
    return model


def _split_into_atomic_claims(answer: str) -> list[str]:
    """Découpe la réponse en claims atomiques.

    Stratégie simple : split sur fin de phrase (., !, ?).
    Évite l'overhead d'un LLM call dédié (cf. VeriFastScore qui distille FActScore).

    Filtre les claims trop courts (< 15 chars) ou purement abstentifs.
    """
    # Strip citation tokens [doc=xxx] avant split
    cleaned = re.sub(r"\[doc[^\]]*\]", "", answer or "")
    # Split sur ponctuation fin de phrase
    sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    claims = []
    for s in sentences:
        s = s.strip()
        # Filtre : trop court, ou pure abstention sémantique
        if len(s) < 15:
            continue
        # Garde tous les claims, y compris abstentifs (le NLI les marquera NEUTRAL)
        claims.append(s)
    return claims


def judge_faithfulness(
    answer: str,
    claims: list[Any],
    max_claims_in_eval: int = 8,
    max_evidence_chars: int = 500,
) -> FaithfulnessReport:
    """Évalue la fidélité de `answer` par rapport aux `claims`/evidence chunks.

    Pour chaque atomic claim de l'answer, calcule NLI vs chaque evidence chunk.
    Aggrège : verdict = SUPPORTED si max(entailment) > seuil ET
                                    max(contradiction) < seuil-min ; sinon UNSUPPORTED ;
                                    sinon NEUTRAL.

    Args:
        answer: réponse synthétisée
        claims: liste d'EvidenceClaim-like (.text et .doc_id)
        max_claims_in_eval: limite sur nb d'atomic claims évalués (cost control)
        max_evidence_chars: tronque le texte evidence par claim

    Returns:
        FaithfulnessReport avec score global + verdicts par claim.
    """
    report = FaithfulnessReport()

    if not answer or len(answer.strip()) < 30:
        report.diagnostic["skip_reason"] = "answer_too_short"
        return report

    if not claims:
        report.overall_score = 0.0
        report.overall_verdict = "UNFAITHFUL"
        report.diagnostic["skip_reason"] = "no_evidence"
        return report

    atomic_claims = _split_into_atomic_claims(answer)[:max_claims_in_eval]
    if not atomic_claims:
        report.diagnostic["skip_reason"] = "no_atomic_claims_extracted"
        return report

    evidence_texts = []
    for c in claims[:10]:  # up to 10 evidence chunks
        text = getattr(c, "text", None) if not isinstance(c, dict) else c.get("text")
        if text:
            evidence_texts.append(text[:max_evidence_chars])

    if not evidence_texts:
        report.overall_score = 0.0
        report.overall_verdict = "UNFAITHFUL"
        report.diagnostic["skip_reason"] = "no_evidence_text"
        return report

    # Build NLI pairs : (premise=evidence, hypothesis=claim)
    pairs = []
    pair_meta = []  # (claim_idx, evidence_idx)
    for ci, claim in enumerate(atomic_claims):
        for ei, ev in enumerate(evidence_texts):
            pairs.append((ev, claim))
            pair_meta.append((ci, ei))

    try:
        model = _get_nli_model()
        import torch
        logits = model.predict(pairs)
        probs = torch.softmax(torch.tensor(logits), dim=-1).numpy()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NLI_JUDGE] Model call failed: %s — fallback PARTIAL", exc)
        report.overall_score = 0.5
        report.overall_verdict = "PARTIAL"
        report.diagnostic["fallback_reason"] = f"{type(exc).__name__}"
        return report

    # Aggregate per-claim : max entailment, max contradiction across evidence
    # Label order : [ENTAILMENT, NEUTRAL, CONTRADICTION]
    per_claim_max_entail = [0.0] * len(atomic_claims)
    per_claim_max_contra = [0.0] * len(atomic_claims)
    per_claim_best_ev = [None] * len(atomic_claims)
    for (ci, ei), p in zip(pair_meta, probs):
        ent, _, contra = float(p[0]), float(p[1]), float(p[2])
        if ent > per_claim_max_entail[ci]:
            per_claim_max_entail[ci] = ent
            per_claim_best_ev[ci] = ei
        if contra > per_claim_max_contra[ci]:
            per_claim_max_contra[ci] = contra

    # Verdict per claim
    n_supported = n_unsupported = n_neutral = 0
    for i, claim in enumerate(atomic_claims):
        ent = per_claim_max_entail[i]
        contra = per_claim_max_contra[i]
        if ent >= ENTAILMENT_THRESHOLD and contra < CONTRADICTION_THRESHOLD:
            verdict = "SUPPORTED"
            n_supported += 1
        elif contra >= CONTRADICTION_THRESHOLD:
            verdict = "UNSUPPORTED"
            n_unsupported += 1
        else:
            verdict = "NEUTRAL"
            n_neutral += 1
        report.claim_verdicts.append(ClaimVerdict(
            claim=claim[:300],
            verdict=verdict,
            entailment=round(ent, 3),
            contradiction=round(contra, 3),
            best_evidence_idx=per_claim_best_ev[i],
        ))

    report.n_claims = len(atomic_claims)
    report.n_supported = n_supported
    report.n_unsupported = n_unsupported
    report.n_neutral = n_neutral

    n_factual = n_supported + n_unsupported
    if n_factual == 0:
        report.overall_score = 1.0
        report.overall_verdict = "FAITHFUL"
        report.diagnostic["all_neutral"] = True
    else:
        report.overall_score = n_supported / n_factual
        if report.overall_score >= 0.8:
            report.overall_verdict = "FAITHFUL"
        elif report.overall_score >= 0.5:
            report.overall_verdict = "PARTIAL"
        else:
            report.overall_verdict = "UNFAITHFUL"

    logger.info(
        "[NLI_JUDGE] verdict=%s score=%.2f sup=%d unsup=%d neutral=%d",
        report.overall_verdict, report.overall_score,
        n_supported, n_unsupported, n_neutral,
    )
    return report


def should_regenerate(report: FaithfulnessReport, threshold: float = 0.5) -> bool:
    """Décide s'il faut régénérer la réponse.

    Regen seulement si UNFAITHFUL avec score < threshold.
    Pas de regen sur PARTIAL pour limiter latence (tradeoff CH-39).
    """
    return (
        report.overall_verdict == "UNFAITHFUL"
        and report.overall_score < threshold
    )
