"""
OSMOSE Verification - Comparison Engine

Moteur de comparaison déterministe basé sur une matrice de règles.
Compare ClaimForm vs ClaimForm et retourne un verdict structuré.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

import logging
from typing import Optional, Dict, Any

from knowbase.verification.comparison.reason_codes import ReasonCode
from knowbase.verification.comparison.truth_regimes import TruthRegime
from knowbase.verification.comparison.value_algebra import (
    Value,
    ScalarValue,
    IntervalValue,
    InequalityValue,
    SetValue,
    BooleanValue,
    VersionValue,
    TextValue,
    AuthorityLevel,
)
from knowbase.verification.comparison.claim_forms import ClaimForm, ClaimFormType
from knowbase.verification.comparison.aggregator import ComparisonResult, ComparisonExplanation

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """
    Moteur de comparaison déterministe.

    Compare deux ClaimForms et retourne un verdict structuré
    basé sur une matrice de règles prédéfinies.

    Usage:
        engine = ComparisonEngine()
        result = engine.compare(assertion_form, claim_form, tolerance=0.0)
    """

    def compare(
        self,
        assertion: ClaimForm,
        claim: ClaimForm,
        tolerance: float = 0.0
    ) -> ComparisonExplanation:
        """
        Compare une assertion contre un claim.

        Args:
            assertion: Forme structurée de l'assertion utilisateur
            claim: Forme structurée du claim de la KB
            tolerance: Tolérance relative pour la comparaison

        Returns:
            ComparisonExplanation avec résultat, raison et détails
        """
        # 1. Vérifier compatibilité des propriétés
        if not assertion.property_matches(claim):
            return ComparisonExplanation(
                result=ComparisonResult.UNKNOWN,
                reason_code=ReasonCode.PROPERTY_MISMATCH,
                confidence=0.3,
                details={
                    "assertion_prop": assertion.property_surface,
                    "claim_prop": claim.property_surface,
                    "assertion_key": assertion.claim_key,
                    "claim_key": claim.claim_key,
                }
            )

        # 2. Vérifier compatibilité des scopes
        if claim.has_scope() and not assertion.scope_matches(claim):
            # Claim a un scope, assertion ne matche pas
            if not assertion.has_scope():
                # Assertion n'a pas de scope → NEEDS_SCOPE
                return ComparisonExplanation(
                    result=ComparisonResult.NEEDS_SCOPE,
                    reason_code=ReasonCode.SCOPE_MISSING,
                    confidence=0.5,
                    details={
                        "scope_key": ", ".join(claim.get_scope_keys()),
                        "claim_scope": {
                            "version": claim.scope_version,
                            "region": claim.scope_region,
                            "edition": claim.scope_edition,
                        }
                    }
                )
            else:
                # Les deux ont des scopes mais différents
                return ComparisonExplanation(
                    result=ComparisonResult.UNKNOWN,
                    reason_code=ReasonCode.SCOPE_MISMATCH,
                    confidence=0.4,
                    details={
                        "assertion_scope": {
                            "version": assertion.scope_version,
                            "region": assertion.scope_region,
                            "edition": assertion.scope_edition,
                        },
                        "claim_scope": {
                            "version": claim.scope_version,
                            "region": claim.scope_region,
                            "edition": claim.scope_edition,
                        }
                    }
                )

        # 3. Vérifier compatibilité des unités
        if not assertion.value.is_compatible_unit(claim.value):
            return ComparisonExplanation(
                result=ComparisonResult.UNKNOWN,
                reason_code=ReasonCode.UNIT_MISMATCH,
                confidence=0.3,
                details={
                    "assertion_unit": assertion.value.unit,
                    "claim_unit": claim.value.unit,
                }
            )

        # 4. Dispatch selon les types de valeurs
        return self._compare_values(
            assertion.value,
            claim.value,
            tolerance
        )

    def _compare_values(
        self,
        assertion_value: Value,
        claim_value: Value,
        tolerance: float
    ) -> ComparisonExplanation:
        """
        Compare deux valeurs selon leurs types.

        Dispatch vers la méthode spécifique selon la combinaison de types.
        """
        a_type = type(assertion_value).__name__
        c_type = type(claim_value).__name__

        # Matrice de dispatch
        dispatch_key = (a_type, c_type)

        dispatch_map = {
            # Scalar vs X
            ("ScalarValue", "ScalarValue"): self._compare_scalar_scalar,
            ("ScalarValue", "IntervalValue"): self._compare_scalar_interval,
            ("ScalarValue", "SetValue"): self._compare_scalar_set,
            ("ScalarValue", "InequalityValue"): self._compare_scalar_inequality,

            # Interval vs X
            ("IntervalValue", "IntervalValue"): self._compare_interval_interval,
            ("IntervalValue", "ScalarValue"): self._compare_interval_scalar,

            # Set vs X
            ("SetValue", "SetValue"): self._compare_set_set,
            ("SetValue", "ScalarValue"): self._compare_set_scalar,

            # Inequality vs X
            ("InequalityValue", "InequalityValue"): self._compare_inequality_inequality,
            ("InequalityValue", "ScalarValue"): self._compare_inequality_scalar,

            # Boolean
            ("BooleanValue", "BooleanValue"): self._compare_boolean_boolean,

            # Version
            ("VersionValue", "VersionValue"): self._compare_version_version,

            # Text fallback
            ("TextValue", "TextValue"): self._compare_text_text,
        }

        compare_fn = dispatch_map.get(dispatch_key)

        if compare_fn:
            return compare_fn(assertion_value, claim_value, tolerance)

        # Types incompatibles
        return ComparisonExplanation(
            result=ComparisonResult.UNKNOWN,
            reason_code=ReasonCode.INCOMPATIBLE_TYPES,
            confidence=0.3,
            details={
                "assertion_type": a_type,
                "claim_type": c_type,
            }
        )

    # ========== Scalar comparisons ==========

    def _compare_scalar_scalar(
        self,
        a: ScalarValue,
        c: ScalarValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Scalar vs Scalar."""
        if a.equals(c, tolerance):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.EXACT_MATCH if tolerance == 0 else ReasonCode.EQUIVALENT_MATCH,
                confidence=1.0,
                details={"value": a.to_canonical()}
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VALUE_OUTSIDE_INTERVAL,  # Scalar outside "interval" of claim
                confidence=1.0,
                details={
                    "assertion_value": a.value,
                    "claim_value": c.value,
                    "unit": a.unit or c.unit,
                }
            )

    def _compare_scalar_interval(
        self,
        a: ScalarValue,
        c: IntervalValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Scalar vs Interval: est-ce que le scalaire est dans l'intervalle?"""
        if c.contains(a):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.VALUE_IN_INTERVAL,
                confidence=1.0,
                details={
                    "value": a.value,
                    "low": c.low,
                    "high": c.high,
                    "unit": a.unit or c.unit,
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VALUE_OUTSIDE_INTERVAL,
                confidence=1.0,
                details={
                    "value": a.value,
                    "low": c.low,
                    "high": c.high,
                    "unit": a.unit or c.unit,
                }
            )

    def _compare_scalar_set(
        self,
        a: ScalarValue,
        c: SetValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Scalar vs Set: le scalaire est-il dans le set? Manque-t-il des valeurs?"""
        if c.contains(a):
            # La valeur est valide, mais l'assertion ne couvre qu'une partie du set
            missing = c.get_missing_values({a.value})
            if missing:
                return ComparisonExplanation(
                    result=ComparisonResult.PARTIAL,
                    reason_code=ReasonCode.VALUE_IN_SET_INCOMPLETE,
                    confidence=0.9,
                    details={
                        "value": a.value,
                        "set_values": sorted(c.values, key=str),
                        "missing": sorted(missing, key=str),
                        "unit": a.unit or c.unit,
                    }
                )
            else:
                # Set à une seule valeur, match complet
                return ComparisonExplanation(
                    result=ComparisonResult.SUPPORTS,
                    reason_code=ReasonCode.VALUE_IN_SET,
                    confidence=1.0,
                    details={
                        "value": a.value,
                        "set_values": sorted(c.values, key=str),
                        "unit": a.unit or c.unit,
                    }
                )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VALUE_NOT_IN_SET,
                confidence=1.0,
                details={
                    "value": a.value,
                    "set_values": sorted(c.values, key=str),
                    "unit": a.unit or c.unit,
                }
            )

    def _compare_scalar_inequality(
        self,
        a: ScalarValue,
        c: InequalityValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Scalar vs Inequality: le scalaire satisfait-il l'inégalité?"""
        if c.contains(a):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.SATISFIES_INEQUALITY,
                confidence=1.0,
                details={
                    "value": a.value,
                    "operator": c.operator,
                    "bound": c.bound,
                    "unit": a.unit or c.unit,
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VIOLATES_INEQUALITY,
                confidence=1.0,
                details={
                    "value": a.value,
                    "operator": c.operator,
                    "bound": c.bound,
                    "unit": a.unit or c.unit,
                }
            )

    # ========== Interval comparisons ==========

    def _compare_interval_interval(
        self,
        a: IntervalValue,
        c: IntervalValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Interval vs Interval."""
        if a.equals(c, tolerance):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.EXACT_MATCH,
                confidence=1.0,
                details={
                    "a_low": a.low,
                    "a_high": a.high,
                    "c_low": c.low,
                    "c_high": c.high,
                    "unit": a.unit or c.unit,
                }
            )
        elif a.overlaps(c):
            return ComparisonExplanation(
                result=ComparisonResult.PARTIAL,
                reason_code=ReasonCode.INTERVALS_OVERLAP,
                confidence=0.8,
                details={
                    "a_low": a.low,
                    "a_high": a.high,
                    "c_low": c.low,
                    "c_high": c.high,
                    "unit": a.unit or c.unit,
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.INTERVALS_DISJOINT,
                confidence=1.0,
                details={
                    "a_low": a.low,
                    "a_high": a.high,
                    "c_low": c.low,
                    "c_high": c.high,
                    "unit": a.unit or c.unit,
                }
            )

    def _compare_interval_scalar(
        self,
        a: IntervalValue,
        c: ScalarValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Interval vs Scalar: l'assertion est plus large que le claim."""
        if a.contains(c):
            # L'assertion (intervalle) contient le claim (scalaire) = PARTIAL
            # L'assertion est trop vague
            return ComparisonExplanation(
                result=ComparisonResult.PARTIAL,
                reason_code=ReasonCode.VALUE_IN_INTERVAL,
                confidence=0.7,
                details={
                    "assertion_low": a.low,
                    "assertion_high": a.high,
                    "claim_value": c.value,
                    "unit": a.unit or c.unit,
                    "note": "Assertion plus large que le claim exact"
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VALUE_OUTSIDE_INTERVAL,
                confidence=1.0,
                details={
                    "assertion_low": a.low,
                    "assertion_high": a.high,
                    "claim_value": c.value,
                    "unit": a.unit or c.unit,
                }
            )

    # ========== Set comparisons ==========

    def _compare_set_set(
        self,
        a: SetValue,
        c: SetValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Set vs Set."""
        if a.equals(c):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.SETS_EQUAL,
                confidence=1.0,
                details={"set_values": sorted(a.values, key=str)}
            )

        if a.values.issubset(c.values):
            missing = c.values - a.values
            return ComparisonExplanation(
                result=ComparisonResult.PARTIAL,
                reason_code=ReasonCode.SET_SUBSET,
                confidence=0.8,
                details={
                    "assertion_set": sorted(a.values, key=str),
                    "claim_set": sorted(c.values, key=str),
                    "missing": sorted(missing, key=str),
                }
            )

        common = a.values & c.values
        if common:
            return ComparisonExplanation(
                result=ComparisonResult.PARTIAL,
                reason_code=ReasonCode.SETS_OVERLAP,
                confidence=0.6,
                details={
                    "assertion_set": sorted(a.values, key=str),
                    "claim_set": sorted(c.values, key=str),
                    "common": sorted(common, key=str),
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.SETS_DISJOINT,
                confidence=1.0,
                details={
                    "assertion_set": sorted(a.values, key=str),
                    "claim_set": sorted(c.values, key=str),
                }
            )

    def _compare_set_scalar(
        self,
        a: SetValue,
        c: ScalarValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Set (assertion) vs Scalar (claim)."""
        if a.contains(c):
            if len(a.values) > 1:
                # L'assertion propose plusieurs options, le claim en indique une
                return ComparisonExplanation(
                    result=ComparisonResult.PARTIAL,
                    reason_code=ReasonCode.VALUE_IN_SET_INCOMPLETE,
                    confidence=0.7,
                    details={
                        "assertion_set": sorted(a.values, key=str),
                        "claim_value": c.value,
                    }
                )
            else:
                return ComparisonExplanation(
                    result=ComparisonResult.SUPPORTS,
                    reason_code=ReasonCode.VALUE_IN_SET,
                    confidence=1.0,
                    details={
                        "assertion_set": sorted(a.values, key=str),
                        "claim_value": c.value,
                    }
                )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VALUE_NOT_IN_SET,
                confidence=1.0,
                details={
                    "assertion_set": sorted(a.values, key=str),
                    "claim_value": c.value,
                }
            )

    # ========== Inequality comparisons ==========

    def _compare_inequality_inequality(
        self,
        a: InequalityValue,
        c: InequalityValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Inequality vs Inequality."""
        if a.equals(c, tolerance):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.EXACT_MATCH,
                confidence=1.0,
                details={
                    "operator": a.operator,
                    "bound": a.bound,
                    "unit": a.unit or c.unit,
                }
            )

        # Vérifier implication
        if c.contains(a):
            # Le claim est plus permissif que l'assertion
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.SATISFIES_INEQUALITY,
                confidence=0.9,
                details={
                    "assertion_op": a.operator,
                    "assertion_bound": a.bound,
                    "claim_op": c.operator,
                    "claim_bound": c.bound,
                }
            )

        return ComparisonExplanation(
            result=ComparisonResult.CONTRADICTS,
            reason_code=ReasonCode.VIOLATES_INEQUALITY,
            confidence=0.9,
            details={
                "assertion_op": a.operator,
                "assertion_bound": a.bound,
                "claim_op": c.operator,
                "claim_bound": c.bound,
            }
        )

    def _compare_inequality_scalar(
        self,
        a: InequalityValue,
        c: ScalarValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Inequality (assertion) vs Scalar (claim)."""
        # L'assertion dit "≤30" et le claim dit "30"
        if a.contains(c):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.SATISFIES_INEQUALITY,
                confidence=0.9,
                details={
                    "operator": a.operator,
                    "bound": a.bound,
                    "claim_value": c.value,
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VIOLATES_INEQUALITY,
                confidence=1.0,
                details={
                    "operator": a.operator,
                    "bound": a.bound,
                    "claim_value": c.value,
                }
            )

    # ========== Boolean comparisons ==========

    def _compare_boolean_boolean(
        self,
        a: BooleanValue,
        c: BooleanValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Boolean vs Boolean."""
        if a.equals(c):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.BOOLEAN_MATCH,
                confidence=1.0,
                details={"value": a.value}
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.BOOLEAN_MISMATCH,
                confidence=1.0,
                details={
                    "assertion": a.value,
                    "claim": c.value,
                }
            )

    # ========== Version comparisons ==========

    def _compare_version_version(
        self,
        a: VersionValue,
        c: VersionValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Version vs Version."""
        if a.equals(c):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.VERSION_MATCH,
                confidence=1.0,
                details={"version": a.to_canonical()}
            )

        if a.is_compatible_with(c):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.VERSION_COMPATIBLE,
                confidence=0.9,
                details={
                    "assertion_version": a.to_canonical(),
                    "claim_version": c.to_canonical(),
                }
            )
        else:
            return ComparisonExplanation(
                result=ComparisonResult.CONTRADICTS,
                reason_code=ReasonCode.VERSION_MISMATCH,
                confidence=1.0,
                details={
                    "assertion_version": a.to_canonical(),
                    "claim_version": c.to_canonical(),
                }
            )

    # ========== Text fallback ==========

    def _compare_text_text(
        self,
        a: TextValue,
        c: TextValue,
        tolerance: float
    ) -> ComparisonExplanation:
        """Text vs Text - requires LLM fallback."""
        # Comparaison basique
        if a.equals(c):
            return ComparisonExplanation(
                result=ComparisonResult.SUPPORTS,
                reason_code=ReasonCode.EXACT_MATCH,
                confidence=0.9,
                details={"text": a.text[:100]}
            )

        # Sinon, indique qu'il faut un fallback LLM
        return ComparisonExplanation(
            result=ComparisonResult.UNKNOWN,
            reason_code=ReasonCode.LLM_CLASSIFICATION,
            confidence=0.5,
            details={
                "assertion_text": a.text[:200],
                "claim_text": c.text[:200],
                "requires_llm": True,
            }
        )
