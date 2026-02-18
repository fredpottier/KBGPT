# src/knowbase/claimfirst/quality/independence_resolver.py
"""
Résolution d'anaphores par entity anchoring + vLLM.

Phase 1 (déterministe): Vérifier si les entités extraites pour la claim
incluent un sujet explicite dans le texte (cos > 0.86).

Phase 2 (vLLM): Pour les claims détectées comme anaphoriques,
le LLM résout en utilisant le passage.

Trigger robuste: (0 entité liée avec cos > τ) ET (verif_score > 0.88)
pour exclure les claims dont le problème est la fidélité (pas l'indépendance).

V1.3: Quality gates pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, List, Optional, TYPE_CHECKING

from knowbase.claimfirst.quality.quality_action import QualityAction, QualityVerdict

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim
    from knowbase.claimfirst.models.passage import Passage
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


ENTITY_IN_TEXT_THRESHOLD = 0.86
VERIF_SCORE_MINIMUM = 0.88  # Claims avec verif bas → pas un problème d'indépendance


class IndependenceResolver:
    """Résout les anaphores par entity anchoring + vLLM (language-agnostic)."""

    MAX_CONCURRENT = 5

    def __init__(self):
        self._stats = {
            "resolved": 0,
            "bucketed": 0,
            "skipped": 0,
        }

    def _is_entity_in_text(
        self,
        entity_name: str,
        claim_text: str,
        embedding_scorer: "EmbeddingScorer",
    ) -> bool:
        """
        Vérifie par embedding si l'entité est mentionnée dans le texte.

        cos(φ(entity_name), φ(claim_text)) > 0.86
        Robuste aux acronymes/synonymes.
        """
        sim = embedding_scorer.score_verifiability_pair(entity_name, claim_text)
        return sim > ENTITY_IN_TEXT_THRESHOLD

    def _should_resolve(
        self,
        claim: "Claim",
        entity_names: List[str],
        verif_score: float,
        embedding_scorer: "EmbeddingScorer",
    ) -> bool:
        """
        Trigger robuste pour la résolution d'indépendance.

        Conditions:
        1. 0 entité liée avec cos > ENTITY_IN_TEXT_THRESHOLD
        2. verif_score > VERIF_SCORE_MINIMUM (exclut problèmes de fidélité)
        """
        if verif_score <= VERIF_SCORE_MINIMUM:
            return False

        if not entity_names:
            return True

        for entity_name in entity_names:
            if self._is_entity_in_text(entity_name, claim.text, embedding_scorer):
                return False

        return True

    async def resolve_batch(
        self,
        claims: List["Claim"],
        claim_entity_map: Dict[str, List[str]],
        passages: List["Passage"],
        verif_scores: Dict[str, float],
        embedding_scorer: "EmbeddingScorer",
    ) -> List[QualityVerdict]:
        """
        Résout les anaphores par entity anchoring + vLLM.

        1. Filtre: claims dont AUCUNE entity cos > 0.86 ET verif > 0.88
        2. vLLM: reformule avec le sujet explicite
        3. Si échec → BUCKET_LOW_INDEPENDENCE

        Args:
            claims: Claims à vérifier
            claim_entity_map: Dict claim_id → [entity_names]
            passages: Passages du document (pour contexte)
            verif_scores: Scores de vérifiabilité (du gate runner)
            embedding_scorer: Scorer pour le calcul entity-in-text

        Returns:
            Liste de QualityVerdict pour les claims résolues
        """
        if not claims:
            return []

        # Index des passages par passage_id
        passage_map = {p.passage_id: p for p in passages}

        # Identifier les claims à résoudre
        to_resolve = []
        for claim in claims:
            entity_names = claim_entity_map.get(claim.claim_id, [])
            verif = verif_scores.get(claim.claim_id, 0.0)
            if self._should_resolve(claim, entity_names, verif, embedding_scorer):
                to_resolve.append(claim)
            else:
                self._stats["skipped"] += 1

        if not to_resolve:
            return []

        logger.info(
            f"[OSMOSE:IndependenceResolver] {len(to_resolve)} claims to resolve"
        )

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        verdicts: List[Optional[QualityVerdict]] = [None] * len(to_resolve)

        async def _process_one(idx: int, claim: "Claim"):
            async with semaphore:
                passage = passage_map.get(claim.passage_id)
                passage_text = passage.text if passage else ""
                verdict = await self._resolve_single(claim, passage_text)
                verdicts[idx] = verdict

        tasks = [_process_one(i, c) for i, c in enumerate(to_resolve)]
        await asyncio.gather(*tasks)

        return [v for v in verdicts if v is not None]

    async def _resolve_single(
        self,
        claim: "Claim",
        passage_text: str,
    ) -> QualityVerdict:
        """Résout une claim unique via LLM."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        prompt = self._build_prompt(claim.text, passage_text)

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
                f"[OSMOSE:IndependenceResolver] LLM call failed for {claim.claim_id}: {e}"
            )
            self._stats["bucketed"] += 1
            return QualityVerdict(
                action=QualityAction.BUCKET_LOW_INDEPENDENCE,
                scores={},
                detail=f"LLM resolution failed: {e}",
            )

        resolved = response.strip()

        # Nettoyer les préfixes LLM courants
        resolved = re.sub(
            r'^(?:Resolved|Rewritten)\s*(?:claim)?[:\s]*',
            '', resolved, flags=re.IGNORECASE,
        ).strip().strip('"').strip()

        # UNCHANGED → pas d'anaphore détectée, garder tel quel
        if resolved.upper().startswith("UNCHANGED"):
            self._stats["skipped"] += 1
            return QualityVerdict(
                action=QualityAction.PASS,
                scores={},
                detail="LLM detected no anaphora, kept as-is",
            )

        # Vérifier que la résolution est valide (longueur minimale)
        if len(resolved) < 10:
            self._stats["bucketed"] += 1
            return QualityVerdict(
                action=QualityAction.BUCKET_LOW_INDEPENDENCE,
                scores={},
                detail=f"Resolution too short ({len(resolved)} chars)",
            )

        self._stats["resolved"] += 1
        return QualityVerdict(
            action=QualityAction.RESOLVE_INDEPENDENCE,
            scores={},
            detail="Anaphora resolved with explicit subject",
            resolved_text=resolved,
        )

    def _build_prompt(self, claim_text: str, passage_text: str) -> str:
        """Construit le prompt pour la résolution d'indépendance."""
        try:
            prompt_config = _load_quality_prompt("independence_resolver")
            if prompt_config:
                system = prompt_config.get("system", "")
                user_template = prompt_config.get("user", "")
                user_filled = user_template.format(
                    claim_text=claim_text,
                    passage_text=passage_text[:500],
                )
                return f"{system}\n\n{user_filled}"
        except Exception:
            pass

        # Fallback prompt
        return (
            "You are a technical documentation analyst. "
            "The following claim may contain anaphoric references (pronouns like "
            "'it', 'they', 'this', 'these') that make it incomprehensible "
            "without its source passage.\n\n"
            "Your task: If the claim contains anaphoric references, rewrite it by "
            "replacing pronouns with their explicit referents from the passage. "
            "If the claim is already self-contained, respond with: UNCHANGED\n\n"
            f"Source passage:\n\"\"\"\n{passage_text[:500]}\n\"\"\"\n\n"
            f"Claim:\n\"\"\"\n{claim_text}\n\"\"\"\n\n"
            "Rewritten claim (or UNCHANGED):"
        )

    def get_stats(self) -> dict:
        return dict(self._stats)


__all__ = [
    "IndependenceResolver",
    "ENTITY_IN_TEXT_THRESHOLD",
    "VERIF_SCORE_MINIMUM",
]
