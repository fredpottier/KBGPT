# src/knowbase/claimfirst/quality/evidence_rewriter.py
"""
Réécriture evidence-locked pour la gray zone de vérifiabilité.

Pour les claims avec cos(text, verbatim) ∈ [0.80, 0.88] :
le LLM reformule la claim à partir du verbatim uniquement.

Le LLM peut répondre ABSTAIN si le verbatim n'est pas claimable
(navigation, titres, "for more information...").

V1.3: Quality gates pipeline (INV-26).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, TYPE_CHECKING

from knowbase.claimfirst.quality.quality_action import QualityAction, QualityVerdict

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim
    from knowbase.claimfirst.quality.embedding_scorer import EmbeddingScorer

logger = logging.getLogger(__name__)


def _load_quality_prompt(key: str) -> Optional[dict]:
    """Charge un prompt quality_gates depuis config/prompts.yaml."""
    try:
        from knowbase.config.prompts_loader import DEFAULT_PROMPTS_PATH
        import yaml
        with open(DEFAULT_PROMPTS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("quality_gates", {}).get(key)
    except Exception:
        return None


# Seuils calibrés empiriquement (embeddings multilingual-e5-large)
VERIF_THRESHOLD_REJECT = 0.80
VERIF_THRESHOLD_GRAY = 0.88
REWRITE_POST_CHECK = 0.88  # Post-check strict après réécriture


class EvidenceRewriter:
    """Reformule les claims à partir du verbatim (evidence-locked)."""

    MAX_CONCURRENT = 5

    def __init__(self):
        self._stats = {
            "rewritten": 0,
            "abstained": 0,
            "post_check_failed": 0,
        }

    async def rewrite_batch(
        self,
        claims: List["Claim"],
        verif_scores: Dict[str, float],
        embedding_scorer: "EmbeddingScorer",
    ) -> List[QualityVerdict]:
        """
        Reformule un batch de claims dans la gray zone via vLLM.

        Args:
            claims: Claims à réécrire (déjà filtrées dans la gray zone)
            verif_scores: Scores de vérifiabilité pré-calculés
            embedding_scorer: Scorer pour le post-check

        Returns:
            Liste de QualityVerdict (un par claim)
        """
        if not claims:
            return []

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        verdicts: List[Optional[QualityVerdict]] = [None] * len(claims)

        async def _process_one(idx: int, claim: "Claim"):
            async with semaphore:
                verdict = await self._rewrite_single(
                    claim, verif_scores, embedding_scorer,
                )
                verdicts[idx] = verdict

        tasks = [_process_one(i, c) for i, c in enumerate(claims)]
        await asyncio.gather(*tasks)

        return [v for v in verdicts if v is not None]

    async def _rewrite_single(
        self,
        claim: "Claim",
        verif_scores: Dict[str, float],
        embedding_scorer: "EmbeddingScorer",
    ) -> QualityVerdict:
        """Réécrit une claim unique via LLM."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        verif_score = verif_scores.get(claim.claim_id, 0.0)

        # Charger le prompt depuis prompts.yaml
        prompt = self._build_prompt(claim.verbatim_quote)

        router = get_llm_router()
        try:
            response = router.complete(
                task_type=TaskType.SHORT_ENRICHMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )
        except Exception as e:
            logger.warning(
                f"[OSMOSE:EvidenceRewriter] LLM call failed for {claim.claim_id}: {e}"
            )
            # En cas d'erreur LLM, on garde la claim telle quelle
            return QualityVerdict(
                action=QualityAction.PASS,
                scores={"verif_score": verif_score},
                detail=f"LLM rewrite failed, kept as-is: {e}",
            )

        rewritten = response.strip()

        # ABSTAIN → BUCKET_NOT_CLAIMABLE
        if rewritten.upper().startswith("ABSTAIN"):
            self._stats["abstained"] += 1
            return QualityVerdict(
                action=QualityAction.BUCKET_NOT_CLAIMABLE,
                scores={"verif_score": verif_score},
                detail="LLM abstained: verbatim not claimable",
            )

        # Post-check: cos(rewritten, verbatim) >= REWRITE_POST_CHECK
        post_scores = embedding_scorer.score_verifiability_pair(
            rewritten, claim.verbatim_quote,
        )
        post_sim = post_scores if isinstance(post_scores, float) else 0.0

        if post_sim < REWRITE_POST_CHECK:
            self._stats["post_check_failed"] += 1
            return QualityVerdict(
                action=QualityAction.REJECT_FABRICATION,
                scores={
                    "verif_score": verif_score,
                    "rewrite_post_check": post_sim,
                },
                detail=(
                    f"Post-check failed: cos(rewritten, verbatim)="
                    f"{post_sim:.3f} < {REWRITE_POST_CHECK}"
                ),
            )

        # Réécriture réussie
        self._stats["rewritten"] += 1
        return QualityVerdict(
            action=QualityAction.REWRITE_EVIDENCE_LOCKED,
            scores={
                "verif_score": verif_score,
                "rewrite_post_check": post_sim,
            },
            detail=f"Rewritten from gray zone verif={verif_score:.3f}",
            rewritten_text=rewritten,
        )

    def _build_prompt(self, verbatim: str) -> str:
        """Construit le prompt pour la réécriture evidence-locked."""
        try:
            prompt_config = _load_quality_prompt("evidence_rewriter")
            if prompt_config:
                system = prompt_config.get("system", "")
                user_template = prompt_config.get("user", "")
                return f"{system}\n\n{user_template.format(verbatim=verbatim)}"
        except Exception:
            pass

        # Fallback prompt
        return (
            "You are a technical documentation analyst. "
            "Rewrite the following verbatim excerpt as a single, precise, "
            "self-contained factual claim. Use ONLY information present in the verbatim. "
            "Do NOT add any interpretation or external knowledge.\n\n"
            "If the verbatim is not a claimable statement (navigation, heading, "
            "boilerplate, 'for more information see...'), respond with exactly: ABSTAIN\n\n"
            f"Verbatim:\n\"\"\"\n{verbatim}\n\"\"\"\n\n"
            "Rewritten claim:"
        )

    def get_stats(self) -> dict:
        return dict(self._stats)


__all__ = [
    "EvidenceRewriter",
    "VERIF_THRESHOLD_REJECT",
    "VERIF_THRESHOLD_GRAY",
    "REWRITE_POST_CHECK",
]
