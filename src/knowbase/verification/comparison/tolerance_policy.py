"""
OSMOSE Verification - Tolerance Policy

Calcul dynamique de la tolérance pour comparaison.
La tolérance dépend du type de valeur, unité, régime et autorité.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

from dataclasses import dataclass
from typing import Optional

from knowbase.verification.comparison.truth_regimes import TruthRegime
from knowbase.verification.comparison.value_algebra import AuthorityLevel


@dataclass
class ToleranceConfig:
    """Configuration des tolérances par type de valeur."""

    # Pourcentages (SLA, etc.)
    percent_tolerance: float = 0.01  # 1% relatif

    # Durées (RPO, RTO, latence)
    duration_tolerance: float = 0.05  # 5% relatif

    # Valeurs génériques
    default_tolerance: float = 0.02  # 2% relatif

    # Valeurs JAMAIS tolérantes
    strict_value_kinds: set = None

    def __post_init__(self):
        if self.strict_value_kinds is None:
            self.strict_value_kinds = {
                "p_value",
                "statistical",
                "ci",  # Confidence interval
                "version",
                "boolean",
            }


class TolerancePolicy:
    """
    Calcule la tolérance appropriée pour une comparaison.

    Règles:
    1. HIGH authority → toujours strict (0 tolérance)
    2. Seulement DESCRIPTIVE_APPROX permet tolérance
    3. Certains types (p-value, CI) sont toujours stricts
    4. La tolérance dépend du type de valeur et unité

    Usage:
        policy = TolerancePolicy()
        tolerance = policy.get_tolerance(
            value_kind="ScalarValue",
            unit="%",
            regime=TruthRegime.DESCRIPTIVE_APPROX,
            authority=AuthorityLevel.MEDIUM
        )
    """

    def __init__(self, config: Optional[ToleranceConfig] = None):
        self.config = config or ToleranceConfig()

    def get_tolerance(
        self,
        value_kind: str,
        unit: Optional[str],
        regime: TruthRegime,
        authority: AuthorityLevel,
        hedge_strength: float = 0.0
    ) -> float:
        """
        Calcule la tolérance pour une comparaison.

        Args:
            value_kind: Nom de la classe Value (e.g., "ScalarValue")
            unit: Unité de la valeur (e.g., "%", "min")
            regime: Régime de vérité
            authority: Niveau d'autorité de la source
            hedge_strength: Force du hedge (0 = certain, 1 = très incertain)

        Returns:
            Tolérance relative (0.0 = strict, 0.05 = 5%, etc.)
        """
        # Règle 1: HIGH authority = toujours strict
        if authority == AuthorityLevel.HIGH:
            return 0.0

        # Règle 2: Seulement DESCRIPTIVE_APPROX permet tolérance
        if regime != TruthRegime.DESCRIPTIVE_APPROX:
            return 0.0

        # Règle 3: Certains types sont toujours stricts
        unit_lower = (unit or "").lower()
        if unit_lower in self.config.strict_value_kinds:
            return 0.0

        # Règle 4: Tolérance selon type de valeur et unité
        base_tolerance = self._get_base_tolerance(value_kind, unit)

        # Ajuster selon hedge strength (plus d'incertitude = plus de tolérance)
        if hedge_strength > 0:
            # Augmenter tolérance jusqu'à 50% pour hedges forts
            adjustment = 1.0 + (hedge_strength * 0.5)
            base_tolerance *= adjustment

        return min(base_tolerance, 0.10)  # Cap à 10% max

    def _get_base_tolerance(self, value_kind: str, unit: Optional[str]) -> float:
        """Détermine la tolérance de base selon le type et l'unité."""
        unit_lower = (unit or "").lower()

        # Pourcentages
        if unit_lower in {"%", "percent", "pourcent"}:
            return self.config.percent_tolerance

        # Durées
        if unit_lower in {"min", "minutes", "h", "hours", "s", "seconds", "ms", "d", "days"}:
            return self.config.duration_tolerance

        # Par type de valeur
        if value_kind == "BooleanValue":
            return 0.0  # Booléen = toujours strict

        if value_kind == "VersionValue":
            return 0.0  # Version = toujours strict

        if value_kind in {"IntervalValue", "InequalityValue"}:
            # Les intervalles/inégalités ont déjà une marge intégrée
            return self.config.default_tolerance * 0.5

        return self.config.default_tolerance

    def is_strict_comparison(
        self,
        regime: TruthRegime,
        authority: AuthorityLevel
    ) -> bool:
        """
        Vérifie si la comparaison doit être stricte.

        Utile pour décider rapidement sans calculer la tolérance.
        """
        if authority == AuthorityLevel.HIGH:
            return True

        strict_regimes = {
            TruthRegime.NORMATIVE_STRICT,
            TruthRegime.NORMATIVE_BOUNDED,
            TruthRegime.EMPIRICAL_STATISTICAL,
        }

        return regime in strict_regimes

    def explain_tolerance(
        self,
        value_kind: str,
        unit: Optional[str],
        regime: TruthRegime,
        authority: AuthorityLevel,
        hedge_strength: float = 0.0
    ) -> dict:
        """
        Explique le calcul de tolérance pour debug/transparence.

        Returns:
            Dict avec tolerance et raisons
        """
        tolerance = self.get_tolerance(
            value_kind, unit, regime, authority, hedge_strength
        )

        reasons = []

        if authority == AuthorityLevel.HIGH:
            reasons.append("Source haute autorité → strict")
        elif regime != TruthRegime.DESCRIPTIVE_APPROX:
            reasons.append(f"Régime {regime.value} → strict")
        else:
            reasons.append(f"Régime approximatif → tolérance {tolerance*100:.1f}%")

            if (unit or "").lower() in {"%", "percent"}:
                reasons.append("Pourcentage → tolérance réduite")
            elif (unit or "").lower() in {"min", "h", "s"}:
                reasons.append("Durée → tolérance standard")

            if hedge_strength > 0:
                reasons.append(f"Hedge strength {hedge_strength:.2f} → ajustement")

        return {
            "tolerance": tolerance,
            "is_strict": tolerance == 0.0,
            "reasons": reasons,
            "inputs": {
                "value_kind": value_kind,
                "unit": unit,
                "regime": regime.value,
                "authority": authority.value,
                "hedge_strength": hedge_strength,
            }
        }
