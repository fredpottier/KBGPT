"""
HALT/EPR — Logprob Entropy Detection (CH-14).

Calcule l'entropie Shannon moyenne sur la sortie LLM générée. Un signal
post-hoc cross-lingue, gratuit, qui flag les réponses où le LLM hésitait
fortement entre plusieurs continuations (= corrélé à l'hallucination ou
à l'absence de support factuel).

Source académique : Google Research 2024 — "Detecting hallucinations via
predictive entropy in instruction-tuned LLMs".

Le seuil exact à utiliser pour flagger une réponse "low_confidence" sera
calibré empiriquement (mémoire feedback) — la fonction expose le score brut.
"""
from __future__ import annotations

import logging
import math
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def compute_avg_entropy(
    logprobs_content: Optional[Iterable[dict]],
) -> Optional[float]:
    """Entropie Shannon moyenne sur la séquence générée.

    Format attendu (OpenAI/vLLM/DeepInfra compatible) :

        logprobs_content = [
            {
                "token": "...",
                "logprob": -0.12,
                "top_logprobs": [
                    {"token": "...", "logprob": -0.12},
                    {"token": "...", "logprob": -2.1},
                    ...
                ],
            },
            ...
        ]

    Pour chaque position, on calcule H_t = -sum(p_i log p_i) sur les top_logprobs
    re-normalisés (somme à 1 sur les top-K). On moyenne sur tous les tokens.

    H bas (0.0–0.5)   = LLM très confiant — bon signe (réponse extractive)
    H moyen (0.5–1.5) = LLM modérément confiant — normal en synthèse
    H haut (>1.5)     = LLM hésitant — signal hallucination potentielle

    Returns:
        L'entropie moyenne (float ≥ 0), ou None si pas de logprobs.
    """
    if not logprobs_content:
        return None

    total = 0.0
    n = 0
    for tok in logprobs_content:
        try:
            top = tok.get("top_logprobs") or []
        except AttributeError:
            continue
        if not top:
            continue
        # Re-normaliser les probabilités sur les top-K (la somme n'est pas exactement 1
        # car on tronque au top_logprobs, mais s'en approche pour les logprobs élevés).
        probs = []
        for item in top:
            lp = item.get("logprob") if isinstance(item, dict) else None
            if lp is None:
                continue
            probs.append(math.exp(lp))
        if not probs:
            continue
        s = sum(probs)
        if s <= 0:
            continue
        probs = [p / s for p in probs]
        h = -sum(p * math.log(p + 1e-12) for p in probs if p > 0)
        total += h
        n += 1

    if n == 0:
        return None
    return total / n


# Seuil par défaut au-dessus duquel on flag "low_confidence" / "potentially unfounded".
# À calibrer empiriquement (cf. CH-14 : Pearson corrélation entropy vs hallucinations
# détectées par juge LLM ≥ 0.5 sur 100 questions).
LOW_CONFIDENCE_ENTROPY_THRESHOLD = 1.5


def is_low_confidence(entropy: Optional[float], threshold: float = LOW_CONFIDENCE_ENTROPY_THRESHOLD) -> bool:
    """True si entropy ≥ threshold (réponse potentiellement non fondée)."""
    if entropy is None:
        return False
    return entropy >= threshold
