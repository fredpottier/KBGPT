"""
OSMOSIS V4 — SelfCorrector transverse (AlignRAG pattern, CH-41 transverse layer B).

Désactivable via env FACTS_FIRST_MODE=latency (mode latence-prioritaire) qui
court-circuite tous les retry — utile pour cas presales/demo où la rapidité
prime sur le recall maximal.

Implémentation simplifiée d'AlignRAG (arXiv 2504.14858 — Critique-Driven Alignment) :
quand le Verifier signale un échec actionnable (items uncited, identifier mismatch,
low confidence sur facts, etc.), le SelfCorrector reformule un FEEDBACK textuel
court et ré-invoque le Structurer une fois avec ce feedback en input.

Pattern :
  Structurer.structure(question, evidence) → result_v1
  Verifier.verify(...)                     → report_v1
  IF report_v1 has actionable errors:
    feedback = SelfCorrector.build_feedback(report_v1)
    result_v2 = Structurer.structure(..., feedback_for_retry=feedback)
    Verifier.verify(...)                   → report_v2
    IF report_v2.passed: return result_v2
    ELSE: return result_v1 (rollback to original; the retry didn't help)

100% transverse : marche pour list, factual, temporal, comparison, causal —
pas de logique type-specific ici. La seule connaissance domain-specific est dans
les VerifierIssue.code détaillés par chaque type Verifier.

Charte D-FF7 (repair policy) :
  - max 1 retry (pas de boucle infinie)
  - retry uniquement si verifier passed=False ET issues actionnables détectées
  - rollback transparent au result_v1 si retry n'aide pas (ne pas dégrader)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# Mode global : "quality" (default — retries actifs) | "latency" (court-circuit retries)
FACTS_FIRST_MODE = os.getenv("FACTS_FIRST_MODE", "quality").lower()

# CH-46 L2 — Tightening seuil warnings : ne retry sur warnings seuls que si ≥ N warnings.
# Avant : 1 warning actionnable suffisait → trigger retry 70% des cas (overhead 63s).
# Après : seuil=2 par défaut → retry sur warnings seulement si ≥2 (~30% des cas).
# Errors actionnables continuent de toujours déclencher retry (1 suffit).
# Rollback : SELFCORRECTOR_WARNING_THRESHOLD=1.
SELFCORRECTOR_WARNING_THRESHOLD = int(os.getenv("SELFCORRECTOR_WARNING_THRESHOLD", "2"))


# Codes d'issue actionnables par retry feedback
# (un retry peut corriger ces erreurs ; les autres = bug schéma, pas réparable)
ACTIONABLE_ERROR_CODES = {
    # List
    "item.duplicate_id",
    "item.source.quote_too_short",
    "item.source.missing_doc_id",
    "composer.support_ids.unknown",
    "coverage.complete_but_empty",
    "answerability.answerable_but_empty",
    # Factual
    "factual.fact.duplicate_id",
    "factual.fact.source.quote_too_short",
    "factual.fact.source.missing_doc_id",
    "factual.direct_answer.unknown_id",
    "factual.answerable_but_empty",
}

# Warnings actionnables (pas error mais ré-extraction peut aider)
ACTIONABLE_WARNING_CODES = {
    "composer.items.uncited",
    "identifier.missing_in_response",
    "factual.fact.object.raw_not_in_quote",
    "factual.direct_answer.empty",
}


@dataclass
class SelfCorrectionDecision:
    """Décision du SelfCorrector — info pour diagnostic."""
    should_retry: bool
    feedback_message: str = ""
    actionable_codes: list[str] = field(default_factory=list)


class SelfCorrector:
    """Transverse retry policy (AlignRAG-inspired).

    Args:
        max_retries: 1 max par défaut (charte D-FF7)
        require_warning_severity: si True, retry aussi sur warnings actionnables
            (sinon uniquement sur errors)
    """

    def __init__(
        self,
        max_retries: int = 1,
        retry_on_actionable_warnings: bool = True,
    ) -> None:
        self.max_retries = max_retries
        self.retry_on_actionable_warnings = retry_on_actionable_warnings

    def decide(self, verifier_report: Any) -> SelfCorrectionDecision:
        """Inspecte le verifier_report et décide si retry nécessaire.

        Args:
            verifier_report: VerifierReport (list ou factual) avec .issues + .passed
        """
        # Court-circuit en mode latency
        if FACTS_FIRST_MODE == "latency":
            return SelfCorrectionDecision(should_retry=False, feedback_message="latency_mode_skip")
        if verifier_report is None:
            return SelfCorrectionDecision(should_retry=False)

        issues = list(getattr(verifier_report, "issues", []) or [])
        if not issues:
            return SelfCorrectionDecision(should_retry=False)

        actionable_errors = [i for i in issues
                              if getattr(i, "severity", "") == "error"
                              and getattr(i, "code", "") in ACTIONABLE_ERROR_CODES]
        actionable_warnings = []
        if self.retry_on_actionable_warnings:
            actionable_warnings = [i for i in issues
                                    if getattr(i, "severity", "") == "warning"
                                    and getattr(i, "code", "") in ACTIONABLE_WARNING_CODES]

        # CH-46 L2 — Tightening : trigger sur (actionable_errors > 0) OU (warnings ≥ threshold).
        # Avant le retry trigge sur 1 warning isolé ; le seuil monte le bar à ≥ N warnings.
        warnings_threshold_met = len(actionable_warnings) >= SELFCORRECTOR_WARNING_THRESHOLD
        if not actionable_errors and not warnings_threshold_met:
            return SelfCorrectionDecision(should_retry=False)

        feedback = self._build_feedback(actionable_errors, actionable_warnings)
        all_codes = [i.code for i in actionable_errors + actionable_warnings]
        return SelfCorrectionDecision(
            should_retry=True,
            feedback_message=feedback,
            actionable_codes=all_codes,
        )

    @staticmethod
    def _build_feedback(errors: list, warnings: list) -> str:
        """Compose un feedback court (≤ 600 chars) à partir des issues actionnables."""
        lines = []
        if errors:
            lines.append("Errors that MUST be fixed in the new attempt:")
            for i in errors[:5]:
                lines.append(f"  - [{i.code}] {i.message}")
        if warnings:
            lines.append("Warnings to address if possible:")
            for i in warnings[:5]:
                lines.append(f"  - [{i.code}] {i.message}")
        lines.append("")
        lines.append(
            "Use the SAME evidence pool. Do not invent items/facts. Make sure every "
            "extracted item has a verbatim source quote ≥10 chars from the pool, a valid "
            "doc_id, and unique item_id/fact_id."
        )
        return "\n".join(lines)

    @staticmethod
    def select_better(result_v1, result_v2, report_v1, report_v2) -> tuple[Any, Any, str]:
        """Sélectionne le meilleur résultat entre tentative initiale et retry.

        Critères (ordre) :
          1. Si retry passe verifier (report_v2.passed) ET initial ne passe pas → retry
          2. Si retry a moins d'issues errors que initial → retry
          3. Sinon → initial (ne pas dégrader)

        Returns:
            (selected_result, selected_report, decision_reason)
        """
        v1_passed = bool(getattr(report_v1, "passed", False))
        v2_passed = bool(getattr(report_v2, "passed", False))
        if v2_passed and not v1_passed:
            return result_v2, report_v2, "retry_passed_initial_failed"
        if v1_passed and not v2_passed:
            return result_v1, report_v1, "initial_passed_retry_failed_rollback"

        v1_errors = sum(1 for i in (getattr(report_v1, "issues", []) or [])
                        if getattr(i, "severity", "") == "error")
        v2_errors = sum(1 for i in (getattr(report_v2, "issues", []) or [])
                        if getattr(i, "severity", "") == "error")
        if v2_errors < v1_errors:
            return result_v2, report_v2, "retry_fewer_errors"
        if v2_errors > v1_errors:
            return result_v1, report_v1, "rollback_retry_introduced_errors"
        # Égalité errors → préférer retry si plus d'items extraits (proxy de progrès)
        v1_items = SelfCorrector._count_items(result_v1)
        v2_items = SelfCorrector._count_items(result_v2)
        if v2_items > v1_items:
            return result_v2, report_v2, "retry_more_items_same_errors"
        return result_v1, report_v1, "no_improvement_keep_initial"

    @staticmethod
    def _count_items(structurer_result) -> int:
        ff = getattr(structurer_result, "facts_first_json", None) or {}
        list_specific = ff.get("list_specific") or {}
        if "items" in list_specific:
            return len(list_specific.get("items") or [])
        factual_specific = ff.get("factual_specific") or {}
        if "facts" in factual_specific:
            return len(factual_specific.get("facts") or [])
        return 0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default: Optional[SelfCorrector] = None


def get_self_corrector() -> SelfCorrector:
    global _default
    if _default is None:
        _default = SelfCorrector()
    return _default


def reset_self_corrector() -> None:
    global _default
    _default = None
