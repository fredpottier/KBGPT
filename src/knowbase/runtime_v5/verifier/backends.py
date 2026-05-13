"""V5 Verifier backends — NLI interface + implementations.

ADR V1.5 §3f : bake-off HHEM-2.1 vs HHEM-7B vs MiniCheck-770M vs Lynx-8B
vs Glider-3.8B. Le winner est sélectionné sur claim-level F1 par shape.

V1.5 livre :
- VerifierBackend interface abstraite (Protocol)
- NoOpVerifier (toujours OK, default safe pour pas casser)
- MockNLIBackend (scriptable pour tests)
- ScoreBasedVerifier wrapper (applique threshold sur score 0-1)
- HHEMBackend adapter (interface, install model différé)

Production : HHEMBackend wrap `vectara/hallucination_evaluation_model` (déjà
intégré dans le projet via knowbase.common.hhem ou similaire). Bake-off
exécute via différentes implémentations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

logger = logging.getLogger(__name__)


# ─── Result types ────────────────────────────────────────────────────────────


class NLIDecision(str, Enum):
    """Décision d'une vérification NLI."""
    SUPPORTED = "supported"  # la claim est soutenue par les sources
    CONTRADICTED = "contradicted"  # la claim est contredite
    NEUTRAL = "neutral"  # les sources ne soutiennent ni contredisent
    INSUFFICIENT_CONTEXT = "insufficient_context"  # pas assez d'evidence


@dataclass
class NLICheckResult:
    """Résultat d'une vérification NLI sur un claim vs evidence."""
    claim_text: str
    decision: NLIDecision
    score: float = 0.0  # 0-1, confidence du decision
    evidence_snippet: str = ""  # snippet de l'évidence utilisée
    latency_ms: float = 0.0
    backend_name: str = ""


# ─── Backend Protocol ────────────────────────────────────────────────────────


class VerifierBackend(Protocol):
    """Interface verifier : claim + evidence → decision + score."""

    name: str

    def check(self, claim: str, evidence: str) -> NLICheckResult:
        """Vérifie si claim est soutenu par evidence.

        Args:
            claim : texte du claim atomique
            evidence : contenu de la/les section(s) cited

        Returns:
            NLICheckResult avec decision + score
        """
        ...


# ─── NoOpVerifier ────────────────────────────────────────────────────────────


class NoOpVerifier:
    """Verifier no-op : retourne toujours SUPPORTED. Default safe pour ne pas
    bloquer en l'absence d'un backend NLI réel (HHEM-2.1 etc.)."""

    name = "noop"

    def check(self, claim: str, evidence: str) -> NLICheckResult:
        return NLICheckResult(
            claim_text=claim,
            decision=NLIDecision.SUPPORTED,
            score=1.0,
            evidence_snippet=evidence[:200],
            latency_ms=0.0,
            backend_name=self.name,
        )


# ─── MockNLIBackend (tests scriptable) ───────────────────────────────────────


class MockNLIBackend:
    """Backend mock pour tests : décision scriptée par mot-clé dans claim.

    Args:
        default_decision : si claim ne match aucun keyword
        keyword_decisions : dict {keyword → (decision, score)}
    """

    name = "mock_nli"

    def __init__(
        self,
        default_decision: NLIDecision = NLIDecision.SUPPORTED,
        default_score: float = 0.9,
        keyword_decisions: dict[str, tuple[NLIDecision, float]] = None,
    ):
        self.default_decision = default_decision
        self.default_score = default_score
        self.keyword_decisions = keyword_decisions or {}
        self.calls_recorded: list[tuple[str, str]] = []

    def check(self, claim: str, evidence: str) -> NLICheckResult:
        self.calls_recorded.append((claim, evidence))
        claim_lower = claim.lower()
        for kw, (decision, score) in self.keyword_decisions.items():
            if kw.lower() in claim_lower:
                return NLICheckResult(
                    claim_text=claim,
                    decision=decision,
                    score=score,
                    evidence_snippet=evidence[:200],
                    latency_ms=1.0,
                    backend_name=self.name,
                )
        return NLICheckResult(
            claim_text=claim,
            decision=self.default_decision,
            score=self.default_score,
            evidence_snippet=evidence[:200],
            latency_ms=1.0,
            backend_name=self.name,
        )


# ─── ScoreThresholdAdapter ───────────────────────────────────────────────────


class ScoreThresholdAdapter:
    """Adapter qui prend un backend retournant un score 0-1 et applique un
    seuil pour produire une NLIDecision.

    Args:
        backend : underlying backend qui retourne score 0-1
        support_threshold : score ≥ threshold → SUPPORTED
        contradict_threshold : score ≤ threshold → CONTRADICTED (entre les
                               deux thresholds → NEUTRAL)
    """

    def __init__(
        self,
        backend: VerifierBackend,
        support_threshold: float = 0.5,
        contradict_threshold: float = 0.2,
    ):
        if support_threshold < contradict_threshold:
            raise ValueError("support_threshold must be ≥ contradict_threshold")
        self.backend = backend
        self.name = f"threshold({backend.name}, s={support_threshold}, c={contradict_threshold})"
        self.support_threshold = support_threshold
        self.contradict_threshold = contradict_threshold

    def check(self, claim: str, evidence: str) -> NLICheckResult:
        raw = self.backend.check(claim, evidence)
        # Apply threshold remap
        if raw.score >= self.support_threshold:
            decision = NLIDecision.SUPPORTED
        elif raw.score <= self.contradict_threshold:
            decision = NLIDecision.CONTRADICTED
        else:
            decision = NLIDecision.NEUTRAL
        return NLICheckResult(
            claim_text=raw.claim_text,
            decision=decision,
            score=raw.score,
            evidence_snippet=raw.evidence_snippet,
            latency_ms=raw.latency_ms,
            backend_name=self.name,
        )


# ─── HHEMBackend (adapter, install différé) ──────────────────────────────────


class HHEMBackend:
    """Adapter HHEM-2.1-Open (Vectara). DeBERTa-v3-large fine-tuned faithfulness.

    Réutilise `knowbase.facts_first.hhem_judge._get_hhem_model()` (lazy-load
    singleton, modèle déjà installé local sous data/models/hub).

    Format HHEM : input = "[premise]\\n[hypothesis]" → sigmoid score 0-1
    (1.0 = entailed/supported, 0.0 = contradicted).

    Decision mapping :
      score >= support_threshold (default 0.5) → SUPPORTED
      score <= contradict_threshold (default 0.2) → CONTRADICTED
      sinon → NEUTRAL

    Le GroundingVerifier override ces seuils via ShapeThreshold par shape.
    """

    name = "hhem-2.1-open"

    def __init__(
        self,
        support_threshold: float = 0.5,
        contradict_threshold: float = 0.2,
    ):
        if support_threshold < contradict_threshold:
            raise ValueError("support_threshold must be ≥ contradict_threshold")
        self.support_threshold = support_threshold
        self.contradict_threshold = contradict_threshold

    def check(self, claim: str, evidence: str) -> NLICheckResult:
        import time as _t
        from knowbase.facts_first.hhem_judge import _get_hhem_model

        t0 = _t.time()
        loaded = _get_hhem_model()
        if loaded is None:
            # Modèle indisponible (load failed) → NEUTRAL conservateur
            return NLICheckResult(
                claim_text=claim,
                decision=NLIDecision.INSUFFICIENT_CONTEXT,
                score=0.0,
                evidence_snippet=evidence[:200],
                latency_ms=(_t.time() - t0) * 1000.0,
                backend_name=f"{self.name}(unavailable)",
            )
        tokenizer, model, device, torch = loaded

        try:
            # HHEM format : "[premise]\n[hypothesis]"
            formatted = f"{evidence}\n{claim}"
            with torch.no_grad():
                inputs = tokenizer(
                    [formatted], return_tensors="pt",
                    padding=True, truncation=True, max_length=512,
                )
                inputs = {k: v.to(device) for k, v in inputs.items()}
                outputs = model(**inputs)
                score = float(torch.sigmoid(outputs.logits).squeeze(-1).cpu().item())
        except Exception as exc:
            logger.warning("[HHEMBackend] inference failed: %s", exc)
            return NLICheckResult(
                claim_text=claim,
                decision=NLIDecision.INSUFFICIENT_CONTEXT,
                score=0.0,
                evidence_snippet=evidence[:200],
                latency_ms=(_t.time() - t0) * 1000.0,
                backend_name=f"{self.name}(error)",
            )

        if score >= self.support_threshold:
            decision = NLIDecision.SUPPORTED
        elif score <= self.contradict_threshold:
            decision = NLIDecision.CONTRADICTED
        else:
            decision = NLIDecision.NEUTRAL

        return NLICheckResult(
            claim_text=claim,
            decision=decision,
            score=score,
            evidence_snippet=evidence[:200],
            latency_ms=(_t.time() - t0) * 1000.0,
            backend_name=self.name,
        )
