"""GroundingVerifier — détection d'hallucinations post-Synthesize via NLI.

A4.5 (22/05/2026) — cf doc/ongoing/A41_AUDIT_PIPELINE_CLAIMFIRST.md et
project_a44_root_cause_synthesize_hallucination.md.

Contexte
--------
Audit A4.4 a révélé que le LLM Synthesize (Qwen2.5-14B-AWQ) cite des
claims valides mais HALLUCINE des détails autour (ex HUM_0031 : "transaction
SE80" inventée alors que le claim cité parle d'autorisation ABAP).

Smoke validation A4.5 :
- mDeBERTa NLI (multilingual, déjà en infra runtime_v3) détecte les
  hallucinations avec scores clairs :
  - Hallucination "SE80" → CONTRADICTION (2.70)
  - Phrase valide → ENTAILMENT (5.18)

Architecture
------------
Pour chaque SynthesizeOutput :
1. Découper answer_text en phrases avec leur citation [claim_id=X]
2. Pour chaque phrase, fetcher le claim_verbatim cité (déjà dans
   SynthesizeOutput.cited_claims)
3. NLI check : claim_verbatim → phrase
4. Si CONTRADICTION dominante (score > entailment) → flag hallucination
5. Décision :
   - Mode LOG (default) : ajoute warning, conserve la réponse
   - Mode STRIP : remplace les phrases hallucinées par "[verification failed]"
   - Mode ABSTAIN : si >50% phrases hallucinées → ABSTENTION

Toggle env : `V6_GROUNDING_VERIFIER_ENABLED` (default "1")
              `V6_GROUNDING_VERIFIER_MODE` (LOG|STRIP|ABSTAIN, default "LOG")

Charte stricte : domain-agnostic (NLI universel).
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger("knowbase.runtime_a3.grounding_verifier")


# Constants
# Décision NLI : on regarde si contradiction > entailment
# (modèle output = [entailment_logit, neutral_logit, contradiction_logit])
MIN_CONTRADICTION_MARGIN = 1.0  # contradiction - entailment > 1.0 → flag
MIN_SENTENCE_LENGTH = 15  # < 15 chars = trop court (titre, label)


# Patterns pour split phrases (domain-agnostic)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ÿ])")
# Match [claim_id=X] dans une phrase
_CITATION_RE = re.compile(r"\[claim_id=([a-zA-Z0-9_]+)\]")


@dataclass
class SentenceVerification:
    """Résultat de vérification d'une phrase."""

    sentence: str
    cited_claim_ids: List[str]
    nli_entailment: float = 0.0
    nli_contradiction: float = 0.0
    is_hallucination: bool = False
    skipped_reason: Optional[str] = None  # None, "no_citation", "no_evidence", "too_short"


@dataclass
class GroundingReport:
    """Rapport global de vérification post-Synthesize."""

    n_sentences: int = 0
    n_checked: int = 0
    n_hallucinations: int = 0
    n_skipped: int = 0
    verifications: List[SentenceVerification] = None
    duration_s: float = 0.0
    mode_applied: str = "LOG"

    def __post_init__(self):
        if self.verifications is None:
            self.verifications = []

    @property
    def hallucination_rate(self) -> float:
        return self.n_hallucinations / max(self.n_checked, 1)


def _split_sentences(text: str) -> List[str]:
    """Split simple en phrases, conserve la ponctuation."""
    if not text:
        return []
    cleaned = text.strip()
    sentences = _SENT_SPLIT_RE.split(cleaned)
    return [s.strip() for s in sentences if s.strip()]


def _extract_citations(sentence: str) -> List[str]:
    """Extrait tous les claim_ids cités dans la phrase."""
    return _CITATION_RE.findall(sentence)


class GroundingVerifier:
    """Vérifie qu'aucune phrase de answer_text n'hallucine vs les claims cités.

    Injection de dépendance :
        - `nli_predict` : callable `(pairs: List[Tuple[str, str]]) -> List[List[float]]`
          retourne pour chaque paire (premise, hypothesis) un triplet
          [entailment_logit, neutral_logit, contradiction_logit]
    """

    def __init__(
        self,
        nli_predict: Optional[Callable] = None,
        contradiction_margin: float = MIN_CONTRADICTION_MARGIN,
    ):
        self._nli_predict = nli_predict
        self._contradiction_margin = contradiction_margin

    def _get_nli(self) -> Callable:
        if self._nli_predict is None:
            from knowbase.runtime_v3.nli_judge import _get_nli_model
            model = _get_nli_model()

            def _predict(pairs: List[Tuple[str, str]]) -> List[List[float]]:
                # CrossEncoder.predict returns numpy array of [n, 3]
                raw = model.predict(pairs)
                return [list(map(float, row)) for row in raw]

            self._nli_predict = _predict
        return self._nli_predict

    def verify(
        self,
        answer_text: str,
        cited_claims_by_id: dict,
    ) -> GroundingReport:
        """Vérifie answer_text vs les claim_verbatim cités.

        Args:
            answer_text : la réponse générée par Synthesize.
            cited_claims_by_id : dict {claim_id: claim_verbatim_text}
                (depuis SynthesizeOutput.cited_claims).

        Returns:
            GroundingReport avec verifications par phrase.
        """
        t0 = time.perf_counter()
        sentences = _split_sentences(answer_text)
        verifications: List[SentenceVerification] = []
        pairs_to_check: List[Tuple[int, Tuple[str, str]]] = []  # (sentence_idx, (evidence, hypothesis))

        for s_idx, sent in enumerate(sentences):
            verif = SentenceVerification(sentence=sent, cited_claim_ids=[])
            if len(sent) < MIN_SENTENCE_LENGTH:
                verif.skipped_reason = "too_short"
                verifications.append(verif)
                continue

            citations = _extract_citations(sent)
            verif.cited_claim_ids = citations
            if not citations:
                verif.skipped_reason = "no_citation"
                verifications.append(verif)
                continue

            # Récupère le verbatim — concat les claims cités si plusieurs
            evidence_parts = []
            for cid in citations:
                vb = cited_claims_by_id.get(cid)
                if vb:
                    evidence_parts.append(vb)
            if not evidence_parts:
                verif.skipped_reason = "no_evidence"
                verifications.append(verif)
                continue
            evidence = " ".join(evidence_parts)

            # Strip les balises citation de la phrase pour clarté NLI
            hypothesis = _CITATION_RE.sub("", sent).strip()
            if len(hypothesis) < MIN_SENTENCE_LENGTH:
                verif.skipped_reason = "too_short_after_strip"
                verifications.append(verif)
                continue

            verifications.append(verif)
            pairs_to_check.append((s_idx, (evidence, hypothesis)))

        # Batch NLI inference
        if pairs_to_check:
            try:
                preds = self._get_nli()([p for _, p in pairs_to_check])
            except Exception:
                logger.exception("[GroundingVerifier] NLI inference failed")
                preds = []

            for i, (s_idx, _) in enumerate(pairs_to_check):
                if i >= len(preds):
                    continue
                triplet = preds[i]
                if len(triplet) >= 3:
                    ent, _neut, contra = triplet[0], triplet[1], triplet[2]
                    verifications[s_idx].nli_entailment = ent
                    verifications[s_idx].nli_contradiction = contra
                    # Décision : contradiction dominante
                    if (contra - ent) > self._contradiction_margin:
                        verifications[s_idx].is_hallucination = True

        # Stats
        n_checked = sum(1 for v in verifications if v.skipped_reason is None)
        n_hallucinations = sum(1 for v in verifications if v.is_hallucination)
        n_skipped = sum(1 for v in verifications if v.skipped_reason is not None)

        return GroundingReport(
            n_sentences=len(sentences),
            n_checked=n_checked,
            n_hallucinations=n_hallucinations,
            n_skipped=n_skipped,
            verifications=verifications,
            duration_s=time.perf_counter() - t0,
        )


# ============================================================================
# Application : LOG / STRIP / ABSTAIN modes
# ============================================================================


def apply_grounding_decision(
    answer_text: str,
    report: GroundingReport,
    mode: str = "LOG",
) -> Tuple[str, List[str]]:
    """Applique la décision de grounding au answer_text.

    Returns:
        (modified_answer_text, list_of_warnings)
    """
    warnings: List[str] = []
    if mode == "LOG":
        if report.n_hallucinations > 0:
            warnings.append(
                f"[GroundingVerifier] {report.n_hallucinations}/{report.n_checked} "
                f"phrases flagged as potentially hallucinated (NLI contradiction)."
            )
        return answer_text, warnings

    if mode == "STRIP":
        # Reconstruct answer_text en marquant les phrases hallucinées
        sentences = _split_sentences(answer_text)
        new_sentences = []
        for i, sent in enumerate(sentences):
            if i < len(report.verifications) and report.verifications[i].is_hallucination:
                new_sentences.append(
                    f"[verification failed: claim does not support this statement]"
                )
                warnings.append(f"Stripped sentence: {sent[:80]}...")
            else:
                new_sentences.append(sent)
        return " ".join(new_sentences), warnings

    if mode == "ABSTAIN":
        # Si majorité hallucinés → abstain
        if report.n_checked > 0 and report.hallucination_rate > 0.5:
            warnings.append(
                f"[GroundingVerifier] Abstaining ({report.n_hallucinations}/{report.n_checked} "
                f"sentences hallucinated)."
            )
            return (
                "The system cannot provide a verified answer — internal grounding check "
                "rejected the generated response. Abstaining.",
                warnings,
            )
        if report.n_hallucinations > 0:
            warnings.append(
                f"[GroundingVerifier] {report.n_hallucinations}/{report.n_checked} "
                f"sentences flagged but below abstention threshold."
            )
        return answer_text, warnings

    # Unknown mode → no-op
    return answer_text, warnings


# ============================================================================
# Toggles env
# ============================================================================


def is_enabled() -> bool:
    return os.getenv("V6_GROUNDING_VERIFIER_ENABLED", "1") == "1"


def get_mode() -> str:
    mode = os.getenv("V6_GROUNDING_VERIFIER_MODE", "LOG").upper()
    if mode not in {"LOG", "STRIP", "ABSTAIN"}:
        return "LOG"
    return mode
