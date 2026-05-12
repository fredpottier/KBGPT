"""Multi-view scorer (CH-49 Phase 1, Cap5 / Amendments 7+9).

3 vues complémentaires sur la concordance answer ↔ gold :
  - exact_view   : exact substring match normalisé (existant via structured_metrics)
  - fuzzy_view   : token_set_ratio + partial_ratio (rapidfuzz)
  - semantic_view: embedding cosine similarity (intfloat/multilingual-e5-large)

Pas de max écraseur (challenge ChatGPT). On retourne les 3 scores + un
`dominant_signal` qui indique laquelle a tiré le score (utile pour
l'analyse fuzzy_lift, semantic_only, etc.).

Bonus : `abstain_reward` (Amendment 5) — si gold answerability=unanswerable
ET answer décide ABSTAIN → score 1.0 sur les 3 vues. Anti-Goodhart.

Domain-agnostic : pas de regex métier ni keywords corpus.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────── #
# Lazy imports (évite la dépendance forte aux modèles dans CI / tests unit)
# ──────────────────────────────────────────────────────────────────────── #

_RAPIDFUZZ = None
_EMBEDDER = None


def _get_rapidfuzz():
    global _RAPIDFUZZ
    if _RAPIDFUZZ is None:
        from rapidfuzz import fuzz  # noqa: WPS433
        _RAPIDFUZZ = fuzz
    return _RAPIDFUZZ


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    try:
        from knowbase.common.clients.shared_clients import get_sentence_transformer
        from knowbase.config.settings import get_settings
        settings = get_settings()
        _EMBEDDER = get_sentence_transformer(
            settings.embeddings_model, cache_folder=str(settings.hf_home)
        )
        return _EMBEDDER
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Multi-view scorer: embedder unavailable ({exc})")
        return None


# ──────────────────────────────────────────────────────────────────────── #


@dataclass
class MultiViewScore:
    """Résultat scorer multi-view.

    `dominant_signal` :
      - "exact"    : exact_view ≥ 0.95
      - "fuzzy"    : exact < 0.95 mais fuzzy ≥ 0.85
      - "semantic" : exact < 0.95, fuzzy < 0.85, mais semantic ≥ 0.75
      - "abstain"  : abstain reward (gold unanswerable + answer abstain)
      - "miss"     : aucune vue ne valide
    """

    exact: float  # 0..1
    fuzzy: float  # 0..1
    semantic: float  # 0..1 (cosine clipped)
    dominant_signal: str  # exact | fuzzy | semantic | abstain | miss
    abstain_reward_applied: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def best(self) -> float:
        """Score représentatif (max des 3 vues)."""
        return max(self.exact, self.fuzzy, self.semantic)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def exact_view(answer: str, references: list[str]) -> float:
    """Substring match normalisé. Score = max recall sur l'union des références."""
    if not references:
        return 0.0
    answer_norm = _normalize(answer)
    if not answer_norm:
        return 0.0
    hits = 0
    for ref in references:
        ref_norm = _normalize(ref)
        if ref_norm and ref_norm in answer_norm:
            hits += 1
    return hits / max(1, len(references))


def fuzzy_view(answer: str, references: list[str]) -> float:
    """Score fuzzy via rapidfuzz token_set_ratio + partial_ratio (max). Normalisé 0..1."""
    if not references:
        return 0.0
    fuzz = _get_rapidfuzz()
    answer_norm = _normalize(answer)
    if not answer_norm:
        return 0.0
    scores: list[float] = []
    for ref in references:
        ref_norm = _normalize(ref)
        if not ref_norm:
            continue
        token_set = fuzz.token_set_ratio(answer_norm, ref_norm) / 100.0
        partial = fuzz.partial_ratio(answer_norm, ref_norm) / 100.0
        scores.append(max(token_set, partial))
    return max(scores) if scores else 0.0


def semantic_view(answer: str, references: list[str]) -> float:
    """Cosine similarity max entre embedding(answer) et embeddings(references).

    Pour rester rapide on encode tout en une seule passe via SentenceTransformer.
    Returns 0..1 (cosine clipped).
    """
    if not references:
        return 0.0
    embedder = _get_embedder()
    if embedder is None:
        return 0.0
    answer_norm = _normalize(answer)
    if not answer_norm:
        return 0.0
    refs_norm = [_normalize(r) for r in references if r]
    if not refs_norm:
        return 0.0
    try:
        # E5 multilingual recommends "query:" prefix mais pour scoring on évite
        # (les references sont aussi de l'anglais générique). Sans préfixe ⇒ symétrique.
        vecs = embedder.encode(
            [answer_norm] + refs_norm,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Semantic view: encode failed ({exc})")
        return 0.0
    if vecs is None or len(vecs) < 2:
        return 0.0
    a_vec = vecs[0]
    sims = [float((a_vec * v).sum()) for v in vecs[1:]]  # already normalized
    if not sims:
        return 0.0
    return max(0.0, min(1.0, max(sims)))


DEFAULT_THRESHOLDS = {
    "exact": 0.95,
    "fuzzy": 0.85,
    "semantic": 0.75,  # À recalibrer post P1.6 — embedder e5 a des sims génériques élevées
}


def _select_dominant(
    exact: float,
    fuzzy: float,
    semantic: float,
    thresholds: dict[str, float] = DEFAULT_THRESHOLDS,
) -> str:
    if exact >= thresholds.get("exact", 0.95):
        return "exact"
    if fuzzy >= thresholds.get("fuzzy", 0.85):
        return "fuzzy"
    if semantic >= thresholds.get("semantic", 0.75):
        return "semantic"
    return "miss"


def multi_view_score(
    answer: str,
    gold_answer: str,
    expected_identifiers: Optional[list[str]] = None,
    list_items_expected: Optional[list[str]] = None,
    answerability: Optional[str] = None,
    decision: Optional[str] = None,
    thresholds: Optional[dict[str, float]] = None,
) -> MultiViewScore:
    """Scorer multi-view principal.

    Args:
        answer: réponse produite par le pipeline
        gold_answer: réponse de référence (gold v5 ground_truth.answer)
        expected_identifiers: identifiants critiques du gold (renforce exact_view)
        list_items_expected: items attendus pour list questions
        answerability: "answerable" | "partial" | "unanswerable" (pour abstain reward)
        decision: "ANSWER" | "ABSTAIN" (pour abstain reward)

    Returns:
        MultiViewScore avec exact/fuzzy/semantic + dominant_signal.
    """
    # Abstain reward (anti-Goodhart) — Amendment 5
    if (
        answerability == "unanswerable"
        and decision == "ABSTAIN"
    ):
        return MultiViewScore(
            exact=1.0, fuzzy=1.0, semantic=1.0,
            dominant_signal="abstain",
            abstain_reward_applied=True,
            detail={"reason": "abstain_correct_unanswerable"},
        )

    # Construit les références : answer principal + identifiers + items
    references: list[str] = []
    if gold_answer:
        references.append(gold_answer)
    if expected_identifiers:
        references.extend(expected_identifiers)
    if list_items_expected:
        references.extend(list_items_expected)

    if not references:
        # Aucune référence : score nul, dominant = miss
        return MultiViewScore(
            exact=0.0, fuzzy=0.0, semantic=0.0,
            dominant_signal="miss",
            detail={"reason": "no_reference_available"},
        )

    e = exact_view(answer, references)
    f = fuzzy_view(answer, references)
    s = semantic_view(answer, references)
    th = thresholds or DEFAULT_THRESHOLDS

    # Pénalité fuzzy + semantic : si identifiers critiques attendus mais peu trouvés,
    # cap les vues sémantiquement permissives. Cela évite les false_positives où la
    # réponse partage le sujet général ("Eiffel Tower 1923 London" vs "1889 Paris").
    # Garde-fou contre le piège fuzzy `partial_ratio` qui matche quand les tokens
    # sont identiques mais l'ordre/quantificateurs sont inversés.
    fuzzy_penalty_applied = False
    semantic_penalty_applied = False
    id_coverage = None
    if expected_identifiers:
        answer_norm = _normalize(answer)
        n_id_matched = sum(
            1 for i in expected_identifiers if _normalize(i) in answer_norm
        )
        id_coverage = n_id_matched / len(expected_identifiers)
        if id_coverage < 0.4:
            s = min(s, 0.6)
            f = min(f, 0.7)
            semantic_penalty_applied = True
            fuzzy_penalty_applied = True

    return MultiViewScore(
        exact=round(e, 3),
        fuzzy=round(f, 3),
        semantic=round(s, 3),
        dominant_signal=_select_dominant(e, f, s, th),
        detail={
            "n_references": len(references),
            "n_identifiers": len(expected_identifiers or []),
            "n_list_items": len(list_items_expected or []),
            "thresholds": th,
            "semantic_penalty_applied": semantic_penalty_applied,
            "fuzzy_penalty_applied": fuzzy_penalty_applied,
            "id_coverage": id_coverage,
        },
    )


def aggregate_multi_view(scores: list[MultiViewScore]) -> dict[str, Any]:
    """Agrégat distribution + means par vue + dominant_signal counts."""
    if not scores:
        return {"n": 0}
    means = {
        "exact": _mean(s.exact for s in scores),
        "fuzzy": _mean(s.fuzzy for s in scores),
        "semantic": _mean(s.semantic for s in scores),
        "best": _mean(s.best for s in scores),
    }
    dominant_counts: dict[str, int] = {}
    for s in scores:
        dominant_counts[s.dominant_signal] = dominant_counts.get(s.dominant_signal, 0) + 1
    return {
        "n": len(scores),
        "means": means,
        "dominant_signal_counts": dominant_counts,
        "abstain_reward_count": sum(1 for s in scores if s.abstain_reward_applied),
    }


def _mean(it) -> float:
    values = list(it)
    return round(sum(values) / len(values), 3) if values else 0.0
