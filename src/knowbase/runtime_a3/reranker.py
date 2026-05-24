"""Cross-encoder reranker runtime — Phase B P2.2 (23/05/2026).

Pattern littérature 2026 (P2 du diagnostic ETAT_ART_KG_RAG_2026) :
le cross-encoder voit `(query, claim_text)` ensemble et produit un score plus
précis qu'un bi-encoder cosinus séparé. Gain documenté +5-15 NDCG@10 sur BEIR/MTEB.

Pipeline cible :
    Execute RRF top-50 → reranker.rerank(question, claims, top_k=5) → Synthesize

Modèle par défaut : BAAI/bge-reranker-v2-m3 (278M params, multilingue FR/EN/DE/ZH/100+).
Score reporté 51.8 nDCG@10 sur BEIR.

Toggle env : `V6_CROSS_ENCODER_RERANK=1` (défaut OFF tant que validé).
Modèle env : `V6_CE_RERANK_MODEL` (défaut BAAI/bge-reranker-v2-m3).

Domain-agnostic strict : aucun token corpus-spécifique, fonctionne identiquement
sur médical / réglementaire / juridique / aerospace.
"""

from __future__ import annotations

import logging
import os
import time
from typing import List, Optional, Tuple

from knowbase.runtime_a3.schemas import ClaimSummary

logger = logging.getLogger("knowbase.runtime_a3.reranker")


DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_TOP_K = 5
DEFAULT_BATCH_SIZE = 16


def _claim_text_for_rerank(claim: ClaimSummary) -> str:
    """Texte d'entrée pour le cross-encoder.

    Privilégie le verbatim text si disponible (plus riche), sinon reconstruit
    depuis subject+predicate+value. Limite 512 tokens approximatifs (cap 2000 chars).
    """
    # Pydantic extra="allow" → ClaimSummary peut porter des champs additionnels
    extras = claim.model_dump() if hasattr(claim, "model_dump") else {}
    for key in ("text", "claim_text_full", "verbatim_quote", "passage_text"):
        val = extras.get(key)
        if val and isinstance(val, str) and val.strip():
            text = val.strip()
            return text[:2000] if len(text) > 2000 else text

    # Fallback : reconstruire depuis triplet
    parts: List[str] = []
    if claim.subject_canonical:
        parts.append(claim.subject_canonical)
    if claim.predicate:
        parts.append(claim.predicate.replace("_", " ").lower())
    val = claim.value or claim.value_normalized
    if val:
        parts.append(str(val))
    return " ".join(parts).strip()


class ClaimReranker:
    """Cross-encoder reranker pour ClaimSummary (Phase B P2.2).

    Wrapping de `knowbase.common.clients.reranker.get_cross_encoder` (cache LRU
    singleton) avec interface adaptée aux ClaimSummary du runtime_v6.

    Args:
        model_name: HuggingFace model id (défaut BAAI/bge-reranker-v2-m3)
        device: "cpu" | "cuda" | None (auto)
        batch_size: taille batch predict (défaut 16)
        top_k: nombre de claims à retourner (défaut 5)
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        top_k: int = DEFAULT_TOP_K,
    ):
        self._model_name = model_name or os.getenv("V6_CE_RERANK_MODEL", DEFAULT_MODEL)
        self._device = device
        self._batch_size = batch_size
        self._top_k = top_k
        self._model = None  # lazy init

    def _get_model(self):
        if self._model is None:
            from knowbase.common.clients.reranker import get_cross_encoder
            t0 = time.perf_counter()
            self._model = get_cross_encoder(
                model_name=self._model_name,
                device=self._device,
            )
            dt = time.perf_counter() - t0
            logger.info(
                "[ClaimReranker] model %s loaded in %.2fs (cached for next calls)",
                self._model_name, dt,
            )
        return self._model

    def rerank(
        self,
        question: str,
        claims: List[ClaimSummary],
        top_k: Optional[int] = None,
    ) -> Tuple[List[ClaimSummary], List[float]]:
        """Rerank les claims par pertinence cross-encoder vs la question.

        Args:
            question: question utilisateur (raw, pas pré-formatée)
            claims: liste de ClaimSummary (typiquement top-50 RRF)
            top_k: nombre à retourner (défaut self._top_k)

        Returns:
            (reranked_claims, scores) : top-K claims triés DESC + scores correspondants

        Comportement défensif :
            - Si claims vide → retourne ([], [])
            - Si question vide → retourne claims[:top_k] sans rerank (passthrough)
            - Si modèle fail → log + raise (caller gère le fallback)
        """
        if not claims:
            return [], []
        if not question or not question.strip():
            k = top_k or self._top_k
            return claims[:k], [0.0] * min(k, len(claims))

        k = top_k or self._top_k
        t0 = time.perf_counter()

        # Préparer pairs (question, claim_text)
        pairs = [(question, _claim_text_for_rerank(c)) for c in claims]
        # Filtrer les pairs avec claim_text vide (peut arriver si claim corrompu)
        valid_pairs_idx = [i for i, (_, ct) in enumerate(pairs) if ct]
        if not valid_pairs_idx:
            logger.warning("[ClaimReranker] no valid claim_text in %d claims, passthrough", len(claims))
            return claims[:k], [0.0] * min(k, len(claims))

        valid_pairs = [pairs[i] for i in valid_pairs_idx]

        # Predict scores (batch)
        try:
            model = self._get_model()
            scores = model.predict(
                valid_pairs,
                batch_size=self._batch_size,
                show_progress_bar=False,
            )
        except Exception:
            logger.exception("[ClaimReranker] predict failed on %d pairs", len(valid_pairs))
            raise

        # Map scores back aux indices originaux
        scored: List[Tuple[int, float]] = []
        for local_i, original_i in enumerate(valid_pairs_idx):
            scored.append((original_i, float(scores[local_i])))

        # Sort DESC + top-K
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = scored[:k]
        kept_claims = [claims[i] for i, _ in kept]
        kept_scores = [s for _, s in kept]

        dt = time.perf_counter() - t0
        logger.info(
            "[ClaimReranker] reranked %d→%d in %.2fs (top_score=%.3f, threshold@%d=%.3f)",
            len(claims), len(kept_claims), dt,
            kept_scores[0] if kept_scores else 0.0,
            k, kept_scores[-1] if kept_scores else 0.0,
        )
        return kept_claims, kept_scores
