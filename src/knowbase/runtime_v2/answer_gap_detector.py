"""
Answer Gap Detector (CH-13) — détection déterministe pré-LLM des questions
unanswerable via TF-IDF inverse.

**Principe** : si la question contient des termes spécifiques (IDF élevé,
i.e. rares dans le corpus) qui n'apparaissent pas dans les chunks/claims
retrouvés, alors la réponse risque d'être hallucinée. On classe la question
en `ANSWERABLE` / `UNCERTAIN` / `UNANSWERABLE` sans appel LLM.

**Couverture cible** (CH-13) : sur les 25 questions unanswerable du benchmark
T6, ≥18 détectées (≥72%) sans dégrader les ANSWERABLE.

Le module est défensif : si le corpus est trop petit pour avoir une IDF
fiable, ou si l'extraction échoue, retourne `ANSWERABLE` (no-op safe).
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# ── Tunables (à calibrer empiriquement sur 25 unanswerable T6) ──────────

# IDF au-dessus duquel un terme est considéré "spécifique"
# (présent dans < e^-2.5 ≈ 8% des chunks de l'échantillon).
SPECIFIC_TERM_IDF_THRESHOLD = 2.5

# Longueur minimum d'un terme pour être considéré
MIN_TERM_LENGTH = 3

# Longueur minimum pour considérer un terme hors-corpus comme "manquant"
# (filtre les typos courts, mots dans une autre langue improbable, etc.)
MIN_OUT_OF_CORPUS_TERM_LENGTH = 4

# Seuils de classification
GAP_SCORE_UNANSWERABLE = 0.50  # ≥50% des termes spécifiques manquants = UNANSWERABLE
GAP_SCORE_UNCERTAIN = 0.25     # 25-50% manquants = UNCERTAIN
# < 0.25 = ANSWERABLE


_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9_/-]{%d,}" % MIN_TERM_LENGTH)


def _tokenize(text: str) -> set[str]:
    """Tokenisation lowercase, dedup, longueur ≥ MIN_TERM_LENGTH."""
    if not text:
        return set()
    return {tok.lower() for tok in _TOKEN_RE.findall(text)}


def extract_specific_terms(question: str) -> list[str]:
    """Termes "spécifiques" de la question (IDF haut ou hors-corpus).

    Retourne les tokens dont l'IDF dans le corpus est ≥ SPECIFIC_TERM_IDF_THRESHOLD,
    OU qui sont absents du sample (probablement spécifiques au domaine de la question).
    Filtre les termes très courts pour limiter le bruit.
    """
    try:
        from knowbase.common.corpus_stats import get_corpus_idf, is_corpus_large_enough
    except Exception as exc:
        logger.warning("[ANSWER_GAP] corpus_stats unavailable: %s", exc)
        return []

    if not is_corpus_large_enough():
        return []

    idf_map = get_corpus_idf() or {}
    if not idf_map:
        return []

    tokens = _tokenize(question)
    specific: list[str] = []
    for tok in tokens:
        idf = idf_map.get(tok)
        if idf is None:
            # Hors-corpus → spécifique (sauf si trop court)
            if len(tok) >= MIN_OUT_OF_CORPUS_TERM_LENGTH:
                specific.append(tok)
        elif idf >= SPECIFIC_TERM_IDF_THRESHOLD:
            specific.append(tok)
    return specific


def compute_gap_score(
    specific_terms: Iterable[str],
    retrieved_text: str,
) -> tuple[float, list[str], list[str]]:
    """Calcule le gap_score entre termes spécifiques de la question
    et le texte retrouvé (concaténation chunks/claims).

    Returns:
        (gap_score, found_terms, missing_terms)
        gap_score ∈ [0, 1] : 0 = tous trouvés, 1 = tous manquants
    """
    spec = [t for t in specific_terms if t]
    if not spec:
        return 0.0, [], []

    haystack_tokens = _tokenize(retrieved_text)
    found = [t for t in spec if t in haystack_tokens]
    missing = [t for t in spec if t not in haystack_tokens]
    gap = 1.0 - (len(found) / len(spec)) if spec else 0.0
    return gap, found, missing


def classify(gap_score: float) -> str:
    """Classification déterministe : ANSWERABLE | UNCERTAIN | UNANSWERABLE."""
    if gap_score >= GAP_SCORE_UNANSWERABLE:
        return "UNANSWERABLE"
    if gap_score >= GAP_SCORE_UNCERTAIN:
        return "UNCERTAIN"
    return "ANSWERABLE"


def detect_answer_gap(
    question: str,
    retrieved_text: str,
) -> dict:
    """API publique — détecte le gap question/contexte.

    Args:
        question: question utilisateur
        retrieved_text: concaténation du texte des chunks/claims top-K (avant synthèse)

    Returns:
        {
            "gap_score": float,        # 0 = tous les termes trouvés, 1 = tous manquants
            "classification": str,      # ANSWERABLE | UNCERTAIN | UNANSWERABLE
            "n_specific_terms": int,
            "specific_terms": list,
            "found": list,
            "missing": list,
        }
    """
    try:
        terms = extract_specific_terms(question)
        if not terms:
            return {
                "gap_score": 0.0,
                "classification": "ANSWERABLE",
                "n_specific_terms": 0,
                "specific_terms": [],
                "found": [],
                "missing": [],
                "skip_reason": "no_specific_terms_or_corpus_too_small",
            }
        gap, found, missing = compute_gap_score(terms, retrieved_text)
        return {
            "gap_score": gap,
            "classification": classify(gap),
            "n_specific_terms": len(terms),
            "specific_terms": terms,
            "found": found,
            "missing": missing,
        }
    except Exception as exc:
        logger.warning("[ANSWER_GAP] detection failed (non-blocking): %s", exc)
        return {
            "gap_score": 0.0,
            "classification": "ANSWERABLE",
            "n_specific_terms": 0,
            "specific_terms": [],
            "found": [],
            "missing": [],
            "error": str(exc),
        }
