"""
R2 — Trust Evaluator V1.1.

Calcule le **kg_trust score** d'une réponse compositée à partir de la qualité
des évidences récupérées. Score 0-1 avec 4 seuils :

- **AUTHORITATIVE** (≥ 0.85) : evidences fortes, cohérentes, recentes, scope aligné
- **RELIABLE**      (0.65–0.85) : evidences solides, quelques imprécisions
- **PARTIAL**       (0.40–0.65) : evidences fragmentaires ou contradictoires
- **FALLBACK**      (< 0.40) : trop peu d'evidence, risque hallucination

Pondération V1.1 (cf. RUNTIME_EXPLOITATION §4) :
- **provenance** (0.40) : qualité des sources (validity_start populé, doc identifié,
                          DocumentContext applicability_frame_v2 non-null)
- **inference**  (0.30) : qualité des LOGICAL_RELATION exploités (avg confidence,
                          ratio dérivées vs directes, nombre de paths)
- **recency**    (0.15) : recency des publications (decay exponentiel)
- **regime**     (0.15) : ajustement selon régime (HYBRID > KG_LED > RAG_LED solo)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

from knowbase.runtime.evidence_planner import Regime
from knowbase.runtime.query_resolver import ResponseMode

logger = logging.getLogger(__name__)


class TrustLevel(str, Enum):
    """4 niveaux V1.1 (cf. RUNTIME_EXPLOITATION §4)."""

    AUTHORITATIVE = "AUTHORITATIVE"  # >= 0.85
    RELIABLE = "RELIABLE"             # 0.65 - 0.85
    PARTIAL = "PARTIAL"               # 0.40 - 0.65
    FALLBACK = "FALLBACK"             # < 0.40


@dataclass
class TrustScore:
    """Score kg_trust détaillé."""

    score: float
    """Score 0-1 final."""

    level: TrustLevel
    """Niveau qualifié."""

    breakdown: dict[str, float] = field(default_factory=dict)
    """Sous-scores par axe (provenance, inference, recency, regime)."""

    notes: list[str] = field(default_factory=list)
    """Observations qualitatives sur la confiance."""


THRESHOLDS = {
    TrustLevel.AUTHORITATIVE: 0.85,
    TrustLevel.RELIABLE: 0.65,
    TrustLevel.PARTIAL: 0.40,
}


# Pondérations des 4 axes
WEIGHTS = {
    "provenance": 0.40,
    "inference": 0.30,
    "recency": 0.15,
    "regime": 0.15,
}


class TrustEvaluator:
    """
    Calcule kg_trust à partir des artefacts du retrieval.

    Inputs :
    - chunks (Qdrant) avec metadata (publication_date, validity_start, etc.)
    - relations LOGICAL_RELATION exploitées (avec confidence, derived flag)
    - régime utilisé (RAG_LED / KG_LED / HYBRID)
    - éventuellement persona pour overrides de seuils
    """

    def evaluate(
        self,
        chunks: list[dict],
        relations: list[dict],
        regime: Regime,
        mode: ResponseMode,
        as_of_date: Optional[date] = None,
    ) -> TrustScore:
        """Calcule le kg_trust score complet."""
        provenance = self._score_provenance(chunks)
        inference = self._score_inference(relations)
        recency = self._score_recency(chunks, as_of_date or date.today())
        regime_score = self._score_regime(regime, mode)

        score = (
            WEIGHTS["provenance"] * provenance
            + WEIGHTS["inference"] * inference
            + WEIGHTS["recency"] * recency
            + WEIGHTS["regime"] * regime_score
        )
        score = max(0.0, min(1.0, score))

        level = self._level_for(score)

        breakdown = {
            "provenance": round(provenance, 3),
            "inference": round(inference, 3),
            "recency": round(recency, 3),
            "regime": round(regime_score, 3),
        }

        notes = []
        if not chunks:
            notes.append("No chunks retrieved — RAG fallback impossible.")
        if provenance < 0.5:
            notes.append("Low provenance: many chunks lack ApplicabilityFrame V2 or validity dates.")
        if inference < 0.5 and relations:
            notes.append("Low inference quality: many relations are derived (transitive) with discount.")
        if not relations:
            notes.append("No LOGICAL_RELATION exploited — RAG_LED only response.")

        return TrustScore(
            score=round(score, 3),
            level=level,
            breakdown=breakdown,
            notes=notes,
        )

    def _score_provenance(self, chunks: list[dict]) -> float:
        """Provenance score = ratio chunks avec metadata complète."""
        if not chunks:
            return 0.0
        complete = 0
        for c in chunks:
            score = 0.0
            # publication_date présent (tier 5 ou supérieur)
            if c.get("publication_date"):
                score += 0.3
            # validity_start présent (tier 4 LLM claim-level OU tier 1 doc)
            if c.get("validity_start"):
                score += 0.2
            # DocumentContext applicability_frame_v2 (proxy : doc_id connu)
            if c.get("doc_id"):
                score += 0.3
            # lifecycle_status non-UNKNOWN
            if c.get("lifecycle_status") and c["lifecycle_status"] != "UNKNOWN":
                score += 0.2
            complete += score
        return complete / len(chunks)

    def _score_inference(self, relations: list[dict]) -> float:
        """Inference score = avg confidence pondéré par direct vs derived."""
        if not relations:
            return 0.5  # neutre si pas de relations exploitées
        total_weight = 0.0
        weighted_conf = 0.0
        for r in relations:
            conf = float(r.get("confidence", 0.0) or 0.0)
            is_derived = r.get("derived", False)
            weight = 0.7 if is_derived else 1.0  # dérivées pèsent moins
            total_weight += weight
            weighted_conf += conf * weight
        if total_weight == 0:
            return 0.5
        return weighted_conf / total_weight

    def _score_recency(self, chunks: list[dict], reference: date) -> float:
        """Recency score = avg recency_weight via decay exponentiel sur 5 ans."""
        if not chunks:
            return 0.5
        weights = []
        for c in chunks:
            pub_str = c.get("publication_date")
            if not pub_str:
                weights.append(0.5)
                continue
            try:
                pub_year = int(str(pub_str)[:4])
                age_years = reference.year - pub_year
                if age_years < 0:
                    age_years = 0
                # decay : weight = 2^(-age/5) → 5 ans = 0.5, 10 ans = 0.25
                weight = 2 ** (-age_years / 5.0)
                weights.append(weight)
            except (ValueError, TypeError):
                weights.append(0.5)
        return sum(weights) / len(weights)

    def _score_regime(self, regime: Regime, mode: ResponseMode) -> float:
        """Score de régime : HYBRID > KG_LED > RAG_LED pour les modes structurés."""
        # Pour les modes structurels (CONFLICT_RISK, SNAPSHOT, etc.), KG_LED est attendu
        structural_modes = {
            ResponseMode.APPLICABILITY_QUERY,
            ResponseMode.SNAPSHOT_TEMPORAL,
            ResponseMode.DIFF_EVOLUTION,
            ResponseMode.CONFLICT_RISK,
            ResponseMode.EXPLORATION_RELATIONAL,
        }

        if mode in structural_modes:
            if regime == Regime.KG_LED:
                return 1.0
            if regime == Regime.HYBRID:
                return 0.85
            return 0.5  # RAG_LED sur question structurelle = sub-optimal

        # Pour LOOKUP_FACTUAL : RAG_LED est l'optimal empirique
        if mode == ResponseMode.LOOKUP_FACTUAL:
            if regime == Regime.RAG_LED:
                return 1.0
            return 0.85

        # SYNTHESIS_SUMMARY : HYBRID > KG_LED > RAG_LED
        if mode == ResponseMode.SYNTHESIS_SUMMARY:
            if regime == Regime.HYBRID:
                return 1.0
            return 0.7

        return 0.7

    def _level_for(self, score: float) -> TrustLevel:
        if score >= THRESHOLDS[TrustLevel.AUTHORITATIVE]:
            return TrustLevel.AUTHORITATIVE
        if score >= THRESHOLDS[TrustLevel.RELIABLE]:
            return TrustLevel.RELIABLE
        if score >= THRESHOLDS[TrustLevel.PARTIAL]:
            return TrustLevel.PARTIAL
        return TrustLevel.FALLBACK


__all__ = ["TrustEvaluator", "TrustLevel", "TrustScore", "THRESHOLDS"]
