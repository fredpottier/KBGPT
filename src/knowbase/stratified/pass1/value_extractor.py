# src/knowbase/stratified/pass1/value_extractor.py
"""
Extracteur de valeurs bornées pour MVP V1.
Types supportés: number, percent, version, enum, boolean.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
import re
from typing import Optional

from ..models.information import ValueInfo, ValueKind, ValueComparable


class ValueExtractor:
    """
    Extracteur de valeurs bornées.

    Extrait et normalise les valeurs depuis le texte.
    MVP V1: number, percent, version, enum, boolean uniquement.
    """

    def extract(self, text: str) -> Optional[ValueInfo]:
        """
        Extrait et normalise une valeur depuis le texte.

        Args:
            text: Texte à analyser

        Returns:
            ValueInfo ou None si pas de valeur détectée
        """
        text_lower = text.lower().strip()

        # Tenter chaque extracteur dans l'ordre de spécificité
        extractors = [
            self._extract_percent,
            self._extract_version,
            self._extract_number_with_unit,
            self._extract_boolean,
            self._extract_enum,
        ]

        for extractor in extractors:
            result = extractor(text_lower, text)
            if result:
                return result

        return None

    def _extract_percent(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait un pourcentage."""
        patterns = [
            r"(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*percent",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                raw_value = match.group(1)
                normalized = float(raw_value) / 100.0
                return ValueInfo(
                    kind=ValueKind.PERCENT,
                    raw=f"{raw_value}%",
                    normalized=normalized,
                    unit="%",
                    operator="=",
                    comparable=ValueComparable.STRICT
                )
        return None

    def _extract_version(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait une version."""
        patterns = [
            (r"(?:tls|ssl)\s*(\d+(?:\.\d+)?)", "tls"),
            (r"(?:v|version\s*)(\d+(?:\.\d+)*)", "version"),
            (r"(\d+\.\d+(?:\.\d+)?)", "generic"),
        ]

        for pattern, pattern_type in patterns:
            match = re.search(pattern, text_lower)
            if match:
                version_str = match.group(1)
                # Normaliser en gardant max 3 niveaux
                parts = version_str.split(".")
                normalized = ".".join(parts[:3])

                # Détecter opérateur
                operator = self._detect_operator(text_lower)

                return ValueInfo(
                    kind=ValueKind.VERSION,
                    raw=version_str,
                    normalized=normalized,
                    unit="version",
                    operator=operator,
                    comparable=ValueComparable.STRICT
                )
        return None

    def _extract_number_with_unit(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait un nombre avec unité."""
        units = {
            r"tib": ("TiB", 1),
            r"tb": ("TB", 1),
            r"gib": ("GiB", 1),
            r"gb": ("GB", 1),
            r"mib": ("MiB", 1),
            r"mb": ("MB", 1),
            r"hours?": ("hours", 1),
            r"days?": ("days", 1),
            r"weeks?": ("weeks", 1),
            r"months?": ("months", 1),
            r"years?": ("years", 1),
            r"seconds?": ("seconds", 1),
            r"minutes?": ("minutes", 1),
        }

        for unit_pattern, (unit_name, multiplier) in units.items():
            pattern = rf"(\d+(?:\.\d+)?)\s*{unit_pattern}"
            match = re.search(pattern, text_lower)
            if match:
                raw_value = match.group(1)
                normalized = float(raw_value) * multiplier
                operator = self._detect_operator(text_lower)

                return ValueInfo(
                    kind=ValueKind.NUMBER,
                    raw=f"{raw_value} {unit_name}",
                    normalized=normalized,
                    unit=unit_name,
                    operator=operator,
                    comparable=ValueComparable.STRICT
                )
        return None

    def _extract_boolean(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait un booléen."""
        true_patterns = [
            r"\b(enabled|required|mandatory|enforced|supported|available)\b",
            r"\b(must|shall)\b",
            r"\bis\s+(enabled|required|mandatory)\b",
        ]
        false_patterns = [
            r"\b(disabled|not required|optional|not supported|unavailable)\b",
            r"\bnot\s+(enabled|required|mandatory)\b",
        ]

        for pattern in true_patterns:
            if re.search(pattern, text_lower):
                return ValueInfo(
                    kind=ValueKind.BOOLEAN,
                    raw="true",
                    normalized=True,
                    unit=None,
                    operator="=",
                    comparable=ValueComparable.STRICT
                )

        for pattern in false_patterns:
            if re.search(pattern, text_lower):
                return ValueInfo(
                    kind=ValueKind.BOOLEAN,
                    raw="false",
                    normalized=False,
                    unit=None,
                    operator="=",
                    comparable=ValueComparable.STRICT
                )

        return None

    def _extract_enum(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait une valeur énumérée."""
        enums = {
            "frequency": ["daily", "weekly", "monthly", "hourly", "yearly", "continuous", "quarterly"],
            "responsibility": ["customer", "sap", "vendor", "shared", "third-party"],
            "severity": ["critical", "high", "medium", "low"],
            "edition": ["private", "public", "enterprise", "standard"],
            "environment": ["production", "development", "staging", "test"],
        }

        for enum_type, values in enums.items():
            for value in values:
                if re.search(rf"\b{value}\b", text_lower):
                    return ValueInfo(
                        kind=ValueKind.ENUM,
                        raw=value,
                        normalized=value.lower(),
                        unit=enum_type,
                        operator="=",
                        comparable=ValueComparable.STRICT
                    )

        return None

    def _detect_operator(self, text_lower: str) -> str:
        """Détecte l'opérateur de comparaison."""
        if any(kw in text_lower for kw in ["above", "over", "exceeds", "greater than", "more than"]):
            return ">"
        if any(kw in text_lower for kw in ["below", "under", "less than"]):
            return "<"
        if any(kw in text_lower for kw in ["at least", "minimum", "min"]):
            return ">="
        if any(kw in text_lower for kw in ["at most", "maximum", "max"]):
            return "<="
        if any(kw in text_lower for kw in ["approximately", "about", "around"]):
            return "approx"
        return "="


# Instance singleton
_value_extractor: Optional[ValueExtractor] = None


def get_value_extractor() -> ValueExtractor:
    """Retourne l'instance singleton."""
    global _value_extractor
    if _value_extractor is None:
        _value_extractor = ValueExtractor()
    return _value_extractor
