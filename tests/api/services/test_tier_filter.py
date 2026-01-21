"""
Tests pour le module tier_filter.py.

Tests du filtrage par DefensibilityTier au runtime:
- Configuration des policies
- Génération des clauses Cypher
- Logique d'escalade
- Validation de l'intégrité sémantique

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2026-01-21
"""

import pytest
from unittest.mock import MagicMock

from knowbase.relations.types import DefensibilityTier, SemanticGrade
from knowbase.api.services.tier_filter import (
    TraversalPolicy,
    TierFilterConfig,
    EscalationResult,
    TierFilterService,
    get_tier_filter_service,
    validate_path_semantic_integrity,
    compute_path_tier,
)


# =============================================================================
# Tests TraversalPolicy
# =============================================================================

class TestTraversalPolicy:
    """Tests pour les policies prédéfinies."""

    def test_strict_policy(self):
        """STRICT: Seulement tier STRICT, pas d'escalade."""
        config = TierFilterConfig.from_policy(TraversalPolicy.STRICT)

        assert config.allowed_tiers == {DefensibilityTier.STRICT}
        assert config.enable_escalation is False
        assert config.fallback_to_anchored is True

    def test_exploratory_policy(self):
        """EXPLORATORY: STRICT avec escalade vers EXTENDED."""
        config = TierFilterConfig.from_policy(TraversalPolicy.EXPLORATORY)

        assert config.allowed_tiers == {DefensibilityTier.STRICT}
        assert config.enable_escalation is True
        assert DefensibilityTier.STRICT in config.escalation_order
        assert DefensibilityTier.EXTENDED in config.escalation_order
        assert config.max_escalation_steps == 2

    def test_balanced_policy(self):
        """BALANCED: STRICT + EXTENDED directement."""
        config = TierFilterConfig.from_policy(TraversalPolicy.BALANCED)

        assert DefensibilityTier.STRICT in config.allowed_tiers
        assert DefensibilityTier.EXTENDED in config.allowed_tiers
        assert config.enable_escalation is False

    def test_unrestricted_policy(self):
        """UNRESTRICTED: Tous les tiers."""
        config = TierFilterConfig.from_policy(TraversalPolicy.UNRESTRICTED)

        assert DefensibilityTier.STRICT in config.allowed_tiers
        assert DefensibilityTier.EXTENDED in config.allowed_tiers
        assert DefensibilityTier.EXPERIMENTAL in config.allowed_tiers
        assert config.fallback_to_anchored is False


# =============================================================================
# Tests TierFilterService
# =============================================================================

class TestTierFilterService:
    """Tests pour le service de filtrage."""

    def test_get_tier_filter_clause_strict(self):
        """Génère clause Cypher pour STRICT uniquement."""
        service = TierFilterService.from_policy(TraversalPolicy.STRICT)
        clause = service.get_tier_filter_clause("r")

        assert "r.defensibility_tier" in clause
        assert "STRICT" in clause

    def test_get_tier_filter_clause_balanced(self):
        """Génère clause Cypher pour STRICT + EXTENDED."""
        service = TierFilterService.from_policy(TraversalPolicy.BALANCED)
        clause = service.get_tier_filter_clause("rel")

        assert "rel.defensibility_tier" in clause
        assert "STRICT" in clause
        assert "EXTENDED" in clause

    def test_get_tier_filter_clause_unrestricted(self):
        """UNRESTRICTED retourne 'true' (pas de filtrage)."""
        service = TierFilterService.from_policy(TraversalPolicy.UNRESTRICTED)
        clause = service.get_tier_filter_clause("r")

        assert clause == "true"

    def test_get_tier_filter_clause_with_fallback(self):
        """Clause avec fallback pour relations sans tier."""
        service = TierFilterService.from_policy(TraversalPolicy.STRICT)
        clause = service.get_tier_filter_clause_with_fallback("r")

        # Doit inclure IS NULL pour backward compatibility
        assert "IS NULL" in clause
        assert "STRICT" in clause


# =============================================================================
# Tests Escalation
# =============================================================================

class TestEscalation:
    """Tests pour la logique d'escalade."""

    def test_should_escalate_when_no_results(self):
        """Doit escalader si pas de résultats et escalade activée."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        assert service.should_escalate(results_count=0, current_step=0) is True
        assert service.should_escalate(results_count=0, current_step=1) is True

    def test_should_not_escalate_when_results_found(self):
        """Ne doit pas escalader si résultats trouvés."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        assert service.should_escalate(results_count=5, current_step=0) is False

    def test_should_not_escalate_when_max_reached(self):
        """Ne doit pas escalader si max_steps atteint."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        assert service.should_escalate(results_count=0, current_step=2) is False

    def test_should_not_escalate_when_disabled(self):
        """Ne doit pas escalader si escalade désactivée."""
        service = TierFilterService.from_policy(TraversalPolicy.STRICT)

        assert service.should_escalate(results_count=0, current_step=0) is False

    def test_get_next_escalation_tier(self):
        """Retourne le prochain tier dans l'ordre d'escalade."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        # Départ: STRICT uniquement
        current = {DefensibilityTier.STRICT}
        next_tier = service.get_next_escalation_tier(current)

        assert next_tier == DefensibilityTier.EXTENDED

    def test_get_next_escalation_tier_none_when_all_used(self):
        """Retourne None si tous les tiers sont déjà utilisés."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        # Tous les tiers de l'ordre d'escalade sont déjà utilisés
        current = {DefensibilityTier.STRICT, DefensibilityTier.EXTENDED}
        next_tier = service.get_next_escalation_tier(current)

        assert next_tier is None

    def test_escalation_result_add_escalation(self):
        """EscalationResult enregistre les escalades."""
        result = EscalationResult(
            current_tiers={DefensibilityTier.STRICT}
        )

        result.add_escalation(DefensibilityTier.EXTENDED)

        assert DefensibilityTier.EXTENDED in result.current_tiers
        assert result.escalation_step == 1
        assert "EXTENDED" in result.escalation_path[0]

    def test_escalation_result_audit_trail(self):
        """EscalationResult génère un audit trail."""
        result = EscalationResult(
            current_tiers={DefensibilityTier.STRICT, DefensibilityTier.EXTENDED},
            escalation_step=1,
            escalation_path=["escalate_to_EXTENDED"],
            final_mode="REASONED",
        )

        audit = result.to_audit_trail()

        assert "STRICT" in audit["tiers_used"]
        assert "EXTENDED" in audit["tiers_used"]
        assert audit["escalation_steps"] == 1
        assert audit["final_mode"] == "REASONED"


# =============================================================================
# Tests Fallback to Anchored
# =============================================================================

class TestFallbackToAnchored:
    """Tests pour le fallback vers ANCHORED."""

    def test_should_fallback_after_max_escalation(self):
        """Doit fallback après max_escalation_steps."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        result = EscalationResult(
            current_tiers={DefensibilityTier.STRICT, DefensibilityTier.EXTENDED},
            escalation_step=2,
            found_results=False,
        )

        assert service.should_fallback_to_anchored(result) is True

    def test_should_not_fallback_when_results_found(self):
        """Ne doit pas fallback si résultats trouvés."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)

        result = EscalationResult(
            current_tiers={DefensibilityTier.STRICT},
            escalation_step=2,
            found_results=True,
        )

        assert service.should_fallback_to_anchored(result) is False

    def test_should_not_fallback_when_disabled(self):
        """Ne doit pas fallback si désactivé."""
        service = TierFilterService.from_policy(TraversalPolicy.UNRESTRICTED)

        result = EscalationResult(
            current_tiers={DefensibilityTier.STRICT},
            escalation_step=5,
            found_results=False,
        )

        assert service.should_fallback_to_anchored(result) is False


# =============================================================================
# Tests Path Integrity & Tier Computation
# =============================================================================

class TestPathIntegrity:
    """Tests pour la validation de l'intégrité des chemins."""

    def test_pure_explicit_path_valid(self):
        """Chemin entièrement EXPLICIT est valide sans warning."""
        grades = [SemanticGrade.EXPLICIT, SemanticGrade.EXPLICIT]

        is_valid, warning = validate_path_semantic_integrity(grades)

        assert is_valid is True
        assert warning is None

    def test_pure_discursive_path_valid(self):
        """Chemin entièrement DISCURSIVE est valide sans warning."""
        grades = [SemanticGrade.DISCURSIVE, SemanticGrade.DISCURSIVE]

        is_valid, warning = validate_path_semantic_integrity(grades)

        assert is_valid is True
        assert warning is None

    def test_mixed_path_valid_with_warning(self):
        """Chemin mixte est valide mais avec warning."""
        grades = [SemanticGrade.EXPLICIT, SemanticGrade.DISCURSIVE]

        is_valid, warning = validate_path_semantic_integrity(grades)

        assert is_valid is True
        assert warning is not None
        assert "mixed" in warning.lower() or "Mixed" in warning

    def test_empty_path_valid(self):
        """Chemin vide est valide."""
        is_valid, warning = validate_path_semantic_integrity([])

        assert is_valid is True
        assert warning is None


class TestComputePathTier:
    """Tests pour le calcul du tier effectif d'un chemin."""

    def test_all_strict_returns_strict(self):
        """Chemin avec tous STRICT retourne STRICT."""
        tiers = [DefensibilityTier.STRICT, DefensibilityTier.STRICT]

        result = compute_path_tier(tiers)

        assert result == DefensibilityTier.STRICT

    def test_one_extended_returns_extended(self):
        """Chemin avec un EXTENDED retourne EXTENDED."""
        tiers = [DefensibilityTier.STRICT, DefensibilityTier.EXTENDED]

        result = compute_path_tier(tiers)

        assert result == DefensibilityTier.EXTENDED

    def test_one_experimental_returns_experimental(self):
        """Chemin avec un EXPERIMENTAL retourne EXPERIMENTAL."""
        tiers = [
            DefensibilityTier.STRICT,
            DefensibilityTier.EXTENDED,
            DefensibilityTier.EXPERIMENTAL,
        ]

        result = compute_path_tier(tiers)

        assert result == DefensibilityTier.EXPERIMENTAL

    def test_empty_path_returns_strict(self):
        """Chemin vide retourne STRICT par défaut."""
        result = compute_path_tier([])

        assert result == DefensibilityTier.STRICT


# =============================================================================
# Tests Factory
# =============================================================================

class TestFactory:
    """Tests pour les fonctions factory."""

    def test_get_tier_filter_service_caches_by_policy(self):
        """get_tier_filter_service met en cache par policy."""
        s1 = get_tier_filter_service(policy=TraversalPolicy.STRICT)
        s2 = get_tier_filter_service(policy=TraversalPolicy.STRICT)

        assert s1 is s2

    def test_get_tier_filter_service_different_policies(self):
        """Différentes policies = différentes instances."""
        s1 = get_tier_filter_service(policy=TraversalPolicy.STRICT)
        s2 = get_tier_filter_service(policy=TraversalPolicy.EXPLORATORY)

        assert s1 is not s2

    def test_get_tier_filter_service_custom_config(self):
        """Config custom crée une nouvelle instance."""
        custom_config = TierFilterConfig(
            allowed_tiers={DefensibilityTier.EXTENDED},
            enable_escalation=True,
        )

        service = get_tier_filter_service(config=custom_config)

        assert DefensibilityTier.EXTENDED in service.config.allowed_tiers
        assert DefensibilityTier.STRICT not in service.config.allowed_tiers


# =============================================================================
# Tests Integration
# =============================================================================

class TestIntegration:
    """Tests d'intégration du workflow complet."""

    def test_full_escalation_workflow(self):
        """Workflow complet: STRICT → EXTENDED → fallback."""
        service = TierFilterService.from_policy(TraversalPolicy.EXPLORATORY)
        escalation = service.create_escalation_result()

        # Étape 1: STRICT, pas de résultats
        assert escalation.current_tiers == {DefensibilityTier.STRICT}
        assert service.should_escalate(results_count=0, current_step=0) is True

        # Escalade vers EXTENDED
        next_tier = service.get_next_escalation_tier(escalation.current_tiers)
        assert next_tier == DefensibilityTier.EXTENDED
        escalation.add_escalation(next_tier)

        # Étape 2: STRICT + EXTENDED, toujours pas de résultats
        assert DefensibilityTier.EXTENDED in escalation.current_tiers
        assert service.should_escalate(results_count=0, current_step=1) is True

        # Pas d'autre tier à ajouter
        next_tier = service.get_next_escalation_tier(escalation.current_tiers)
        assert next_tier is None

        # Simuler max_steps atteint
        escalation.escalation_step = 2

        # Fallback vers ANCHORED
        assert service.should_fallback_to_anchored(escalation) is True
