# src/knowbase/claimfirst/quality/atomicity_splitter.py
"""
Split des claims non-atomiques via vLLM.

Claims >160 chars avec ≥3 clauses → splittées en 2-4 claims atomiques.
Comptage de clauses par ponctuation universelle (language-agnostic).

V1.3: Quality gates pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from knowbase.claimfirst.quality.quality_action import QualityAction, QualityVerdict

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim

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


ATOMICITY_CHAR_THRESHOLD = 160


class AtomicitySplitter:
    """Split les claims >160 chars en claims atomiques via vLLM."""

    MAX_CONCURRENT = 5

    def __init__(self):
        self._stats = {
            "claims_split": 0,
            "sub_claims_created": 0,
            "claims_kept": 0,
        }

    @staticmethod
    def _count_clauses(text: str) -> int:
        """
        Compte les clauses via ponctuation universelle (language-agnostic).

        Split sur virgule, point-virgule, deux-points, point,
        parenthèses, et bullet-like patterns.
        """
        separators = re.split(r'[,;:.]|\(|\)|^\s*[-•*]\s', text)
        return len([s for s in separators if len(s.strip()) > 10])

    @staticmethod
    def should_split(claim: "Claim") -> bool:
        """Vérifie si une claim doit être splittée."""
        text = claim.text
        return (
            len(text) > ATOMICITY_CHAR_THRESHOLD
            and AtomicitySplitter._count_clauses(text) >= 3
        )

    async def split_batch(
        self,
        claims: List["Claim"],
    ) -> Tuple[List["Claim"], List[QualityVerdict]]:
        """
        Split chaque claim longue en 2-4 claims atomiques.

        Args:
            claims: Claims candidates au split

        Returns:
            Tuple[claims résultantes (originale remplacée par sub-claims), verdicts]
        """
        to_split = [c for c in claims if self.should_split(c)]
        to_keep = [c for c in claims if not self.should_split(c)]

        if not to_split:
            return claims, []

        logger.info(
            f"[OSMOSE:AtomicitySplitter] {len(to_split)} claims to split "
            f"(>{ATOMICITY_CHAR_THRESHOLD} chars, ≥3 clauses)"
        )

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        results: List[Tuple[Optional["Claim"], List["Claim"], QualityVerdict]] = [
            (None, [], QualityVerdict(action=QualityAction.PASS, scores={}))
        ] * len(to_split)

        async def _process_one(idx: int, claim: "Claim"):
            async with semaphore:
                parent, sub_claims, verdict = await self._split_single(claim)
                results[idx] = (parent, sub_claims, verdict)

        tasks = [_process_one(i, c) for i, c in enumerate(to_split)]
        await asyncio.gather(*tasks)

        # Assembler le résultat
        verdicts = []
        output_claims = list(to_keep)
        for parent, sub_claims, verdict in results:
            verdicts.append(verdict)
            if sub_claims and len(sub_claims) > 1:
                # Split réussi → ajouter sub-claims, retirer parente
                output_claims.extend(sub_claims)
                self._stats["claims_split"] += 1
                self._stats["sub_claims_created"] += len(sub_claims)
            elif parent:
                # Pas de split (LLM a retourné 1 seule claim) → garder originale
                output_claims.append(parent)
                self._stats["claims_kept"] += 1

        return output_claims, verdicts

    async def _split_single(
        self,
        claim: "Claim",
    ) -> Tuple["Claim", List["Claim"], QualityVerdict]:
        """Split une claim unique via LLM."""
        from knowbase.common.llm_router import get_llm_router, TaskType
        from knowbase.claimfirst.models.claim import Claim, ClaimScope

        prompt = self._build_prompt(claim.text)

        router = get_llm_router()
        try:
            response = router.complete(
                task_type=TaskType.SHORT_ENRICHMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
        except Exception as e:
            logger.warning(
                f"[OSMOSE:AtomicitySplitter] LLM call failed for {claim.claim_id}: {e}"
            )
            return claim, [], QualityVerdict(
                action=QualityAction.PASS,
                scores={"char_count": len(claim.text)},
                detail=f"LLM split failed, kept as-is: {e}",
            )

        # Parser la réponse
        sub_texts = self._parse_response(response)

        if len(sub_texts) <= 1:
            # LLM n'a pas splité → claim atomique malgré sa longueur
            return claim, [], QualityVerdict(
                action=QualityAction.PASS,
                scores={"char_count": len(claim.text), "clauses": self._count_clauses(claim.text)},
                detail="LLM returned 1 claim, no split needed",
            )

        # Créer les sub-claims
        sub_claims = []
        suffixes = ["_a", "_b", "_c", "_d"]
        for i, sub_text in enumerate(sub_texts[:4]):
            suffix = suffixes[i] if i < len(suffixes) else f"_{i}"
            sub_claim = Claim(
                claim_id=f"{claim.claim_id}{suffix}",
                tenant_id=claim.tenant_id,
                doc_id=claim.doc_id,
                text=sub_text,
                claim_type=claim.claim_type,
                scope=claim.scope,
                verbatim_quote=claim.verbatim_quote,
                passage_id=claim.passage_id,
                unit_ids=claim.unit_ids,
                confidence=claim.confidence,
                language=claim.language,
            )
            sub_claims.append(sub_claim)

        verdict = QualityVerdict(
            action=QualityAction.SPLIT_ATOMICITY,
            scores={
                "char_count": len(claim.text),
                "clauses": self._count_clauses(claim.text),
                "sub_claims_count": len(sub_claims),
            },
            detail=f"Split into {len(sub_claims)} atomic claims",
            split_claims=[sc.text for sc in sub_claims],
        )

        return claim, sub_claims, verdict

    def _parse_response(self, response: str) -> List[str]:
        """Parse la réponse LLM (JSON array ou lignes numérotées).

        Gère les patterns Qwen3 où du raisonnement est ajouté après la réponse.
        """
        raw = response.strip()

        # Couper tout après un marqueur de raisonnement LLM
        cleaned = re.split(
            r'\n\s*\*{0,2}\s*(?:Reasoning|Explanation|Note|Analysis|Response|Comment)[:\s*]',
            raw, maxsplit=1, flags=re.IGNORECASE,
        )[0].strip()

        # Essayer JSON array — extraire le premier [...] trouvé
        json_match = re.search(r'\[.*\]', cleaned, flags=re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except (json.JSONDecodeError, TypeError):
                pass

        # Essayer lignes numérotées (1. ..., 2. ..., etc.)
        lines = cleaned.split("\n")
        claims = []
        for line in lines:
            line = line.strip()
            # Retirer le numéro en début de ligne
            line_cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
            # Retirer tirets/bullets
            line_cleaned = re.sub(r'^[-•*]\s*', '', line_cleaned)
            if line_cleaned and len(line_cleaned) >= 10:
                # Retirer guillemets encadrants
                line_cleaned = re.sub(r'^["\']+|["\']+$', '', line_cleaned).strip()
                claims.append(line_cleaned)

        if claims:
            return claims

        # Fallback: retourner le texte entier comme une seule claim
        if cleaned and len(cleaned) >= 10:
            return [cleaned]

        return []

    def _build_prompt(self, claim_text: str) -> str:
        """Construit le prompt pour le split d'atomicité."""
        try:
            prompt_config = _load_quality_prompt("atomicity_splitter")
            if prompt_config:
                system = prompt_config.get("system", "")
                user_template = prompt_config.get("user", "")
                return f"{system}\n\n{user_template.format(claim_text=claim_text)}"
        except Exception:
            pass

        # Fallback prompt
        return (
            "You are a technical documentation analyst. "
            "Split the following compound claim into 2-4 atomic claims. "
            "Each atomic claim must:\n"
            "- State exactly ONE factual assertion\n"
            "- Be self-contained and understandable independently\n"
            "- Preserve the original meaning without adding information\n\n"
            "If the claim is already atomic (states only one thing), "
            "return it unchanged as a single-element list.\n\n"
            "Return a JSON array of strings.\n\n"
            f"Compound claim:\n\"\"\"\n{claim_text}\n\"\"\"\n\n"
            "Atomic claims (JSON array):"
        )

    def get_stats(self) -> dict:
        return dict(self._stats)


__all__ = [
    "AtomicitySplitter",
    "ATOMICITY_CHAR_THRESHOLD",
]
