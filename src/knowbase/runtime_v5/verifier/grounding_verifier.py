"""V5 GroundingVerifier — orchestrator (CH-52.8.6 / S7.6).

ADR V1.5 §3f : pipeline complet
1. Claim segmentation (ClaimSegmenter)
2. Claim-level NLI (VerifierBackend) avec thresholds par shape
3. Answer-level consistency checks (4 checks)
4. Decision : ACCEPT / RETRY / REJECT
5. Typed failure reasons + retry policy

Charte domain-agnostic strict.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from knowbase.runtime_v5.verifier.answer_checks import run_answer_level_checks
from knowbase.runtime_v5.verifier.backends import (
    NLICheckResult,
    NLIDecision,
    NoOpVerifier,
    VerifierBackend,
)
from knowbase.runtime_v5.verifier.claim_segmenter import (
    Claim,
    ClaimSegmenter,
)
from knowbase.runtime_v5.verifier.failure import (
    FailureReason,
    VerifierFailure,
    make_failure,
)
from knowbase.runtime_v5.verifier.thresholds import (
    ShapeThreshold,
    get_threshold,
)

logger = logging.getLogger(__name__)


class VerificationOutcome(str, Enum):
    """Décision globale du verifier."""
    ACCEPTED = "accepted"  # tous claims OK, aucune failure
    PARTIAL_ACCEPT = "partial_accept"  # quelques failures non-retryable, on accepte avec warning
    RETRY_REQUESTED = "retry_requested"  # retryable failures → demander retry à l'agent
    REJECTED = "rejected"  # failures critiques non-retryable → refuser la réponse


@dataclass
class VerificationReport:
    """Rapport complet d'une vérification."""
    outcome: VerificationOutcome
    claims: list[Claim] = field(default_factory=list)
    nli_results: list[NLICheckResult] = field(default_factory=list)
    failures: list[VerifierFailure] = field(default_factory=list)
    threshold_used: Optional[ShapeThreshold] = None
    latency_ms: float = 0.0
    backend_name: str = ""

    def n_claims(self) -> int:
        return len(self.claims)

    def n_supported(self) -> int:
        return sum(1 for r in self.nli_results
                   if r.decision == NLIDecision.SUPPORTED)

    def support_rate(self) -> float:
        if not self.nli_results:
            return 0.0
        return self.n_supported() / len(self.nli_results)

    def has_retryable_failures(self) -> bool:
        return any(f.retryable for f in self.failures)

    def summary(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "n_claims": self.n_claims(),
            "support_rate": round(self.support_rate(), 3),
            "n_failures": len(self.failures),
            "n_retryable_failures": sum(1 for f in self.failures if f.retryable),
            "failure_reasons": [f.reason.value for f in self.failures],
            "latency_ms": self.latency_ms,
            "backend": self.backend_name,
        }


# ─── GroundingVerifier ───────────────────────────────────────────────────────


class GroundingVerifier:
    """Orchestre claim segmentation + NLI + answer-level checks.

    Args:
        backend : VerifierBackend (default NoOpVerifier)
        segmenter : ClaimSegmenter (default standard)
        partial_accept_rate : si support_rate >= ce seuil, on PARTIAL_ACCEPT
                              au lieu de REJECT (default 0.7 = 70% supported)
        max_evidence_chars : tronque evidence quand passé au NLI (default 8000)
    """

    def __init__(
        self,
        backend: Optional[VerifierBackend] = None,
        segmenter: Optional[ClaimSegmenter] = None,
        partial_accept_rate: float = 0.70,
        max_evidence_chars: int = 8000,
    ):
        self.backend = backend or NoOpVerifier()
        self.segmenter = segmenter or ClaimSegmenter()
        self.partial_accept_rate = partial_accept_rate
        self.max_evidence_chars = max_evidence_chars

    # ─── Main entrypoint ────────────────────────────────────────────────────

    def verify(
        self,
        answer_text: str,
        evidence_by_citation: dict[str, str],
        answer_shape: Optional[str] = None,
        cited_tool_names: Optional[set[str]] = None,
    ) -> VerificationReport:
        """Vérifie une réponse en bloc.

        Args:
            answer_text : texte de la réponse draft (peut contenir [doc=X] citations)
            evidence_by_citation : mapping citation_key → evidence_text.
                Keys : doc_id OU section_id OU source_index str
            answer_shape : pour récupérer threshold par shape
            cited_tool_names : pour answer-level check unsupported_numeric_transform

        Returns:
            VerificationReport avec outcome + claims + nli_results + failures
        """
        t0 = time.time()
        threshold = get_threshold(answer_shape)

        # 1. Claim segmentation
        claims = self.segmenter.segment(answer_text)

        # 2. Claim-level NLI checks
        nli_results = []
        per_claim_failures: list[VerifierFailure] = []
        for i, claim in enumerate(claims):
            # Pick evidence by citation refs
            evidence = self._resolve_evidence(claim, evidence_by_citation)
            if not evidence:
                # Aucune evidence → missing_evidence
                per_claim_failures.append(make_failure(
                    reason=FailureReason.MISSING_EVIDENCE,
                    details=(
                        f"Claim {i} has no resolvable evidence "
                        f"(claim citations: {[r.raw for r in claim.citations]})"
                    ),
                    affected_claim_text=claim.text,
                    affected_claim_index=i,
                ))
                continue
            evidence_trimmed = evidence[:self.max_evidence_chars]
            result = self.backend.check(claim.text, evidence_trimmed)
            nli_results.append(result)

            # Apply threshold-based decision (overrides backend decision)
            adjusted_decision = self._apply_threshold(result.score, threshold)
            if adjusted_decision != result.decision:
                # Le threshold override le decision du backend
                result.decision = adjusted_decision

            # Classify failure
            if adjusted_decision == NLIDecision.CONTRADICTED:
                per_claim_failures.append(make_failure(
                    reason=FailureReason.CITATION_MISMATCH,
                    details=(
                        f"Claim {i} contradicted by cited evidence "
                        f"(NLI score={result.score:.3f}, threshold support={threshold.support})"
                    ),
                    affected_claim_text=claim.text,
                    affected_claim_index=i,
                ))
            elif adjusted_decision == NLIDecision.NEUTRAL:
                # Neutral : evidence n'est ni pour ni contre → missing si shape=quantitative/factual
                if answer_shape and answer_shape.lower() in ("factual", "quantitative", "lifecycle"):
                    per_claim_failures.append(make_failure(
                        reason=FailureReason.MISSING_EVIDENCE,
                        details=(
                            f"Claim {i} not supported by evidence (NLI neutral, "
                            f"score={result.score:.3f} < support_threshold={threshold.support})"
                        ),
                        affected_claim_text=claim.text,
                        affected_claim_index=i,
                    ))

        # 3. Answer-level consistency checks
        answer_failures = run_answer_level_checks(claims, cited_tool_names)
        all_failures = per_claim_failures + answer_failures

        # 4. Outcome decision
        outcome = self._decide_outcome(claims, nli_results, all_failures, threshold)

        latency_ms = (time.time() - t0) * 1000.0
        return VerificationReport(
            outcome=outcome,
            claims=claims,
            nli_results=nli_results,
            failures=all_failures,
            threshold_used=threshold,
            latency_ms=latency_ms,
            backend_name=self.backend.name,
        )

    # ─── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_evidence(claim: Claim, evidence_map: dict[str, str]) -> str:
        """Récupère l'evidence text pour les citations d'un claim."""
        pieces = []
        for ref in claim.citations:
            # Try section_id puis doc_id puis source_index
            keys_to_try = []
            if ref.section_id:
                keys_to_try.append(ref.section_id)
            if ref.doc_id:
                keys_to_try.append(ref.doc_id)
            if ref.source_index is not None:
                keys_to_try.append(str(ref.source_index))
            for k in keys_to_try:
                if k in evidence_map:
                    pieces.append(evidence_map[k])
                    break
        return "\n\n".join(pieces)

    @staticmethod
    def _apply_threshold(score: float, threshold: ShapeThreshold) -> NLIDecision:
        """Map score → decision via threshold (inverse pour unanswerable)."""
        if threshold.inverted:
            # Cas unanswerable : score haut = bad (réponse alors qu'elle devrait abstain)
            if score >= threshold.support:
                return NLIDecision.CONTRADICTED  # réponse non-attendue
            elif score <= threshold.contradict:
                return NLIDecision.SUPPORTED  # abstention valide
            return NLIDecision.NEUTRAL
        # Cas normal
        if score >= threshold.support:
            return NLIDecision.SUPPORTED
        if score <= threshold.contradict:
            return NLIDecision.CONTRADICTED
        return NLIDecision.NEUTRAL

    def _decide_outcome(
        self,
        claims: list[Claim],
        nli_results: list[NLICheckResult],
        failures: list[VerifierFailure],
        threshold: ShapeThreshold,
    ) -> VerificationOutcome:
        """Décide l'outcome global selon failures + support_rate."""
        if not claims:
            # Aucun claim détecté → on accepte (réponse vide ou métadonnée)
            return VerificationOutcome.ACCEPTED

        retryable = [f for f in failures if f.retryable]
        non_retryable = [f for f in failures if not f.retryable]

        # Critical non-retryable → REJECT
        critical = [
            f for f in non_retryable
            if f.reason in (
                FailureReason.CONTRADICTORY_CITATIONS,
                FailureReason.VERSION_CONFLICT,
                FailureReason.UNSUPPORTED_NUMERIC_TRANSFORM,
                FailureReason.CROSS_TENANT,
                FailureReason.COST_CAP_EXCEEDED,
            )
        ]
        if critical:
            return VerificationOutcome.REJECTED

        # Retryable failures (missing_evidence / citation_mismatch)
        if retryable:
            return VerificationOutcome.RETRY_REQUESTED

        # Failures non-retryable mais soft (missing_qualifier, tool_error)
        if non_retryable:
            return VerificationOutcome.PARTIAL_ACCEPT

        # Pas de failure : check support rate
        if nli_results:
            n_supported = sum(
                1 for r in nli_results if r.decision == NLIDecision.SUPPORTED
            )
            rate = n_supported / len(nli_results)
            if rate >= self.partial_accept_rate:
                return VerificationOutcome.ACCEPTED
            return VerificationOutcome.PARTIAL_ACCEPT
        return VerificationOutcome.ACCEPTED
