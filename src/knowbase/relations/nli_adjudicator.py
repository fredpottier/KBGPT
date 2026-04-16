"""
C4 NLI Adjudicator — Adjudication des paires candidates via LLM.

Stage 2 du pipeline C4 Relations Evidence-First.

Chaque paire candidate est evaluee par Claude Haiku pour determiner :
- Le type de relation (CONTRADICTS, QUALIFIES, REFINES, NONE)
- La confiance (0.0-1.0)
- Les preuves verbatim des deux claims

Usage :
    from knowbase.relations.nli_adjudicator import NLIAdjudicator
    adj = NLIAdjudicator()
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
class AdjudicationResult:
    """Resultat de l'adjudication NLI d'une paire de claims."""
    claim_a_id: str
    claim_b_id: str
    relation: str           # CONTRADICTS | QUALIFIES | REFINES | NONE
    confidence: float
    evidence_a: str          # verbatim span from claim A
    evidence_b: str          # verbatim span from claim B
    reasoning: str
    detection_method: str    # "embedding_nli"
    doc_a_title: str = ""
    doc_b_title: str = ""


# Seuils asymetriques — faux positif pire que faux negatif
THRESHOLDS = {
    "CONTRADICTS": 0.85,
    "QUALIFIES": 0.75,
    "REFINES": 0.75,
}

NLI_PROMPT = """You are a factual relation detector for technical documentation.

Given two claims from DIFFERENT documents, determine their logical relationship.

Claim A (from "{doc_a}"): "{text_a}"
Claim B (from "{doc_b}"): "{text_b}"

Classify the relationship as EXACTLY one of:
- CONTRADICTS: The claims make INCOMPATIBLE factual assertions about the SAME subject in the SAME context.
- QUALIFIES: One claim adds conditions, exceptions, or scope limitations to the other.
- REFINES: One claim provides more specific detail about the same assertion.
- NONE: The claims are unrelated, merely similar, or compatible.

CRITICAL RULES:
- Similar topics WITHOUT incompatible assertions = NONE (not CONTRADICTS).
- Version/edition differences alone are NOT contradictions. "X in version 2023" vs "Y in version 2025" is an EVOLUTION, not a contradiction.
- CONTRADICTS requires truly INCOMPATIBLE assertions about the SAME thing in the SAME context.
- Two DIFFERENT modules/features/components that share the same capability are NOT contradictions. "Module A has feature X" and "Module B has feature X" = NONE (parallel features, not conflict).
- Product rebranding is NOT a contradiction. "SAP Cloud ERP Private Edition" and "SAP S/4HANA Cloud Private Edition" refer to the same product.
- You MUST quote the EXACT phrases from each claim that create the relationship.

Respond ONLY with valid JSON (no markdown):
{{"relation": "CONTRADICTS|QUALIFIES|REFINES|NONE", "confidence": 0.0, "evidence_a": "exact quote from Claim A", "evidence_b": "exact quote from Claim B", "reasoning": "one sentence why"}}"""


class NLIAdjudicator:
    """Adjudique les paires candidates via LLM NLI."""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers

    def adjudicate_batch(
        self,
        pairs: list,  # list[CandidatePair]
        on_progress: callable = None,
    ) -> list[AdjudicationResult]:
        """Adjudique un batch de paires en parallele.

        Args:
            pairs: Liste de CandidatePair
            on_progress: Callback(done, total) pour progression

        Returns:
            Liste de AdjudicationResult (seuls ceux qui passent le seuil)
        """
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
                        # Validate evidence is verbatim
                        pair = futures[future]
                        if self._validate_evidence(result, pair):
                            results.append(result)
                        else:
                            logger.debug(f"[C4:NLI] Evidence validation failed for {result.claim_a_id}")
                except Exception as e:
                    logger.debug(f"[C4:NLI] Adjudication failed: {e}")

        duration = time.time() - start
        logger.info(
            f"[C4:NLI] Adjudicated {len(pairs)} pairs in {duration:.1f}s → "
            f"{len(results)} relations found "
            f"({len([r for r in results if r.relation == 'CONTRADICTS'])} CONTRADICTS, "
            f"{len([r for r in results if r.relation == 'QUALIFIES'])} QUALIFIES, "
            f"{len([r for r in results if r.relation == 'REFINES'])} REFINES)"
        )

        return results

    def _adjudicate_one(self, pair) -> AdjudicationResult | None:
        """Adjudique une seule paire via LLM."""
        prompt = NLI_PROMPT.format(
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
            # Parse JSON — handle potential markdown wrapping
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)

            return AdjudicationResult(
                claim_a_id=pair.claim_a_id,
                claim_b_id=pair.claim_b_id,
                relation=data.get("relation", "NONE"),
                confidence=float(data.get("confidence", 0)),
                evidence_a=data.get("evidence_a", ""),
                evidence_b=data.get("evidence_b", ""),
                reasoning=data.get("reasoning", ""),
                detection_method="embedding_nli",
                doc_a_title=pair.claim_a_doc_title,
                doc_b_title=pair.claim_b_doc_title,
            )

        except json.JSONDecodeError as e:
            logger.debug(f"[C4:NLI] JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"[C4:NLI] LLM call failed: {e}")
            return None

    def _passes_threshold(self, result: AdjudicationResult) -> bool:
        """Verifie si le resultat passe le seuil de confiance asymetrique."""
        if result.relation == "NONE":
            return False
        threshold = THRESHOLDS.get(result.relation, 0.85)
        return result.confidence >= threshold

    def _validate_evidence(self, result: AdjudicationResult, pair) -> bool:
        """Verifie que les preuves sont des substrings des claims originaux.

        Invariant INV-PROOF-01 : preuves verbatim obligatoires.
        """
        if not result.evidence_a or not result.evidence_b:
            return False

        # Tolerance : lowercase comparison, strip whitespace
        text_a = pair.claim_a_text.lower()
        text_b = pair.claim_b_text.lower()
        ev_a = result.evidence_a.lower().strip()
        ev_b = result.evidence_b.lower().strip()

        # Check substring (avec tolerance sur la ponctuation)
        a_valid = ev_a in text_a or ev_a.rstrip('.') in text_a
        b_valid = ev_b in text_b or ev_b.rstrip('.') in text_b

        if not a_valid or not b_valid:
            logger.debug(
                f"[C4:NLI] Evidence mismatch: "
                f"a_valid={a_valid} ({result.evidence_a[:50]}), "
                f"b_valid={b_valid} ({result.evidence_b[:50]})"
            )

        return a_valid and b_valid
