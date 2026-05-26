"""
grounding_gate.py — P1.4b-4 : vérification de grounding/fidélité d'un claim (Q4/Q5).

Après décomposition+décontextualisation (Stage B), on vérifie qu'un claim est bien ANCRÉ
dans sa source (pas d'hallucination introduite par la décontextualisation) :

(a) ANCRAGE IDENTIFIANTS (déterministe, gratuit, toujours) : chaque identifiant précis du
    claim (specific_identifiers) doit apparaître dans la source. Un identifiant absent =
    hallucination flagrante (transaction/code/n° inventé) → flag.
(b) ENTAILMENT NLI : claim ⊨ source. Modèle `cross-encoder/nli-deberta-v3-base` (décidé au
    spike p1_grounding_nli_spike.py : séparation fidèle/hallu +0.992 ; bge-reranker écarté
    car reranker≠NLI ; HHEM cassé). P(entailment) = softmax(logits)[1], seuil ~0.5.

PRÉMISSE = le PASSAGE source (`passage_text`), PAS le verbatim seul : la décontextualisation
nomme le sujet depuis le contexte du passage (« It supports X » → « SAP HANA supports X »),
donc le claim n'est pas entailé par le verbatim isolé mais bien par le passage.

POLITIQUE : **flag `marginal`, JAMAIS reject** (cohérent « NULL > faux » + préserver le rappel).
Scorer NLI INJECTABLE → testable sans charger le modèle ; indisponibilité → on n'applique que
l'ancrage déterministe (NLI sauté, pas de flag NLI à tort).

Caveat : le modèle est EN-fort → re-tester sur claims FR avant de s'y fier en multilingue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from knowbase.claimfirst.quality.identifier_guard import specific_identifiers

logger = logging.getLogger(__name__)

NLI_MODEL = "cross-encoder/nli-deberta-v3-base"


@dataclass
class GroundingResult:
    marginal: bool
    identifier_anchored: bool
    missing_identifiers: List[str] = field(default_factory=list)
    entailed: Optional[bool] = None        # None = NLI non appliqué (modèle indispo)
    entail_score: Optional[float] = None
    reason: str = ""


class GroundingGate:
    """Vérifie l'ancrage d'un claim dans sa source. Flag marginal, ne rejette pas.

    Args:
        entail_threshold: seuil P(entailment) (défaut 0.5 ; marge énorme au spike).
        nli_scorer: callable batch (List[(premise, hypothesis)]) -> List[float] (P(entail)).
            Si None, scorer par défaut lazy (cross-encoder/nli-deberta-v3-base).
        enabled: si False, NLI sauté (seul l'ancrage identifiants s'applique).
    """

    def __init__(
        self,
        entail_threshold: float = 0.5,
        nli_scorer: Optional[Callable[[Sequence[Tuple[str, str]]], List[float]]] = None,
        enabled: bool = True,
    ):
        self.entail_threshold = entail_threshold
        self.enabled = enabled
        self._nli_scorer = nli_scorer
        self._ce = None
        self._ce_failed = False

    # ── scorer NLI par défaut (lazy, fallback sûr) ────────────────────────────
    def _default_scorer(self, pairs: Sequence[Tuple[str, str]]) -> Optional[List[float]]:
        if self._ce_failed:
            return None
        if self._ce is None:
            try:
                from sentence_transformers import CrossEncoder
                self._ce = CrossEncoder(NLI_MODEL)
            except Exception as exc:  # pragma: no cover
                logger.warning("[GroundingGate] NLI %s indisponible: %s", NLI_MODEL, exc)
                self._ce_failed = True
                return None
        try:
            import numpy as np
            logits = self._ce.predict(list(pairs), apply_softmax=False, convert_to_numpy=True)
            out: List[float] = []
            for row in logits:
                row = np.asarray(row, dtype=float)
                e = np.exp(row - row.max())
                p = e / e.sum()
                out.append(float(p[1]))  # idx 1 = entailment pour ce modèle
            return out
        except Exception as exc:  # pragma: no cover
            logger.warning("[GroundingGate] NLI predict échec: %s", exc)
            self._ce_failed = True
            return None

    def _score(self, pairs: Sequence[Tuple[str, str]]) -> Optional[List[float]]:
        if not pairs:
            return []
        if self._nli_scorer is not None:
            try:
                return list(self._nli_scorer(pairs))
            except Exception as exc:  # pragma: no cover
                logger.warning("[GroundingGate] scorer injecté échec: %s", exc)
                return None
        return self._default_scorer(pairs)

    # ── API ───────────────────────────────────────────────────────────────────
    def check_batch(
        self, items: Sequence[Tuple[str, str]]
    ) -> List[GroundingResult]:
        """items = [(claim_text, source_text)] ; source_text = passage de préférence."""
        if not items:
            return []
        # (a) ancrage identifiants — déterministe
        anchor: List[Tuple[bool, List[str]]] = []
        for claim_text, source_text in items:
            src_low = (source_text or "").lower()
            missing = [tok for tok in specific_identifiers(claim_text) if tok not in src_low]
            anchor.append((len(missing) == 0, missing))

        # (b) NLI entailment — seulement si activé
        scores: Optional[List[float]] = None
        if self.enabled:
            scores = self._score([(src or "", clm or "") for clm, src in items])

        results: List[GroundingResult] = []
        for i, (claim_text, _src) in enumerate(items):
            id_ok, missing = anchor[i]
            entailed: Optional[bool] = None
            score: Optional[float] = None
            if scores is not None and i < len(scores):
                score = scores[i]
                entailed = score >= self.entail_threshold
            marginal = (not id_ok) or (entailed is False)
            reasons = []
            if not id_ok:
                reasons.append(f"identifiants non ancrés: {missing}")
            if entailed is False:
                reasons.append(f"non entailé (NLI={score:.3f})")
            results.append(GroundingResult(
                marginal=marginal, identifier_anchored=id_ok, missing_identifiers=missing,
                entailed=entailed, entail_score=score, reason="; ".join(reasons),
            ))
        return results

    def check(self, claim_text: str, source_text: str) -> GroundingResult:
        return self.check_batch([(claim_text, source_text)])[0]
