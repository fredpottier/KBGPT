"""Claim Filter runtime — score sémantique claim↔question pour Synthesize.

Post-A3.9-bis : le grounding (subject + predicate) est résolu, mais Synthesize
reçoit TOUS les claims du subject (jusqu'à 30) et le LLM en choisit certains
hors-sujet pour la question précise. Ce module pré-filtre les claims par
score sémantique avant qu'ils n'arrivent au prompt LLM.

Pipeline :
    1. Concaténer chaque claim en "{subject} {predicate} {value}" (string lisible).
    2. Encoder la question + chaque claim_text via Sentence Transformer (batch).
    3. Cosine similarity entre la question et chaque claim.
    4. Garder top-K claims avec score >= MIN_SCORE.
    5. Si filtre vide → renvoyer top-1 quand même (graceful fallback : on garde
       au moins 1 claim pour que Synthesize puisse produire une réponse).

Charte stricte : aucun token corpus-spécifique, scoring purement sémantique.

Toggle env var : `V6_CLAIM_FILTER_ENABLED` (default "1").
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from knowbase.runtime_a3.schemas import (
    ClaimFilterResult,
    ClaimSummary,
    ScoredClaim,
)

logger = logging.getLogger("knowbase.runtime_a3.claim_filter")


# Constants
# MIN_SCORE calibré sur ms-marco-style relevance (sentence-transformers e5-large)
# cosine similarity. Score [0.5, 0.7] = relevance plausible, [0.7+] = fort.
# Seuil 0.55 = conservateur (laisse passer relevance faible mais filtre noise).
# MIN_SCORE et TOP_K calibrés sur smoke Q "options connectivite Azure RISE" :
# top-1 ExpressRoute=0.91, last skeleton=0.85. Scores serrés (e5-large encodings
# claim_text courts). On vise top-K dur pour réduire le bruit envoyé au LLM
# Synthesize plutôt que de compter sur le seuil.
MIN_SCORE = 0.55
TOP_K_DEFAULT = 5  # max claims envoyés à Synthesize après filtrage
MIN_KEPT = 1        # garde toujours au moins 1 claim (graceful fallback)


def _claim_text(claim: ClaimSummary) -> str:
    """Concat subject + predicate + value en string lisible pour embedding."""
    parts: List[str] = []
    if claim.subject_canonical:
        parts.append(claim.subject_canonical)
    if claim.predicate:
        # UPPER_SNAKE → "lower words" pour matcher la question naturelle
        parts.append(claim.predicate.replace("_", " ").lower())
    val = claim.value or claim.value_normalized
    if val:
        parts.append(str(val))
    return " ".join(parts).strip()


class ClaimFilter:
    """Filtre les claims par score sémantique vs la question.

    Injection de dépendances :
        - `embedder` : callable `(texts: List[str]) -> List[List[float]]` (batch)
    """

    def __init__(
        self,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        min_score: float = MIN_SCORE,
        top_k: int = TOP_K_DEFAULT,
        min_kept: int = MIN_KEPT,
    ):
        self._embedder = embedder
        self._min_score = min_score
        self._top_k = top_k
        self._min_kept = min_kept

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda texts: [v.tolist() for v in mgr.encode(texts)]
        return self._embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter(
        self,
        question: str,
        claims: List[ClaimSummary],
        groups: Optional[List[int]] = None,
    ) -> Tuple[List[ClaimSummary], ClaimFilterResult]:
        """Filtre les claims par pertinence sémantique vs la question.

        Args:
            question : la question utilisateur
            claims : liste de claims à filtrer
            groups : liste parallèle d'IDs de groupe (typiquement sub_goal_idx).
                Si fourni, applique top-K **par groupe** (préserve la diversité
                pour les comparaisons et list_enumeration multi-sub_goal).
                Si None, top-K global.

        Returns:
            (kept_claims, ClaimFilterResult)
            - kept_claims : sous-liste, ordre = score DESC (ou intra-groupe DESC)
            - ClaimFilterResult : trace observability
        """
        t0 = time.perf_counter()
        n_in = len(claims)

        if groups is not None and len(groups) != len(claims):
            raise ValueError(
                f"groups length ({len(groups)}) must match claims length ({len(claims)})"
            )

        if not question or not question.strip() or not claims:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="passthrough",
                duration_s=time.perf_counter() - t0,
            )

        # Préparer les textes
        claim_texts = [_claim_text(c) for c in claims]
        # Filtrer les claims sans texte (rare mais on garde l'index)
        valid_indices = [i for i, t in enumerate(claim_texts) if t]
        if not valid_indices:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="no_claim_text",
                duration_s=time.perf_counter() - t0,
            )

        try:
            # Batch encode : question + tous claim_texts en 1 appel
            all_texts = [question] + [claim_texts[i] for i in valid_indices]
            embeddings = self._get_embedder()(all_texts)
        except Exception:
            logger.exception("claim_filter: embedder failed, passthrough")
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="embedder_error",
                duration_s=time.perf_counter() - t0,
            )

        q_vec = embeddings[0]
        claim_vecs = embeddings[1:]

        # Cosine similarity
        scored: List[Tuple[int, float]] = []
        q_norm = sum(x * x for x in q_vec) ** 0.5
        if q_norm == 0:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="zero_query_norm",
                duration_s=time.perf_counter() - t0,
            )

        for local_i, vec in enumerate(claim_vecs):
            c_norm = sum(x * x for x in vec) ** 0.5
            if c_norm == 0:
                continue
            dot = sum(a * b for a, b in zip(q_vec, vec))
            sim = max(0.0, min(1.0, dot / (q_norm * c_norm)))
            original_idx = valid_indices[local_i]
            scored.append((original_idx, sim))

        if not scored:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="no_valid_vec",
                duration_s=time.perf_counter() - t0,
            )

        # Sort DESC par score
        scored.sort(key=lambda t: t[1], reverse=True)

        # Sélection : top-K avec score >= MIN_SCORE, mais au moins MIN_KEPT.
        # Si `groups` fourni, top-K est appliqué PAR groupe (stratification).
        if groups is None:
            kept_with_threshold = [(i, s) for i, s in scored if s >= self._min_score]
            if len(kept_with_threshold) < self._min_kept:
                kept_indices_scores = scored[: self._min_kept]
            else:
                kept_indices_scores = kept_with_threshold[: self._top_k]
        else:
            # Stratification par groupe : top-K par groupe distinct
            kept_per_group: Dict[int, List[Tuple[int, float]]] = {}
            for idx, sim in scored:
                g = groups[idx]
                if g not in kept_per_group:
                    kept_per_group[g] = []
                # On limite top-K par groupe, en respectant le seuil (sauf min_kept)
                if sim >= self._min_score or len(kept_per_group[g]) < self._min_kept:
                    if len(kept_per_group[g]) < self._top_k:
                        kept_per_group[g].append((idx, sim))
            # Flat back to a list, intra-group DESC déjà respecté (scored est DESC)
            kept_indices_scores = []
            for g_items in kept_per_group.values():
                kept_indices_scores.extend(g_items)
            # Tri global final DESC pour cohérence
            kept_indices_scores.sort(key=lambda t: t[1], reverse=True)

        kept_set = {i for i, _ in kept_indices_scores}

        # Ordre kept : par score DESC
        kept_claims: List[ClaimSummary] = []
        for idx, _ in kept_indices_scores:
            kept_claims.append(claims[idx])

        # Trace : tous claims scorés (kept + filtered)
        scored_results: List[ScoredClaim] = []
        for idx, sim in scored:
            scored_results.append(ScoredClaim(
                claim_id=claims[idx].claim_id or f"idx_{idx}",
                score=sim,
                kept=(idx in kept_set),
            ))

        result = ClaimFilterResult(
            scored=scored_results,
            n_input=n_in,
            n_kept=len(kept_claims),
            method="embedding_cosine",
            duration_s=time.perf_counter() - t0,
        )

        if logger.isEnabledFor(logging.INFO):
            kept_preview = [
                f"{claims[i].claim_id}({s:.2f})"
                for i, s in kept_indices_scores[:5]
            ]
            logger.info(
                "claim_filter: %d→%d kept (top-5: %s) in %.2fs",
                n_in, len(kept_claims), kept_preview, result.duration_s,
            )

        return kept_claims, result


# ============================================================================
# Top-level API
# ============================================================================


def filter_claims(
    question: str,
    claims: List[ClaimSummary],
    filter_obj: Optional[ClaimFilter] = None,
) -> Tuple[List[ClaimSummary], ClaimFilterResult]:
    """API top-level."""
    f = filter_obj or ClaimFilter()
    return f.filter(question, claims)
