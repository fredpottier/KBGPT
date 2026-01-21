"""
Phase D - Runtime Tier Filtering pour le mode Reasoned.

Ce module implémente le filtrage par DefensibilityTier au runtime:
- allowed_tiers: Set de tiers autorisés pour la traversée
- Stratégie d'escalade: STRICT → EXTENDED → Anchored

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set, Tuple

from knowbase.relations.types import DefensibilityTier, SemanticGrade

logger = logging.getLogger(__name__)


class TraversalPolicy(str, Enum):
    """
    Politique de traversée prédéfinie.

    Chaque policy définit les tiers autorisés et la stratégie d'escalade.
    """
    # Production: STRICT uniquement, pas d'escalade
    STRICT = "strict"

    # Exploration: STRICT puis EXTENDED si vide
    EXPLORATORY = "exploratory"

    # Balanced: STRICT + EXTENDED directement
    BALANCED = "balanced"

    # Unrestricted: Tous les tiers (pour debug/admin)
    UNRESTRICTED = "unrestricted"


@dataclass
class TierFilterConfig:
    """
    Configuration du filtrage par tier.

    Attributes:
        allowed_tiers: Ensemble des tiers autorisés pour la traversée
        enable_escalation: Si True, escalade vers tier suivant si résultats vides
        escalation_order: Ordre d'escalade des tiers
        max_escalation_steps: Nombre max d'escalades
        fallback_to_anchored: Si True, fallback vers ANCHORED après escalade
    """
    allowed_tiers: Set[DefensibilityTier] = field(
        default_factory=lambda: {DefensibilityTier.STRICT}
    )
    enable_escalation: bool = False
    escalation_order: List[DefensibilityTier] = field(
        default_factory=lambda: [
            DefensibilityTier.STRICT,
            DefensibilityTier.EXTENDED,
        ]
    )
    max_escalation_steps: int = 2
    fallback_to_anchored: bool = True

    @classmethod
    def from_policy(cls, policy: TraversalPolicy) -> "TierFilterConfig":
        """
        Crée une configuration à partir d'une policy prédéfinie.

        Args:
            policy: TraversalPolicy à utiliser

        Returns:
            TierFilterConfig correspondante
        """
        if policy == TraversalPolicy.STRICT:
            return cls(
                allowed_tiers={DefensibilityTier.STRICT},
                enable_escalation=False,
                fallback_to_anchored=True,
            )
        elif policy == TraversalPolicy.EXPLORATORY:
            return cls(
                allowed_tiers={DefensibilityTier.STRICT},
                enable_escalation=True,
                escalation_order=[
                    DefensibilityTier.STRICT,
                    DefensibilityTier.EXTENDED,
                ],
                max_escalation_steps=2,
                fallback_to_anchored=True,
            )
        elif policy == TraversalPolicy.BALANCED:
            return cls(
                allowed_tiers={
                    DefensibilityTier.STRICT,
                    DefensibilityTier.EXTENDED,
                },
                enable_escalation=False,
                fallback_to_anchored=True,
            )
        elif policy == TraversalPolicy.UNRESTRICTED:
            return cls(
                allowed_tiers={
                    DefensibilityTier.STRICT,
                    DefensibilityTier.EXTENDED,
                    DefensibilityTier.EXPERIMENTAL,
                },
                enable_escalation=False,
                fallback_to_anchored=False,
            )
        else:
            # Default: STRICT
            return cls()


@dataclass
class EscalationResult:
    """
    Résultat d'une tentative d'escalade.

    Attributes:
        current_tiers: Tiers actuellement utilisés
        escalation_step: Nombre d'escalades effectuées
        found_results: Si des résultats ont été trouvés
        escalation_path: Historique des escalades
        final_mode: Mode final (REASONED, ANCHORED, TEXT_ONLY)
    """
    current_tiers: Set[DefensibilityTier]
    escalation_step: int = 0
    found_results: bool = False
    escalation_path: List[str] = field(default_factory=list)
    final_mode: Optional[str] = None

    def add_escalation(self, tier: DefensibilityTier) -> None:
        """Enregistre une escalade."""
        self.current_tiers.add(tier)
        self.escalation_step += 1
        self.escalation_path.append(f"escalate_to_{tier.value}")

    def to_audit_trail(self) -> dict:
        """Génère un audit trail pour traçabilité."""
        return {
            "tiers_used": [t.value for t in self.current_tiers],
            "escalation_steps": self.escalation_step,
            "escalation_path": self.escalation_path,
            "final_mode": self.final_mode,
        }


class TierFilterService:
    """
    Service de filtrage par DefensibilityTier.

    Responsabilités:
    1. Générer les clauses Cypher pour filtrer par tier
    2. Gérer la stratégie d'escalade
    3. Tracer les décisions pour auditabilité
    """

    def __init__(self, config: Optional[TierFilterConfig] = None):
        """
        Initialize le service.

        Args:
            config: Configuration du filtrage (défaut: STRICT)
        """
        self.config = config or TierFilterConfig()

    @classmethod
    def from_policy(cls, policy: TraversalPolicy) -> "TierFilterService":
        """
        Crée un service à partir d'une policy.

        Args:
            policy: TraversalPolicy à utiliser

        Returns:
            TierFilterService configuré
        """
        return cls(TierFilterConfig.from_policy(policy))

    def get_tier_filter_clause(
        self,
        relationship_alias: str = "rel",
        allowed_tiers: Optional[Set[DefensibilityTier]] = None,
    ) -> str:
        """
        Génère une clause WHERE Cypher pour filtrer par tier.

        Args:
            relationship_alias: Alias de la relation dans la requête Cypher
            allowed_tiers: Tiers à autoriser (utilise config si None)

        Returns:
            Clause WHERE (sans le mot-clé WHERE)

        Example:
            >>> service.get_tier_filter_clause("r")
            "r.defensibility_tier IN ['STRICT']"
        """
        tiers = allowed_tiers or self.config.allowed_tiers
        tier_values = [t.value for t in tiers]

        # Si tous les tiers sont autorisés, pas besoin de filtre
        if len(tier_values) >= 3:  # STRICT, EXTENDED, EXPERIMENTAL
            return "true"

        return f"{relationship_alias}.defensibility_tier IN {tier_values}"

    def get_tier_filter_clause_with_fallback(
        self,
        relationship_alias: str = "rel",
        allowed_tiers: Optional[Set[DefensibilityTier]] = None,
    ) -> str:
        """
        Génère une clause WHERE avec fallback pour relations sans tier.

        Certaines relations existantes peuvent ne pas avoir de defensibility_tier.
        Cette clause les inclut si STRICT est autorisé (backward compatibility).

        Args:
            relationship_alias: Alias de la relation
            allowed_tiers: Tiers à autoriser

        Returns:
            Clause WHERE avec fallback
        """
        tiers = allowed_tiers or self.config.allowed_tiers
        tier_values = [t.value for t in tiers]

        # Si tous les tiers sont autorisés
        if len(tier_values) >= 3:
            return "true"

        # Inclure les relations sans tier si STRICT est autorisé
        if DefensibilityTier.STRICT in tiers:
            return (
                f"({relationship_alias}.defensibility_tier IS NULL OR "
                f"{relationship_alias}.defensibility_tier IN {tier_values})"
            )

        return f"{relationship_alias}.defensibility_tier IN {tier_values}"

    def should_escalate(
        self,
        results_count: int,
        current_step: int,
    ) -> bool:
        """
        Détermine si une escalade doit être tentée.

        Args:
            results_count: Nombre de résultats trouvés
            current_step: Étape d'escalade actuelle

        Returns:
            True si escalade recommandée
        """
        if not self.config.enable_escalation:
            return False

        if results_count > 0:
            return False

        if current_step >= self.config.max_escalation_steps:
            return False

        return True

    def get_next_escalation_tier(
        self,
        current_tiers: Set[DefensibilityTier],
    ) -> Optional[DefensibilityTier]:
        """
        Retourne le prochain tier à ajouter lors de l'escalade.

        Args:
            current_tiers: Tiers actuellement autorisés

        Returns:
            Prochain tier à ajouter, ou None si escalade impossible
        """
        for tier in self.config.escalation_order:
            if tier not in current_tiers:
                return tier
        return None

    def create_escalation_result(self) -> EscalationResult:
        """
        Crée un nouveau résultat d'escalade.

        Returns:
            EscalationResult initialisé avec les tiers de départ
        """
        return EscalationResult(
            current_tiers=self.config.allowed_tiers.copy(),
            escalation_step=0,
        )

    def should_fallback_to_anchored(
        self,
        escalation_result: EscalationResult,
    ) -> bool:
        """
        Détermine si le fallback vers ANCHORED doit être utilisé.

        Args:
            escalation_result: Résultat de l'escalade

        Returns:
            True si fallback vers ANCHORED recommandé
        """
        if not self.config.fallback_to_anchored:
            return False

        if escalation_result.found_results:
            return False

        # Fallback si toutes les escalades ont été tentées sans succès
        if escalation_result.escalation_step >= self.config.max_escalation_steps:
            return True

        return False


# =============================================================================
# Anti-contamination: Règles de traversée sémantique
# =============================================================================

def validate_path_semantic_integrity(
    path_grades: List[SemanticGrade],
) -> Tuple[bool, Optional[str]]:
    """
    Valide l'intégrité sémantique d'un chemin.

    Règle anti-contamination: Pas de transitivité EXPLICIT→DISCURSIVE→?
    Un chemin ne doit pas mélanger EXPLICIT et DISCURSIVE de manière
    à propager une inférence discursive via une chaîne explicite.

    Args:
        path_grades: Liste des SemanticGrade des edges du chemin

    Returns:
        Tuple (is_valid, warning_message)
    """
    if not path_grades:
        return True, None

    # Vérifier la présence de transitions problématiques
    has_explicit = SemanticGrade.EXPLICIT in path_grades
    has_discursive = SemanticGrade.DISCURSIVE in path_grades

    if has_explicit and has_discursive:
        # Chemin mixte: avertissement mais pas rejet
        # (la traversée est permise mais doit être tracée)
        return True, (
            "Mixed path: contains both EXPLICIT and DISCURSIVE edges. "
            "Inference chain may include reconstructed relations."
        )

    return True, None


def compute_path_tier(
    edge_tiers: List[DefensibilityTier],
) -> DefensibilityTier:
    """
    Calcule le tier effectif d'un chemin.

    Le tier d'un chemin est le tier le plus faible de ses edges.
    (STRICT < EXTENDED < EXPERIMENTAL)

    Args:
        edge_tiers: Liste des DefensibilityTier des edges

    Returns:
        Tier effectif du chemin
    """
    if not edge_tiers:
        return DefensibilityTier.STRICT

    # Ordre de faiblesse
    tier_order = {
        DefensibilityTier.STRICT: 0,
        DefensibilityTier.EXTENDED: 1,
        DefensibilityTier.EXPERIMENTAL: 2,
    }

    max_weakness = max(tier_order.get(t, 0) for t in edge_tiers)

    for tier, order in tier_order.items():
        if order == max_weakness:
            return tier

    return DefensibilityTier.STRICT


# =============================================================================
# Singleton et factory
# =============================================================================

_tier_filter_services: dict = {}


def get_tier_filter_service(
    policy: TraversalPolicy = TraversalPolicy.STRICT,
    config: Optional[TierFilterConfig] = None,
) -> TierFilterService:
    """
    Retourne un service de filtrage par tier.

    Args:
        policy: Policy prédéfinie (ignorée si config fourni)
        config: Configuration custom (prioritaire sur policy)

    Returns:
        TierFilterService
    """
    if config is not None:
        return TierFilterService(config)

    cache_key = policy.value
    if cache_key not in _tier_filter_services:
        _tier_filter_services[cache_key] = TierFilterService.from_policy(policy)

    return _tier_filter_services[cache_key]


__all__ = [
    "TraversalPolicy",
    "TierFilterConfig",
    "EscalationResult",
    "TierFilterService",
    "get_tier_filter_service",
    "validate_path_semantic_integrity",
    "compute_path_tier",
]
