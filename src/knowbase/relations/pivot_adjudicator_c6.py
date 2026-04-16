"""
C6 PivotAdjudicator — Adjudication des paires pivot via LLM.

Stage 2 du pipeline C6 Cross-doc Pivots.

Pour chaque paire de claims partageant une entite pivot, determine :
- COMPLEMENTS : les claims apportent des perspectives complementaires sur le meme sujet
- EVOLVES_TO  : un claim est une version plus recente/mise a jour de l'autre
- SPECIALIZES : un claim est un cas particulier de l'autre (general → specifique)
- NONE        : pas de relation significative

Usage :
    from knowbase.relations.pivot_adjudicator_c6 import PivotAdjudicatorC6
    adj = PivotAdjudicatorC6()
    results = adj.adjudicate_batch(candidate_pairs)
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PivotAdjudicationResult:
    """Resultat de l'adjudication C6 d'une paire de claims."""
    claim_a_id: str
    claim_b_id: str
    relation: str           # COMPLEMENTS | EVOLVES_TO | SPECIALIZES | NONE
    confidence: float
    evidence_a: str
    evidence_b: str
    reasoning: str
    pivot_entity: str
    detection_method: str = "entity_pivot_nli"
    doc_a_title: str = ""
    doc_b_title: str = ""


THRESHOLDS = {
    "COMPLEMENTS": 0.75,
    "EVOLVES_TO": 0.80,
    "SPECIALIZES": 0.75,
}

C6_PROMPT = """You are a cross-document relationship detector for technical documentation.

Two claims from DIFFERENT documents share a common entity: "{pivot}".

Claim A (from "{doc_a}"): "{text_a}"
Claim B (from "{doc_b}"): "{text_b}"

Classify the relationship as EXACTLY one of:
- COMPLEMENTS: The claims provide DIFFERENT but COMPATIBLE information about the same subject. One covers aspects the other doesn't. Together they give a fuller picture.
- EVOLVES_TO: Claim B is a NEWER version or UPDATE of Claim A (or vice versa). The factual content has changed between document versions.
- SPECIALIZES: One claim is a SPECIFIC case or detailed instance of the other's general statement.
- NONE: The claims are unrelated, nearly identical, or already covered by CONTRADICTS/QUALIFIES/REFINES.

CRITICAL RULES:
- Nearly IDENTICAL claims (just minor wording changes) = NONE. Don't flag trivial rephrasing.
- Product rebranding ("SAP Cloud ERP Private Edition" = "SAP S/4HANA Cloud Private Edition") is NOT a relationship — it's the same thing renamed.
- COMPLEMENTS requires genuinely DIFFERENT information (different aspects, features, or perspectives). Not just the same fact from two docs.
- EVOLVES_TO requires a clear factual CHANGE between versions (value changed, feature added/removed, process modified).
- SPECIALIZES requires a clear general-to-specific relationship (e.g., "all systems support X" → "System Y supports X with parameters A, B, C").
- You MUST quote the EXACT phrases from each claim that create the relationship.

Respond ONLY with valid JSON (no markdown):
{{"relation": "COMPLEMENTS|EVOLVES_TO|SPECIALIZES|NONE", "confidence": 0.0, "evidence_a": "exact quote from Claim A", "evidence_b": "exact quote from Claim B", "reasoning": "one sentence why"}}"""


class PivotAdjudicatorC6:
    """Adjudique les paires pivot via LLM NLI."""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers

    def adjudicate_batch(
        self,
        pairs: list,
        on_progress: callable = None,
    ) -> list[PivotAdjudicationResult]:
        """Adjudique un batch de paires pivot en parallele."""
        start = time.time()
        results = []
        done = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._adjudicate_one, pair): pair
                for pair in pairs
            }

            for future in as_completed(futures):
                done += 1
                if on_progress and done % 20 == 0:
                    on_progress(done, len(pairs))

                try:
                    result = future.result()
                    if result and self._passes_threshold(result):
                        pair = futures[future]
                        if self._validate_evidence(result, pair):
                            results.append(result)
                        else:
                            logger.debug(f"[C6:NLI] Evidence validation failed for {result.claim_a_id}")
                except Exception as e:
                    logger.debug(f"[C6:NLI] Adjudication failed: {e}")

        duration = time.time() - start
        by_type = {}
        for r in results:
            by_type[r.relation] = by_type.get(r.relation, 0) + 1

        logger.info(
            f"[C6:NLI] Adjudicated {len(pairs)} pairs in {duration:.1f}s → "
            f"{len(results)} relations found "
            f"({', '.join(f'{k} {v}' for k, v in sorted(by_type.items()))})"
        )

        return results

    def _adjudicate_one(self, pair) -> PivotAdjudicationResult | None:
        """Adjudique une seule paire via LLM."""
        prompt = C6_PROMPT.format(
            pivot=pair.pivot_entity[:60],
            doc_a=pair.claim_a_doc_title[:60],
            text_a=pair.claim_a_text[:500],
            doc_b=pair.claim_b_doc_title[:60],
            text_b=pair.claim_b_text[:500],
        )

        try:
            from knowbase.common.llm_router import get_llm_router, TaskType
            router = get_llm_router()
            text = router.complete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            ).strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)

            return PivotAdjudicationResult(
                claim_a_id=pair.claim_a_id,
                claim_b_id=pair.claim_b_id,
                relation=data.get("relation", "NONE"),
                confidence=float(data.get("confidence", 0)),
                evidence_a=data.get("evidence_a", ""),
                evidence_b=data.get("evidence_b", ""),
                reasoning=data.get("reasoning", ""),
                pivot_entity=pair.pivot_entity,
                detection_method="entity_pivot_nli",
                doc_a_title=pair.claim_a_doc_title,
                doc_b_title=pair.claim_b_doc_title,
            )

        except json.JSONDecodeError as e:
            logger.debug(f"[C6:NLI] JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"[C6:NLI] LLM call failed: {e}")
            return None

    def _passes_threshold(self, result: PivotAdjudicationResult) -> bool:
        """Verifie le seuil de confiance."""
        if result.relation == "NONE":
            return False
        threshold = THRESHOLDS.get(result.relation, 0.80)
        return result.confidence >= threshold

    def _validate_evidence(self, result: PivotAdjudicationResult, pair) -> bool:
        """Verifie que les preuves sont verbatim (INV-PROOF-01)."""
        if not result.evidence_a or not result.evidence_b:
            return False

        text_a = pair.claim_a_text.lower()
        text_b = pair.claim_b_text.lower()
        ev_a = result.evidence_a.lower().strip()
        ev_b = result.evidence_b.lower().strip()

        a_valid = ev_a in text_a or ev_a.rstrip('.') in text_a
        b_valid = ev_b in text_b or ev_b.rstrip('.') in text_b

        return a_valid and b_valid
