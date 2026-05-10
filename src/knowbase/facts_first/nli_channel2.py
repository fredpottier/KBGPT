"""
OSMOSIS V4 — Channel 2 NLI Verifier (CH-41 transverse layer C).

Wrapper transverse qui réutilise `runtime_v3/nli_judge.py` (HHEM/mDeBERTa déjà
setup CH-39.1) pour vérifier la fidélité de la réponse Composer vs les sources
extraites par le Structurer.

100% transverse : marche pour list, factual, temporal, comparison, causal —
prend juste (answer_text, evidence_quotes) et retourne un FaithfulnessScore.

Channel 1 (déterministe) + Channel 2 (NLI) :
  - Channel 1 vérifie la STRUCTURE (schema, citations, identifiers, doc_ids)
  - Channel 2 vérifie la SÉMANTIQUE (la réponse ne dit pas ce que les sources
    n'ont pas dit)

Référence littérature : VeriCite (arXiv 2510.11394, Oct 2025) — NLI à chaque
transition donne +9-11pts Citation-F1. HHEM-2.1 / Patronus Lynx state-of-the-art
faithfulness 2025-2026.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Activable / désactivable globalement (NLI peut être lent sur CPU)
NLI_CHANNEL2_ENABLED = os.getenv("NLI_CHANNEL2_ENABLED", "true").lower() == "true"
# Backend NLI : "mdeberta" (default, NLI XNLI multilingue) | "hhem" (HHEM-2.1, mieux calibré paraphrases)
NLI_BACKEND = os.getenv("NLI_BACKEND", "mdeberta").lower()


@dataclass
class Channel2Report:
    """Rapport Channel 2 NLI."""
    enabled: bool = True
    overall_score: float = 1.0  # 0=unfaithful, 1=faithful
    overall_verdict: str = "FAITHFUL"  # FAITHFUL | PARTIAL | UNFAITHFUL | SKIPPED
    n_claims_supported: int = 0
    n_claims_unsupported: int = 0
    n_claims_neutral: int = 0
    latency_ms: int = 0
    skip_reason: Optional[str] = None
    per_claim_verdicts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "overall_score": self.overall_score,
            "overall_verdict": self.overall_verdict,
            "n_claims_supported": self.n_claims_supported,
            "n_claims_unsupported": self.n_claims_unsupported,
            "n_claims_neutral": self.n_claims_neutral,
            "latency_ms": self.latency_ms,
            "skip_reason": self.skip_reason,
        }


class _EvidenceTextWrapper:
    """Adaptateur léger pour passer une string comme un EvidenceClaim au judge_faithfulness."""
    __slots__ = ("text", "doc_id")

    def __init__(self, text: str, doc_id: str = "unknown") -> None:
        self.text = text
        self.doc_id = doc_id


class Channel2NLIVerifier:
    """Verifier sémantique transverse via NLI (HHEM/mDeBERTa)."""

    def __init__(self, enabled: bool = NLI_CHANNEL2_ENABLED, max_claims: int = 8) -> None:
        self.enabled = enabled
        self.max_claims = max_claims

    def verify(
        self,
        composer_output: dict,
        facts_first: dict,
    ) -> Channel2Report:
        """Vérifie sémantiquement la cohérence answer_text ↔ source quotes.

        Args:
            composer_output: dict avec 'answer_text' (str)
            facts_first: dict facts_first_v1 (extrait les source.quote des items/facts)
        """
        report = Channel2Report(enabled=self.enabled)
        if not self.enabled:
            report.overall_verdict = "SKIPPED"
            report.skip_reason = "channel2_disabled"
            return report

        t0 = time.time()
        answer = (composer_output or {}).get("answer_text", "") or ""
        if not answer or len(answer.strip()) < 30:
            report.overall_verdict = "SKIPPED"
            report.skip_reason = "answer_too_short"
            report.latency_ms = int((time.time() - t0) * 1000)
            return report

        # Skip Channel 2 sur abstentions déterministes (réponse standardisée
        # "pas trouvée" — NLI score 0.0 = faux positif systématique)
        answer_lower = answer.strip().lower()
        abstention_markers = (
            "n'a pas été trouvée dans les documents",
            "was not found in the available documents",
        )
        if any(m in answer_lower for m in abstention_markers):
            report.overall_verdict = "SKIPPED"
            report.skip_reason = "abstention_response"
            report.overall_score = 1.0  # abstention = honnête, pas pénalisée
            report.latency_ms = int((time.time() - t0) * 1000)
            return report

        evidence_texts = self._collect_source_quotes(facts_first)
        if not evidence_texts:
            report.overall_score = 0.0
            report.overall_verdict = "UNFAITHFUL"
            report.skip_reason = "no_source_quotes"
            report.latency_ms = int((time.time() - t0) * 1000)
            return report

        # Dispatch vers HHEM-2.1 ou mDeBERTa selon NLI_BACKEND
        evidence_claims = [_EvidenceTextWrapper(text=q, doc_id="src") for q in evidence_texts]
        try:
            if NLI_BACKEND == "hhem":
                from knowbase.facts_first.hhem_judge import judge_faithfulness_hhem
                faithfulness_report = judge_faithfulness_hhem(
                    answer=answer, claims=evidence_claims,
                    max_claims_in_eval=self.max_claims,
                )
            else:
                from knowbase.runtime_v3.nli_judge import judge_faithfulness
                faithfulness_report = judge_faithfulness(
                    answer=answer, claims=evidence_claims,
                    max_claims_in_eval=self.max_claims,
                )
        except ImportError as exc:
            logger.warning("NLI backend %s import failed: %s", NLI_BACKEND, exc)
            report.overall_verdict = "SKIPPED"
            report.skip_reason = f"import_error: {exc}"
            report.latency_ms = int((time.time() - t0) * 1000)
            return report
        except Exception as exc:
            logger.warning("NLI backend %s judge failed: %s", NLI_BACKEND, exc)
            report.overall_verdict = "SKIPPED"
            report.skip_reason = f"nli_error: {exc}"
            report.latency_ms = int((time.time() - t0) * 1000)
            return report

        report.overall_score = float(getattr(faithfulness_report, "overall_score", 0.0))
        report.overall_verdict = str(getattr(faithfulness_report, "overall_verdict", "UNFAITHFUL"))
        report.n_claims_supported = int(getattr(faithfulness_report, "n_supported", 0))
        report.n_claims_unsupported = int(getattr(faithfulness_report, "n_unsupported", 0))
        report.n_claims_neutral = int(getattr(faithfulness_report, "n_neutral", 0))
        # Per-claim détails (pour audit)
        for cv in getattr(faithfulness_report, "claim_verdicts", []) or []:
            report.per_claim_verdicts.append({
                "claim": getattr(cv, "claim", "")[:160],
                "verdict": getattr(cv, "verdict", ""),
                "entailment": float(getattr(cv, "entailment", 0.0)),
                "contradiction": float(getattr(cv, "contradiction", 0.0)),
            })
        report.latency_ms = int((time.time() - t0) * 1000)
        return report

    @staticmethod
    def _collect_source_quotes(facts_first: dict) -> list[str]:
        """Extrait les source.quote des items (list) ou facts (factual) ou autres."""
        quotes: list[str] = []
        list_specific = facts_first.get("list_specific") or {}
        for it in list_specific.get("items") or []:
            q = ((it or {}).get("source") or {}).get("quote") or ""
            if q:
                quotes.append(q)
        factual_specific = facts_first.get("factual_specific") or {}
        for f in factual_specific.get("facts") or []:
            q = ((f or {}).get("source") or {}).get("quote") or ""
            if q:
                quotes.append(q)
        # Pour les autres types (temporal, comparison, causal) à venir, structures
        # peuvent différer ; on ratisse large via récursion sur clés "source"
        if not quotes:
            quotes = Channel2NLIVerifier._extract_quotes_recursive(facts_first)
        # Dédupe en gardant ordre
        seen = set()
        out = []
        for q in quotes:
            qn = q.strip()
            if qn and qn not in seen:
                seen.add(qn)
                out.append(qn)
        return out

    @staticmethod
    def _extract_quotes_recursive(obj: Any, depth: int = 0) -> list[str]:
        """Walk générique pour extraire source.quote depuis structures imbriquées (max depth 6)."""
        if depth > 6:
            return []
        out: list[str] = []
        if isinstance(obj, dict):
            if "quote" in obj and isinstance(obj["quote"], str) and len(obj["quote"]) > 10:
                out.append(obj["quote"])
            for v in obj.values():
                out.extend(Channel2NLIVerifier._extract_quotes_recursive(v, depth + 1))
        elif isinstance(obj, list):
            for v in obj:
                out.extend(Channel2NLIVerifier._extract_quotes_recursive(v, depth + 1))
        return out


_default: Optional[Channel2NLIVerifier] = None


def get_channel2_verifier() -> Channel2NLIVerifier:
    global _default
    if _default is None:
        _default = Channel2NLIVerifier()
    return _default


def reset_channel2_verifier() -> None:
    global _default
    _default = None
