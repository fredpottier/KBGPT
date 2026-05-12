"""
Pydantic models pour Current Resolver V2-S3.

Structurellement minimal et domain-agnostic. Aucun champ specifique à un domaine.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CurrentResolverDecision(str, Enum):
    """Décision de politique appliquée au top candidate."""

    AUTO_PICK_HIGH_CONFIDENCE = "auto_pick_high_confidence"  # top ≥ 0.85
    AUTO_PICK_SINGLE_CANDIDATE = "auto_pick_single_candidate"  # 1 seul candidat
    SUGGEST_WITH_ALTERNATIVES = "suggest_with_alternatives"  # 0.55 ≤ top < 0.85
    ESCALATE_AMBIGUOUS = "escalate_ambiguous"  # top < 0.55, remonter au user
    NOT_FOUND = "not_found"  # 0 candidat


class ConfidenceWeights(BaseModel):
    """Poids des heuristiques runtime (VISION §4.3, configurables).

    Les pondérations sont des indices runtime, **jamais persistées dans le KG**.
    Les valeurs par défaut sont issues de la Vision et peuvent être ajustées
    par persona ou globalement (mais pas écrites dans le KG).
    """

    # Calibration P2.3 — recency renforcée pour les cas borderline
    # (ex: CS-25 Amdt 27 vs Amdt 28, où Amdt 28 est l'autoritaire actuel
    # mais Amdt 27 a plus de centrality KG par hasard sémantique).
    recency: float = 0.60
    version_ordering: float = 0.25
    kg_centrality: float = 0.05
    trust_score: float = 0.10

    auto_pick_threshold: float = 0.85
    suggest_threshold: float = 0.55


class CurrentCandidate(BaseModel):
    """Un candidat au current pour un sujet, avec ses sub-scores et score agrégé.

    Tous les fields scores sont calculés à la volée (non persistés).
    """

    doc_id: str
    publication_date: Optional[str] = None
    has_successor_declared: bool = False  # True si LIFECYCLE_RELATION SUPERSEDES exists
    # Sub-scores (∈ [0, 1])
    score_recency: float = 0.0
    score_version_ordering: float = 0.0
    score_kg_centrality: float = 0.0
    score_trust: float = 0.0
    # Score agrégé pondéré
    confidence: float = 0.0
    # Audit
    diagnostic: dict = Field(default_factory=dict)


class CurrentResolverResult(BaseModel):
    """Sortie du Current Resolver pour une requête."""

    decision: CurrentResolverDecision
    top_candidate: Optional[CurrentCandidate] = None
    alternatives: list[CurrentCandidate] = Field(default_factory=list)
    n_filtered_in_phase1: int = 0
    weights_used: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    reasoning: Optional[str] = None
