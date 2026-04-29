"""
R6 — Fallback strategies V1.1.

Quand kg_trust < FALLBACK threshold, deux stratégies selon la policy persona :

- **STRICT (compliance_officer)** : hard abstention, on retourne une réponse
  qui dit explicitement "données insuffisantes" et on liste les preuves
  manquantes. Pas de tentative de synthèse approximative.

- **PERMISSIVE (explorer / reader)** : soft fallback, on retourne le best-effort
  basé sur le RAG sémantique pur, avec un disclaimer explicite et un drill-down
  vers les sources. La short_answer est marquée "low confidence".

Cette logique est invoquée par l'orchestrator APRÈS le calcul du trust et
AVANT la synthèse LLM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from knowbase.runtime.personas import FallbackPolicy, PersonaProfile
from knowbase.runtime.trust_evaluator import TrustLevel, TrustScore

logger = logging.getLogger(__name__)


@dataclass
class FallbackDecision:
    """Décision de fallback prise après évaluation du trust."""

    apply_fallback: bool
    """Si True, on applique la stratégie de fallback."""

    strategy: str
    """'NONE' | 'HARD_ABSTENTION' | 'SOFT_RAG_DISCLAIMED'."""

    abstention_message: Optional[str] = None
    """Pour HARD_ABSTENTION : message explicite à afficher."""

    disclaimer: Optional[str] = None
    """Pour SOFT_RAG_DISCLAIMED : disclaimer à préfixer/suffixer à la réponse."""

    triggered_by: list[str] = field(default_factory=list)
    """Notes du trust qui ont déclenché le fallback."""


def decide_fallback(
    trust: TrustScore,
    profile: PersonaProfile,
    chunks_count: int,
) -> FallbackDecision:
    """
    Décide de la stratégie fallback à appliquer.

    Logique :
    1. Si trust.level != FALLBACK ET on a des chunks → pas de fallback
    2. Si trust.level == FALLBACK ou chunks=0 :
       - STRICT policy → HARD_ABSTENTION
       - PERMISSIVE policy → SOFT_RAG_DISCLAIMED
    """
    # Pas de fallback si trust ok
    if trust.level != TrustLevel.FALLBACK and chunks_count > 0:
        return FallbackDecision(apply_fallback=False, strategy="NONE")

    # Fallback déclenché
    if profile.fallback_policy == FallbackPolicy.STRICT:
        message = _build_abstention_message(trust, chunks_count)
        return FallbackDecision(
            apply_fallback=True,
            strategy="HARD_ABSTENTION",
            abstention_message=message,
            triggered_by=trust.notes,
        )

    # PERMISSIVE
    disclaimer = _build_disclaimer(trust, chunks_count)
    return FallbackDecision(
        apply_fallback=True,
        strategy="SOFT_RAG_DISCLAIMED",
        disclaimer=disclaimer,
        triggered_by=trust.notes,
    )


def _build_abstention_message(trust: TrustScore, chunks_count: int) -> str:
    """Message d'abstention pour la policy STRICT (compliance_officer)."""
    if chunks_count == 0:
        return (
            "**Données insuffisantes** — aucune source n'a été trouvée dans le corpus "
            "qui réponde directement à cette question. "
            "Pour un usage réglementaire ou audit, il est recommandé de :\n"
            "- Vérifier que le document de référence est bien ingéré\n"
            "- Reformuler la question avec les termes du domaine\n"
            "- Contacter l'expert métier pour validation manuelle"
        )

    notes_str = "\n- ".join(trust.notes) if trust.notes else "qualité des preuves insuffisante"
    return (
        f"**Confiance insuffisante** (kg_trust = {trust.score:.2f}) — pour un usage "
        f"réglementaire, ce niveau de preuve n'est pas suffisant.\n\n"
        f"Raisons :\n- {notes_str}\n\n"
        f"Recommandation : consulter directement les sources via le drill-down ou "
        f"reformuler la question avec plus de spécificité."
    )


def _build_disclaimer(trust: TrustScore, chunks_count: int) -> str:
    """Disclaimer pour la policy PERMISSIVE (explorer / reader)."""
    if chunks_count == 0:
        return (
            "_⚠ Aucune source structurée trouvée. Cette réponse est un best-effort "
            "basé sur la similarité sémantique uniquement._"
        )
    return (
        f"_⚠ Confiance basse (kg_trust = {trust.score:.2f}). Cette réponse "
        f"s'appuie sur des preuves fragmentaires — vérifier les citations._"
    )


def apply_fallback_to_response(
    composed,
    decision: FallbackDecision,
):
    """
    Applique la décision de fallback à la ComposedResponse en place.

    - HARD_ABSTENTION : remplace short_answer par le message d'abstention
    - SOFT_RAG_DISCLAIMED : préfixe le disclaimer à short_answer
    """
    if not decision.apply_fallback:
        return composed

    if decision.strategy == "HARD_ABSTENTION":
        composed.short_answer = decision.abstention_message or composed.short_answer
        composed.debug_info["fallback_applied"] = "HARD_ABSTENTION"
        composed.debug_info["fallback_reason"] = decision.triggered_by
        # On peut aussi vider business_block (selon politique)
        # Pour l'instant on le garde pour audit trail
    elif decision.strategy == "SOFT_RAG_DISCLAIMED":
        prefix = decision.disclaimer or ""
        composed.short_answer = f"{prefix}\n\n{composed.short_answer}"
        composed.debug_info["fallback_applied"] = "SOFT_RAG_DISCLAIMED"

    return composed


__all__ = [
    "FallbackDecision",
    "decide_fallback",
    "apply_fallback_to_response",
]
