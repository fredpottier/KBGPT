# src/knowbase/claimfirst/quality/quality_gate_runner.py
"""
Orchestrateur des 5 gates qualité.

Instance unique pour tout le pipeline — conserve les scores entre phases.

Phases:
- Phase 1.4: Verifiability gate (AVANT dedup)
- Phase 1.6b: Deterministic gates (tautologie, template, SF alignment)
- Phase 1.6c: Atomicity splitter
- Phase 2.6: Independence resolver (APRÈS entity canonicalization)

V1.3: Quality gates pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from knowbase.claimfirst.quality.quality_action import QualityAction, QualityVerdict
from knowbase.claimfirst.quality.embedding_scorer import EmbeddingScorer
from knowbase.claimfirst.quality.evidence_rewriter import (
    EvidenceRewriter,
    VERIF_THRESHOLD_REJECT,
    VERIF_THRESHOLD_GRAY,
)
from knowbase.claimfirst.quality.deterministic_gates import (
    check_tautology,
    check_template_leak,
    check_sf_alignment,
)
from knowbase.claimfirst.quality.atomicity_splitter import AtomicitySplitter
from knowbase.claimfirst.quality.independence_resolver import IndependenceResolver

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim
    from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger(__name__)


class QualityGateRunner:
    """
    Orchestre les 5 gates qualité dans l'ordre optimal.

    Instance unique pour tout le pipeline — conserve les scores entre phases.
    """

    def __init__(self):
        self.embedding_scorer = EmbeddingScorer()
        self.evidence_rewriter = EvidenceRewriter()
        self.atomicity_splitter = AtomicitySplitter()
        self.independence_resolver = IndependenceResolver()
        self._verif_scores: Dict[str, float] = {}

    def run_verifiability_gate(
        self,
        claims: List["Claim"],
    ) -> Tuple[List["Claim"], Dict[str, int]]:
        """
        Phase 1.4 — AVANT dedup.

        1. Calcul embedding batch verif: cos(text, verbatim)
        2. Reject < 0.80
        3. Gray zone [0.80, 0.88] → Evidence Rewriter (vLLM)
        4. Rewriter peut ABSTAIN → BUCKET_NOT_CLAIMABLE
        5. Post-check rewrite: cos(rewritten, verbatim) >= 0.88

        Conserve verif_scores dans self pour la Phase 2.6.
        """
        stats = {
            "total_input": len(claims),
            "passed": 0,
            "rejected_fabrication": 0,
            "rewritten_evidence": 0,
            "bucket_not_claimable": 0,
            "total_output": 0,
        }

        if not claims:
            return claims, stats

        # 1. Calcul batch des scores de vérifiabilité
        verif_scores = self.embedding_scorer.score_verifiability(claims)
        self._verif_scores.update(verif_scores)

        # 2. Trier les claims par zone
        passed = []
        rejected = []
        gray_zone = []

        for claim in claims:
            score = verif_scores.get(claim.claim_id, 0.0)

            if score < VERIF_THRESHOLD_REJECT:
                # Rejet direct : fabrication
                rejected.append(claim)
                stats["rejected_fabrication"] += 1
                self._apply_quality_status(
                    claim,
                    QualityAction.REJECT_FABRICATION,
                    {"verif_score": score},
                    [f"Rejected: cos(text,verbatim)={score:.3f} < {VERIF_THRESHOLD_REJECT}"],
                )
            elif score < VERIF_THRESHOLD_GRAY:
                # Gray zone → réécriture nécessaire
                gray_zone.append(claim)
            else:
                # OK
                passed.append(claim)
                stats["passed"] += 1

        # 3. Réécrire les claims de la gray zone via vLLM
        if gray_zone:
            logger.info(
                f"[OSMOSE:QualityGates] Rewriting {len(gray_zone)} claims in gray zone "
                f"[{VERIF_THRESHOLD_REJECT}, {VERIF_THRESHOLD_GRAY}]"
            )
            verdicts = self._run_async(
                self.evidence_rewriter.rewrite_batch(
                    gray_zone, verif_scores, self.embedding_scorer,
                )
            )

            for claim, verdict in zip(gray_zone, verdicts):
                if verdict.action == QualityAction.REWRITE_EVIDENCE_LOCKED:
                    # Réécriture réussie
                    claim.text = verdict.rewritten_text
                    passed.append(claim)
                    stats["rewritten_evidence"] += 1
                    self._apply_quality_status(
                        claim,
                        verdict.action,
                        verdict.scores,
                        [verdict.detail] if verdict.detail else [],
                    )
                elif verdict.action == QualityAction.BUCKET_NOT_CLAIMABLE:
                    rejected.append(claim)
                    stats["bucket_not_claimable"] += 1
                    self._apply_quality_status(
                        claim,
                        verdict.action,
                        verdict.scores,
                        [verdict.detail] if verdict.detail else [],
                    )
                elif verdict.action == QualityAction.REJECT_FABRICATION:
                    rejected.append(claim)
                    stats["rejected_fabrication"] += 1
                    self._apply_quality_status(
                        claim,
                        verdict.action,
                        verdict.scores,
                        [verdict.detail] if verdict.detail else [],
                    )
                else:
                    # PASS (fallback en cas d'erreur LLM)
                    passed.append(claim)
                    stats["passed"] += 1

        stats["total_output"] = len(passed)
        return passed, stats

    def run_deterministic_and_atomicity_gates(
        self,
        claims: List["Claim"],
    ) -> Tuple[List["Claim"], Dict[str, int]]:
        """
        Phase 1.6b-c — après quality filters existants.

        1. Calcul embedding batch SF + triviality
        2. Gates déterministes: tautologie, template leak, SF alignment
        3. Atomicity splitter: len > 160 AND count_clauses >= 3
        """
        stats = {
            "total_input": len(claims),
            "rejected_tautology": 0,
            "rejected_template": 0,
            "sf_discarded": 0,
            "claims_split": 0,
            "sub_claims_created": 0,
            "total_output": 0,
        }

        if not claims:
            return claims, stats

        # 1. Calcul batch des scores SF et triviality
        sf_scores = self.embedding_scorer.score_sf_alignment(claims)
        triviality_scores = self.embedding_scorer.score_triviality(claims)

        # 2. Gates déterministes
        passed = []
        for claim in claims:
            # 2a. Template leak (pas besoin d'embedding)
            verdict = check_template_leak(claim)
            if verdict:
                stats["rejected_template"] += 1
                self._apply_quality_status(
                    claim,
                    verdict.action,
                    verdict.scores,
                    [verdict.detail] if verdict.detail else [],
                )
                continue

            # 2b. Tautologie
            verdict = check_tautology(claim, triviality_scores)
            if verdict:
                stats["rejected_tautology"] += 1
                self._apply_quality_status(
                    claim,
                    verdict.action,
                    verdict.scores,
                    [verdict.detail] if verdict.detail else [],
                )
                continue

            # 2c. SF alignment (ne rejette PAS — supprime SF)
            verdict = check_sf_alignment(claim, sf_scores)
            if verdict:
                stats["sf_discarded"] += 1
                claim.structured_form = None
                self._apply_quality_status(
                    claim,
                    verdict.action,
                    verdict.scores,
                    [verdict.detail] if verdict.detail else [],
                )

            passed.append(claim)

        # 3. Atomicity splitter (vLLM)
        passed, split_verdicts = self._run_async(
            self.atomicity_splitter.split_batch(passed)
        )
        for v in split_verdicts:
            if v.action == QualityAction.SPLIT_ATOMICITY:
                stats["claims_split"] += 1
                stats["sub_claims_created"] += v.scores.get("sub_claims_count", 0)

        stats["total_output"] = len(passed)
        return passed, stats

    def run_independence_gate(
        self,
        claims: List["Claim"],
        claim_entity_map: Dict[str, List[str]],
        passages: List["Passage"],
        entities: Optional[list] = None,
    ) -> Tuple[List["Claim"], Dict[str, int]]:
        """
        Phase 2.6 — après entity canonicalization.

        Utilise self._verif_scores (calculés en Phase 1.4) pour le trigger.

        Args:
            claim_entity_map: Dict claim_id → List[entity_id]
            entities: Entity objects pour résoudre entity_id → name
        """
        stats = {
            "total_input": len(claims),
            "resolved": 0,
            "bucketed": 0,
            "skipped": 0,
            "total_output": 0,
        }

        if not claims:
            return claims, stats

        # Convertir claim_entity_map (claim_id → entity_ids)
        # en claim_entity_names (claim_id → entity_names)
        entity_name_by_id: Dict[str, str] = {}
        if entities:
            for entity in entities:
                entity_name_by_id[entity.entity_id] = entity.normalized_name

        claim_entity_names: Dict[str, List[str]] = {}
        for claim_id, entity_ids in claim_entity_map.items():
            names = [
                entity_name_by_id.get(eid, eid) for eid in entity_ids
            ]
            claim_entity_names[claim_id] = names

        verdicts = self._run_async(
            self.independence_resolver.resolve_batch(
                claims=claims,
                claim_entity_map=claim_entity_names,
                passages=passages,
                verif_scores=self._verif_scores,
                embedding_scorer=self.embedding_scorer,
            )
        )

        # Construire un index claim_id → verdict
        verdict_by_claim: Dict[str, QualityVerdict] = {}
        for claim, verdict in zip(
            [c for c in claims if self._verif_scores.get(c.claim_id, 0) > 0.88],
            verdicts,
        ):
            verdict_by_claim[claim.claim_id] = verdict

        # Appliquer les résolutions
        output = []
        for claim in claims:
            verdict = verdict_by_claim.get(claim.claim_id)
            if verdict is None:
                # Pas traité par le resolver → garder tel quel
                output.append(claim)
                stats["skipped"] += 1
                continue

            if verdict.action == QualityAction.RESOLVE_INDEPENDENCE:
                claim.text = verdict.resolved_text
                output.append(claim)
                stats["resolved"] += 1
                self._apply_quality_status(
                    claim,
                    verdict.action,
                    verdict.scores,
                    [verdict.detail] if verdict.detail else [],
                )
            elif verdict.action == QualityAction.BUCKET_LOW_INDEPENDENCE:
                # On garde la claim mais on marque
                output.append(claim)
                stats["bucketed"] += 1
                self._apply_quality_status(
                    claim,
                    verdict.action,
                    verdict.scores,
                    [verdict.detail] if verdict.detail else [],
                )
            else:
                # PASS
                output.append(claim)
                stats["skipped"] += 1

        stats["total_output"] = len(output)
        resolver_stats = self.independence_resolver.get_stats()
        stats.update({f"resolver_{k}": v for k, v in resolver_stats.items()})

        return output, stats

    @staticmethod
    def _apply_quality_status(
        claim: "Claim",
        action: QualityAction,
        scores: Dict[str, float],
        reasons: List[str],
    ) -> None:
        """Applique le quality_status, quality_scores et quality_reasons sur la claim."""
        claim.quality_status = action.value
        # Merge des scores (ne pas écraser les précédents)
        if claim.quality_scores:
            claim.quality_scores.update(scores)
        else:
            claim.quality_scores = dict(scores)
        # Append des raisons
        if claim.quality_reasons:
            claim.quality_reasons.extend(reasons)
        else:
            claim.quality_reasons = list(reasons)

    @staticmethod
    def _run_async(coro):
        """Exécute une coroutine async depuis un contexte sync."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result()
            else:
                return asyncio.run(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def get_stats(self) -> dict:
        return {
            "evidence_rewriter": self.evidence_rewriter.get_stats(),
            "atomicity_splitter": self.atomicity_splitter.get_stats(),
            "independence_resolver": self.independence_resolver.get_stats(),
            "verif_scores_cached": len(self._verif_scores),
        }


__all__ = [
    "QualityGateRunner",
]
