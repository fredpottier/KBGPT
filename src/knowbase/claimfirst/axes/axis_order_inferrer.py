# src/knowbase/claimfirst/axes/axis_order_inferrer.py
"""
AxisOrderInferrer - Inférence du type d'ordre pour un axe d'applicabilité.

INV-14: Si inconnu, value_order = None (jamais inventer un ordre)

Cas d'inférence:
- CERTAIN: Numériques, années, semver
- INFERRED: Patterns ordinaux (Phase I/II/III, Early/Late)
- UNKNOWN: L'axe semble orderable mais l'ordre est inconnu
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from knowbase.claimfirst.models.applicability_axis import (
    OrderingConfidence,
    OrderType,
)

logger = logging.getLogger(__name__)


@dataclass
class OrderInferenceResult:
    """
    Résultat de l'inférence d'ordre pour un axe.

    Attributes:
        is_orderable: Si l'axe est orderable
        order_type: Type d'ordre (total, partial, none)
        confidence: Niveau de confiance
        inferred_order: Ordre inféré (None si UNKNOWN - INV-14)
        reason: Explication du résultat
    """
    is_orderable: bool
    order_type: OrderType
    confidence: OrderingConfidence
    inferred_order: Optional[List[str]]  # None si UNKNOWN (INV-14)
    reason: str


# Patterns pour versions semver (1.0, 2.1.3, etc.)
SEMVER_PATTERN = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")

# Patterns pour années
YEAR_PATTERN = re.compile(r"^(19|20)\d{2}$")

# Patterns pour années SAP style (2021, 2021 FPS01)
SAP_YEAR_PATTERN = re.compile(r"^(20\d{2})(?:\s*FPS(\d+))?$")

# Patterns ordinaux romains
ROMAN_NUMERAL_PATTERN = re.compile(r"^(I{1,3}|IV|V|VI{1,3}|IX|X)$", re.IGNORECASE)
ROMAN_VALUES = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}

# Patterns ordinaux textuels
ORDINAL_WORDS = {
    "one": 1, "first": 1, "1st": 1,
    "two": 2, "second": 2, "2nd": 2,
    "three": 3, "third": 3, "3rd": 3,
    "four": 4, "fourth": 4, "4th": 4,
    "five": 5, "fifth": 5, "5th": 5,
    "early": 1, "initial": 1,
    "late": 99, "final": 99,
}

# Éditions connues avec ordre
EDITION_ORDER = [
    "standard", "professional", "enterprise",
    "on-premise", "private", "public",
]


class AxisOrderInferrer:
    """
    Infère le type d'ordre pour les valeurs d'un axe.

    INV-14: Si l'ordre est inconnu, retourne inferred_order=None.
    Jamais inventer un ordre.
    """

    def infer_order(
        self,
        axis_key: str,
        values: List[str],
    ) -> OrderInferenceResult:
        """
        Infère l'ordre pour un ensemble de valeurs.

        Args:
            axis_key: Clé de l'axe (release_id, year, etc.)
            values: Valeurs à ordonner

        Returns:
            OrderInferenceResult avec l'ordre inféré (ou None si inconnu)
        """
        if not values:
            return OrderInferenceResult(
                is_orderable=False,
                order_type=OrderType.NONE,
                confidence=OrderingConfidence.UNKNOWN,
                inferred_order=None,
                reason="No values provided",
            )

        # Normaliser les valeurs
        normalized = [v.strip() for v in values if v.strip()]

        if len(normalized) < 2:
            # Une seule valeur = pas d'ordre à inférer
            return OrderInferenceResult(
                is_orderable=False,
                order_type=OrderType.NONE,
                confidence=OrderingConfidence.UNKNOWN,
                inferred_order=None,
                reason="Single value, no ordering possible",
            )

        # Essayer différentes stratégies d'inférence
        strategies = [
            (self._try_semver_order, "semver"),
            (self._try_year_order, "year"),
            (self._try_sap_year_order, "sap_year"),
            (self._try_numeric_order, "numeric"),
            (self._try_roman_order, "roman"),
            (self._try_ordinal_word_order, "ordinal_word"),
            (self._try_edition_order, "edition"),
        ]

        for strategy_func, strategy_name in strategies:
            result = strategy_func(normalized)
            if result.is_orderable and result.confidence != OrderingConfidence.UNKNOWN:
                logger.debug(
                    f"[OSMOSE:AxisOrderInferrer] {axis_key}: "
                    f"ordered via {strategy_name} ({result.confidence.value})"
                )
                return result

        # INV-14: Si aucune stratégie ne fonctionne, retourner UNKNOWN
        return OrderInferenceResult(
            is_orderable=False,
            order_type=OrderType.NONE,
            confidence=OrderingConfidence.UNKNOWN,
            inferred_order=None,  # INV-14: Jamais inventer
            reason="Could not determine ordering strategy",
        )

    def _try_semver_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme versions semver (1.0, 2.1.3, etc.).
        """
        parsed = []
        for v in values:
            match = SEMVER_PATTERN.match(v)
            if not match:
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values match semver pattern",
                )
            major = int(match.group(1))
            minor = int(match.group(2) or 0)
            patch = int(match.group(3) or 0)
            parsed.append((major, minor, patch, v))

        # Trier par composants numériques
        parsed.sort(key=lambda x: (x[0], x[1], x[2]))
        ordered = [p[3] for p in parsed]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.CERTAIN,
            inferred_order=ordered,
            reason="Semver ordering",
        )

    def _try_year_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme années (2020, 2021, 2022).
        """
        years = []
        for v in values:
            if not YEAR_PATTERN.match(v):
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values are years",
                )
            years.append((int(v), v))

        years.sort(key=lambda x: x[0])
        ordered = [y[1] for y in years]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.CERTAIN,
            inferred_order=ordered,
            reason="Year ordering",
        )

    def _try_sap_year_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme années SAP (2021, 2021 FPS01, 2021 FPS02).
        """
        parsed = []
        for v in values:
            match = SAP_YEAR_PATTERN.match(v)
            if not match:
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values match SAP year pattern",
                )
            year = int(match.group(1))
            fps = int(match.group(2)) if match.group(2) else 0
            parsed.append((year, fps, v))

        parsed.sort(key=lambda x: (x[0], x[1]))
        ordered = [p[2] for p in parsed]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.CERTAIN,
            inferred_order=ordered,
            reason="SAP year+FPS ordering",
        )

    def _try_numeric_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme nombres simples (1, 2, 3 ou 1.0, 2.0, 3.0).
        """
        numbers = []
        for v in values:
            try:
                num = float(v)
                numbers.append((num, v))
            except ValueError:
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values are numeric",
                )

        numbers.sort(key=lambda x: x[0])
        ordered = [n[1] for n in numbers]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.CERTAIN,
            inferred_order=ordered,
            reason="Numeric ordering",
        )

    def _try_roman_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme chiffres romains (I, II, III, IV...).
        """
        parsed = []
        for v in values:
            upper_v = v.upper()
            if upper_v not in ROMAN_VALUES:
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values are roman numerals",
                )
            parsed.append((ROMAN_VALUES[upper_v], v))

        parsed.sort(key=lambda x: x[0])
        ordered = [p[1] for p in parsed]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.INFERRED,  # Moins certain que numérique
            inferred_order=ordered,
            reason="Roman numeral ordering",
        )

    def _try_ordinal_word_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme mots ordinaux (first, second, early, late...).
        """
        parsed = []
        for v in values:
            lower_v = v.lower()
            if lower_v not in ORDINAL_WORDS:
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values are ordinal words",
                )
            parsed.append((ORDINAL_WORDS[lower_v], v))

        parsed.sort(key=lambda x: x[0])
        ordered = [p[1] for p in parsed]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.INFERRED,
            inferred_order=ordered,
            reason="Ordinal word ordering",
        )

    def _try_edition_order(self, values: List[str]) -> OrderInferenceResult:
        """
        Essaie d'ordonner comme éditions (standard < professional < enterprise).
        """
        # Vérifier si toutes les valeurs sont des éditions connues
        lower_values = [v.lower() for v in values]

        for lv in lower_values:
            if lv not in EDITION_ORDER:
                return OrderInferenceResult(
                    is_orderable=False,
                    order_type=OrderType.NONE,
                    confidence=OrderingConfidence.UNKNOWN,
                    inferred_order=None,
                    reason="Not all values are known editions",
                )

        # Créer mapping position → valeur originale
        positions = [(EDITION_ORDER.index(v.lower()), v) for v in values]
        positions.sort(key=lambda x: x[0])
        ordered = [p[1] for p in positions]

        return OrderInferenceResult(
            is_orderable=True,
            order_type=OrderType.TOTAL,
            confidence=OrderingConfidence.INFERRED,
            inferred_order=ordered,
            reason="Edition ordering",
        )


__all__ = [
    "AxisOrderInferrer",
    "OrderInferenceResult",
]
