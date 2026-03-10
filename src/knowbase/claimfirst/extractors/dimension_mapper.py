# src/knowbase/claimfirst/extractors/dimension_mapper.py
"""
Dimension Mapper v2 — Stabilisation des questions en QuestionDimension (Étape 3a).

V2 = match déterministe + bonus embedding (si score déterministe < 0.8).

Architecture scoring en 3 couches :
1. Checks bloquants (value_type, operator inversion, semantic inversion)
2. Score déterministe (match exact → 1.0, préfixe commun ≥ 60% → 0.8)
3. Bonus embedding (seulement si score déterministe < 0.8)
   - cosine ≥ 0.85 → bonus +0.3 (plafonné à 0.95)
   - cosine < 0.60 → pas de bonus
   - entre 0.60 et 0.85 → bonus proportionnel

Seuil match ≥ 0.7 + aucun bloquant → merge vers dimension existante.
Sinon → créer nouvelle QuestionDimension candidate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from knowbase.claimfirst.models.question_dimension import QuestionDimension

logger = logging.getLogger("[OSMOSE] dimension_mapper")


# Paires d'inversion sémantique (les deux sens)
_INVERSION_PAIRS = [
    (r"\bmin[_\s]", r"\bmax[_\s]"),
    (r"\bminimum", r"\bmaximum"),
    (r"\benabled", r"\bdisabled"),
    (r"\brequired", r"\boptional"),
    (r"\ballowed", r"\bprohibited"),
    (r"\bsupported", r"\bunsupported"),
]


@dataclass
class MatchTrace:
    """Traçabilité d'une décision de merge pour audit."""
    match_strategy: str     # "exact" | "prefix" | "embedding_bonus" | "new_dimension"
    score_deterministic: float
    score_embedding: Optional[float] = None
    score_final: float = 0.0
    blocked_by: Optional[str] = None  # "value_type" | "operator_inversion" | "semantic_inversion" | None
    matched_dimension_id: Optional[str] = None


class DimensionMapperV2:
    """Dimension mapper avec cache d'embeddings pour dedup amélioré."""

    def __init__(self):
        self._embedding_cache: Dict[str, np.ndarray] = {}
        self._encoder = None

    def _get_encoder(self):
        """Lazy load de l'encoder d'embeddings."""
        if self._encoder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            self._encoder = EmbeddingModelManager()
        return self._encoder

    def _encode(self, text: str) -> np.ndarray:
        """Encode un texte avec cache."""
        if text in self._embedding_cache:
            return self._embedding_cache[text]
        encoder = self._get_encoder()
        result = encoder.encode([text])
        vec = result[0] if len(result.shape) > 1 else result
        self._embedding_cache[text] = vec
        return vec

    def preload_registry(self, registry: List[QuestionDimension]) -> None:
        """Pré-charge les embeddings du registre existant."""
        questions = [dim.canonical_question for dim in registry if dim.canonical_question]
        if not questions:
            return
        try:
            encoder = self._get_encoder()
            embeddings = encoder.encode(questions)
            for i, dim in enumerate(registry):
                if dim.canonical_question and i < len(embeddings):
                    vec = embeddings[i] if len(embeddings.shape) > 1 else embeddings
                    self._embedding_cache[dim.canonical_question] = vec
            logger.info(f"[DimMapper] Pre-loaded {len(questions)} embeddings")
        except Exception as e:
            logger.warning(f"[DimMapper] Embedding preload failed: {e}")

    def map_to_dimension(
        self,
        candidate_key: str,
        candidate_question: str,
        value_type: str,
        operator: str,
        registry: List[QuestionDimension],
        use_embeddings: bool = True,
    ) -> Tuple[Optional[str], float, MatchTrace]:
        """
        Mappe un candidat vers une QuestionDimension existante.

        Returns:
            (dimension_id, match_score, trace)
            (None, 0.0, trace) si aucun match
        """
        if not registry:
            trace = MatchTrace(
                match_strategy="new_dimension",
                score_deterministic=0.0,
                score_final=0.0,
            )
            return (None, 0.0, trace)

        candidate_key_norm = candidate_key.lower().strip()

        best_match: Optional[str] = None
        best_score: float = 0.0
        best_trace = MatchTrace(
            match_strategy="new_dimension",
            score_deterministic=0.0,
            score_final=0.0,
        )

        for dim in registry:
            # Ignorer les dimensions mergées
            if dim.status == "merged":
                continue

            dim_key_norm = dim.dimension_key.lower().strip()

            # ── Checks bloquants ─────────────────────────────────────────
            if dim.value_type != value_type:
                continue

            if _is_operator_inversion(operator, dim.allowed_operators):
                continue

            if _is_semantic_inversion(candidate_key_norm, dim_key_norm):
                continue

            # ── Score déterministe ───────────────────────────────────────
            det_score = 0.0
            strategy = "new_dimension"

            if candidate_key_norm == dim_key_norm:
                det_score = 1.0
                strategy = "exact"
            else:
                prefix_ratio = _common_prefix_ratio(candidate_key_norm, dim_key_norm)
                if prefix_ratio >= 0.6:
                    det_score = 0.8
                    strategy = "prefix"

            # ── Bonus embedding (seulement si score < 0.8) ──────────────
            emb_score = None
            final_score = det_score

            if det_score < 0.8 and use_embeddings and candidate_question and dim.canonical_question:
                try:
                    emb_score = self._compute_embedding_similarity(
                        candidate_question, dim.canonical_question
                    )
                    if emb_score is not None:
                        bonus = _compute_embedding_bonus(emb_score)
                        if bonus > 0:
                            final_score = min(det_score + bonus, 0.95)
                            # Cosine très haute → le score final suffit pour merger
                            if emb_score >= 0.85:
                                final_score = max(final_score, 0.75)
                            if final_score > det_score:
                                strategy = "embedding_bonus"
                except Exception as e:
                    logger.debug(f"[DimMapper] Embedding error: {e}")

            if final_score > best_score:
                best_score = final_score
                best_match = dim.dimension_id
                best_trace = MatchTrace(
                    match_strategy=strategy,
                    score_deterministic=det_score,
                    score_embedding=emb_score,
                    score_final=final_score,
                    matched_dimension_id=dim.dimension_id,
                )

        if best_score >= 0.7 and best_match:
            return (best_match, best_score, best_trace)

        best_trace.match_strategy = "new_dimension"
        best_trace.matched_dimension_id = None
        return (None, 0.0, best_trace)

    def _compute_embedding_similarity(self, text_a: str, text_b: str) -> Optional[float]:
        """Cosine similarity entre deux textes."""
        vec_a = self._encode(text_a)
        vec_b = self._encode(text_b)
        return _cosine_similarity(vec_a, vec_b)


def _cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Cosine similarity entre deux vecteurs."""
    if v1 is None or v2 is None:
        return 0.0
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def _compute_embedding_bonus(similarity: float) -> float:
    """Calcule le bonus embedding proportionnel."""
    if similarity >= 0.85:
        return 0.3
    if similarity < 0.60:
        return 0.0
    # Proportionnel entre 0.60 et 0.85
    return 0.3 * (similarity - 0.60) / (0.85 - 0.60)


# ── API compatible v1 ─────────────────────────────────────────────────

def map_to_dimension(
    candidate_key: str,
    candidate_question: str,
    value_type: str,
    operator: str,
    registry: List[QuestionDimension],
) -> Tuple[Optional[str], float]:
    """
    API v1 compatible — match déterministe uniquement (pas d'embedding).

    Returns:
        (dimension_id, match_score) si match trouvé (score >= 0.7)
        (None, 0.0) si aucun match
    """
    if not registry:
        return (None, 0.0)

    candidate_key_norm = candidate_key.lower().strip()

    best_match: Optional[str] = None
    best_score: float = 0.0

    for dim in registry:
        if dim.status == "merged":
            continue

        dim_key_norm = dim.dimension_key.lower().strip()

        if dim.value_type != value_type:
            continue
        if _is_operator_inversion(operator, dim.allowed_operators):
            continue
        if _is_semantic_inversion(candidate_key_norm, dim_key_norm):
            continue

        score = 0.0
        if candidate_key_norm == dim_key_norm:
            score = 1.0
        else:
            prefix_ratio = _common_prefix_ratio(candidate_key_norm, dim_key_norm)
            if prefix_ratio >= 0.6:
                score = 0.8

        if score > best_score:
            best_score = score
            best_match = dim.dimension_id

    if best_score >= 0.7 and best_match:
        return (best_match, best_score)

    return (None, 0.0)


def _is_operator_inversion(operator: str, allowed_operators: List[str]) -> bool:
    """Vérifie si l'opérateur est une inversion des opérateurs autorisés."""
    inversions = {
        ">=": "<=",
        "<=": ">=",
        ">": "<",
        "<": ">",
    }
    inverted = inversions.get(operator)
    if inverted and inverted in allowed_operators and operator not in allowed_operators:
        return True
    return False


def _is_semantic_inversion(key_a: str, key_b: str) -> bool:
    """Détecte les inversions sémantiques (min/max, enabled/disabled, etc.)."""
    for pattern_a, pattern_b in _INVERSION_PAIRS:
        a_has_first = bool(re.search(pattern_a, key_a))
        a_has_second = bool(re.search(pattern_b, key_a))
        b_has_first = bool(re.search(pattern_a, key_b))
        b_has_second = bool(re.search(pattern_b, key_b))

        if (a_has_first and b_has_second) or (a_has_second and b_has_first):
            return True

    return False


def _common_prefix_ratio(a: str, b: str) -> float:
    """Calcule le ratio de préfixe commun entre deux strings."""
    if not a or not b:
        return 0.0
    max_len = max(len(a), len(b))
    common = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            common += 1
        else:
            break
    return common / max_len


__all__ = [
    "map_to_dimension",
    "DimensionMapperV2",
    "MatchTrace",
    "_cosine_similarity",
    "_compute_embedding_bonus",
]
