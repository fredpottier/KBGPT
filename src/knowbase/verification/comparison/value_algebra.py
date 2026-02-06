"""
OSMOSE Verification - Value Algebra

Types de valeurs unifiés pour comparaison déterministe.
Chaque type implémente les opérations: equals, contains, to_canonical.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set, Any, Union
import re


class AuthorityLevel(str, Enum):
    """
    Niveau d'autorité de la source du claim.

    Impact sur la comparaison:
    - HIGH: Toujours strict (0 tolérance)
    - MEDIUM: Règles standard
    - LOW: Peut être ignoré si conflit avec HIGH
    """
    HIGH = "HIGH"       # Contrat, standard, spec officielle
    MEDIUM = "MEDIUM"   # Documentation technique
    LOW = "LOW"         # Slide marketing, note interne


@dataclass
class Value(ABC):
    """
    Classe abstraite pour tous les types de valeurs.

    Interface commune pour la comparaison déterministe.
    """
    unit: Optional[str] = None

    @abstractmethod
    def contains(self, other: "Value") -> bool:
        """Vérifie si cette valeur contient/inclut l'autre."""
        pass

    @abstractmethod
    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        """Vérifie l'égalité avec tolérance optionnelle."""
        pass

    @abstractmethod
    def to_canonical(self) -> str:
        """Représentation canonique pour hashing/debug."""
        pass

    def is_compatible_unit(self, other: "Value") -> bool:
        """Vérifie la compatibilité des unités."""
        if self.unit is None or other.unit is None:
            return True  # Unité manquante = compatible par défaut
        return self._normalize_unit(self.unit) == self._normalize_unit(other.unit)

    @staticmethod
    def _normalize_unit(unit: Optional[str]) -> str:
        """Normalise une unité pour comparaison."""
        if unit is None:
            return ""
        if not isinstance(unit, str):
            return str(unit)
        unit = unit.lower().strip()
        # Aliases courants
        aliases = {
            "percent": "%",
            "pourcent": "%",
            "minutes": "min",
            "minute": "min",
            "hours": "h",
            "hour": "h",
            "heure": "h",
            "heures": "h",
            "seconds": "s",
            "second": "s",
            "seconde": "s",
            "secondes": "s",
            "days": "d",
            "day": "d",
            "jour": "d",
            "jours": "d",
        }
        return aliases.get(unit, unit)


@dataclass
class ScalarValue(Value):
    """
    Valeur scalaire simple.

    Examples:
    - SLA 99.5%
    - RPO 30 min
    - Capacity 1000 users
    """
    value: float = 0.0

    def contains(self, other: "Value") -> bool:
        """Un scalaire ne contient que lui-même."""
        if isinstance(other, ScalarValue):
            return self.equals(other)
        return False

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, ScalarValue):
            return False
        if not self.is_compatible_unit(other):
            return False

        if tolerance == 0.0:
            return self.value == other.value

        # Tolérance relative
        if self.value == 0:
            return abs(other.value) <= tolerance
        return abs(self.value - other.value) / abs(self.value) <= tolerance

    def to_canonical(self) -> str:
        unit_str = f" {self.unit}" if self.unit else ""
        return f"{self.value}{unit_str}"


@dataclass
class IntervalValue(Value):
    """
    Intervalle de valeurs [low, high].

    Examples:
    - SLA 99.7-99.9%
    - RPO 0-30 min
    """
    low: float = field(default=0.0)
    high: float = field(default=0.0)
    inclusive_low: bool = field(default=True)
    inclusive_high: bool = field(default=True)

    def __post_init__(self):
        # Assurer low <= high
        if self.low > self.high:
            self.low, self.high = self.high, self.low

    def contains(self, other: "Value") -> bool:
        """Vérifie si une valeur est dans l'intervalle."""
        if not self.is_compatible_unit(other):
            return False

        if isinstance(other, ScalarValue):
            if self.inclusive_low and self.inclusive_high:
                return self.low <= other.value <= self.high
            elif self.inclusive_low:
                return self.low <= other.value < self.high
            elif self.inclusive_high:
                return self.low < other.value <= self.high
            else:
                return self.low < other.value < self.high

        if isinstance(other, IntervalValue):
            # L'autre intervalle doit être contenu entièrement
            return self.contains(ScalarValue(other.low, other.unit)) and \
                   self.contains(ScalarValue(other.high, other.unit))

        return False

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, IntervalValue):
            return False
        if not self.is_compatible_unit(other):
            return False

        if tolerance == 0.0:
            return (self.low == other.low and
                    self.high == other.high and
                    self.inclusive_low == other.inclusive_low and
                    self.inclusive_high == other.inclusive_high)

        # Avec tolérance: les bornes doivent être proches
        low_match = abs(self.low - other.low) <= tolerance * abs(self.low) if self.low != 0 else abs(other.low) <= tolerance
        high_match = abs(self.high - other.high) <= tolerance * abs(self.high) if self.high != 0 else abs(other.high) <= tolerance
        return low_match and high_match

    def overlaps(self, other: "IntervalValue") -> bool:
        """Vérifie si deux intervalles se chevauchent."""
        if not self.is_compatible_unit(other):
            return False
        return self.low <= other.high and other.low <= self.high

    def to_canonical(self) -> str:
        unit_str = f" {self.unit}" if self.unit else ""
        low_bracket = "[" if self.inclusive_low else "("
        high_bracket = "]" if self.inclusive_high else ")"
        return f"{low_bracket}{self.low}, {self.high}{high_bracket}{unit_str}"


@dataclass
class InequalityValue(Value):
    """
    Inégalité: ≤, ≥, <, >

    Examples:
    - RPO ≤ 30 min
    - Latency < 100 ms
    """
    operator: str = "<="  # <=, >=, <, >
    bound: float = 0.0

    def contains(self, other: "Value") -> bool:
        """Vérifie si une valeur satisfait l'inégalité."""
        if not self.is_compatible_unit(other):
            return False

        if isinstance(other, ScalarValue):
            return self._check_inequality(other.value)

        if isinstance(other, IntervalValue):
            # Tout l'intervalle doit satisfaire l'inégalité
            return self._check_inequality(other.low) and self._check_inequality(other.high)

        if isinstance(other, InequalityValue):
            # Vérifier l'implication logique
            return self._implies(other)

        return False

    def _check_inequality(self, value: float) -> bool:
        """Vérifie si une valeur satisfait l'inégalité."""
        if self.operator == "<=":
            return value <= self.bound
        elif self.operator == ">=":
            return value >= self.bound
        elif self.operator == "<":
            return value < self.bound
        elif self.operator == ">":
            return value > self.bound
        return False

    def _implies(self, other: "InequalityValue") -> bool:
        """Vérifie si cette inégalité implique l'autre."""
        # x <= 30 implique x <= 40
        if self.operator == "<=" and other.operator == "<=":
            return self.bound <= other.bound
        if self.operator == ">=" and other.operator == ">=":
            return self.bound >= other.bound
        # Autres cas complexes
        return False

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, InequalityValue):
            return False
        if not self.is_compatible_unit(other):
            return False
        if self.operator != other.operator:
            return False

        if tolerance == 0.0:
            return self.bound == other.bound

        if self.bound == 0:
            return abs(other.bound) <= tolerance
        return abs(self.bound - other.bound) / abs(self.bound) <= tolerance

    def to_canonical(self) -> str:
        unit_str = f" {self.unit}" if self.unit else ""
        return f"{self.operator} {self.bound}{unit_str}"


@dataclass
class SetValue(Value):
    """
    Ensemble de valeurs discrètes.

    Examples:
    - RPO: {0, 30} min
    - Editions: {Standard, Professional, Enterprise}
    """
    values: Set[Any] = field(default_factory=set)
    conditions: Optional[dict] = None  # {value: condition} pour sets conditionnels

    def __post_init__(self):
        # Convertir en set si nécessaire
        if not isinstance(self.values, set):
            self.values = set(self.values)

    def contains(self, other: "Value") -> bool:
        """Vérifie si une valeur est dans l'ensemble."""
        if isinstance(other, ScalarValue):
            return other.value in self.values or str(other.value) in self.values

        if isinstance(other, SetValue):
            # L'autre set doit être un sous-ensemble
            return other.values.issubset(self.values)

        if isinstance(other, TextValue):
            # Comparaison textuelle
            return other.text.lower() in {str(v).lower() for v in self.values}

        return False

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, SetValue):
            return False
        return self.values == other.values

    def is_conditional(self) -> bool:
        """Vérifie si c'est un set conditionnel (avec contexte)."""
        return self.conditions is not None and len(self.conditions) > 0

    def get_missing_values(self, subset: Set[Any]) -> Set[Any]:
        """Retourne les valeurs manquantes par rapport au set complet."""
        return self.values - subset

    def to_canonical(self) -> str:
        unit_str = f" {self.unit}" if self.unit else ""
        values_str = ", ".join(str(v) for v in sorted(self.values, key=str))
        return f"{{{values_str}}}{unit_str}"


@dataclass
class BooleanValue(Value):
    """
    Valeur booléenne.

    Examples:
    - Encryption: supported
    - Feature X: not available
    """
    value: bool = False

    def contains(self, other: "Value") -> bool:
        return self.equals(other)

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, BooleanValue):
            return False
        return self.value == other.value

    def to_canonical(self) -> str:
        return "true" if self.value else "false"


@dataclass
class VersionValue(Value):
    """
    Valeur de version.

    Examples:
    - TLS 1.2
    - SAP S/4HANA 2023.10
    """
    major: int = 0
    minor: Optional[int] = None
    patch: Optional[int] = None
    suffix: Optional[str] = None  # "beta", "LTS", etc.
    original: str = ""  # Version originale pour display

    def contains(self, other: "Value") -> bool:
        """Une version ne contient que elle-même ou ses patchs."""
        if not isinstance(other, VersionValue):
            return False

        # Même major et minor = contient les patchs
        if self.major == other.major:
            if self.minor is None or other.minor is None:
                return True
            if self.minor == other.minor:
                return True

        return False

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, VersionValue):
            return False

        # Comparaison stricte
        return (self.major == other.major and
                self.minor == other.minor and
                self.patch == other.patch)

    def __lt__(self, other: "VersionValue") -> bool:
        """Comparaison pour ordering."""
        if not isinstance(other, VersionValue):
            return NotImplemented

        self_tuple = (self.major, self.minor or 0, self.patch or 0)
        other_tuple = (other.major, other.minor or 0, other.patch or 0)
        return self_tuple < other_tuple

    def is_compatible_with(self, required: "VersionValue") -> bool:
        """
        Vérifie si cette version est compatible avec une version requise.
        Généralement: version >= required
        """
        return not (self < required)

    @classmethod
    def parse(cls, version_str: str) -> "VersionValue":
        """Parse une string de version."""
        original = version_str
        version_str = version_str.strip()

        # Pattern: X.Y.Z[-suffix] ou vX.Y.Z
        pattern = r'^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.](.+))?$'
        match = re.match(pattern, version_str, re.IGNORECASE)

        if match:
            return cls(
                major=int(match.group(1)),
                minor=int(match.group(2)) if match.group(2) else None,
                patch=int(match.group(3)) if match.group(3) else None,
                suffix=match.group(4),
                original=original
            )

        # TLS/SSL format: TLS 1.2
        tls_pattern = r'^(?:TLS|SSL)\s*(\d+)(?:\.(\d+))?$'
        tls_match = re.match(tls_pattern, version_str, re.IGNORECASE)
        if tls_match:
            return cls(
                major=int(tls_match.group(1)),
                minor=int(tls_match.group(2)) if tls_match.group(2) else None,
                original=original,
                unit="TLS"
            )

        # Fallback: juste un nombre
        try:
            return cls(major=int(version_str), original=original)
        except ValueError:
            return cls(major=0, original=original)

    def to_canonical(self) -> str:
        if self.original:
            return self.original

        parts = [str(self.major)]
        if self.minor is not None:
            parts.append(str(self.minor))
        if self.patch is not None:
            parts.append(str(self.patch))

        version = ".".join(parts)
        if self.suffix:
            version += f"-{self.suffix}"
        if self.unit:
            version = f"{self.unit} {version}"

        return version


@dataclass
class TextValue(Value):
    """
    Valeur textuelle (fallback).

    Pour les cas où aucun type structuré n'est applicable.
    Requiert comparaison LLM.
    """
    text: str = ""

    def contains(self, other: "Value") -> bool:
        if isinstance(other, TextValue):
            # Containment textuel simple
            return other.text.lower() in self.text.lower()
        return False

    def equals(self, other: "Value", tolerance: float = 0.0) -> bool:
        if not isinstance(other, TextValue):
            return False
        # Comparaison insensible à la casse
        return self.text.lower().strip() == other.text.lower().strip()

    def to_canonical(self) -> str:
        return self.text


def parse_numeric_value(text: str) -> Optional[Union[ScalarValue, IntervalValue, InequalityValue]]:
    """
    Parse une valeur numérique depuis un texte.

    Détecte automatiquement le type:
    - Scalaire: "99.5%", "30 min"
    - Intervalle: "99.7-99.9%", "0 to 30 min"
    - Inégalité: "≤30 min", "at least 99.5%"

    Returns:
        Value instance ou None si non parsable
    """
    if not text:
        return None

    text = text.strip()

    # 1. Détecter inégalités
    ineq_patterns = [
        (r'(?:at\s+least|minimum|≥|>=)\s*(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms)?', ">="),
        (r'(?:at\s+most|maximum|≤|<=)\s*(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms)?', "<="),
        (r'(?:less\s+than|under|<)\s*(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms)?', "<"),
        (r'(?:more\s+than|over|>)\s*(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms)?', ">"),
    ]

    for pattern, operator in ineq_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1).replace(",", "."))
            unit = match.group(2) if len(match.groups()) > 1 else None
            return InequalityValue(operator=operator, bound=value, unit=unit)

    # 2. Détecter intervalles
    interval_patterns = [
        r'(\d+(?:[.,]\d+)?)\s*[-–to]\s*(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms)?',
        r'(?:between|entre)\s+(\d+(?:[.,]\d+)?)\s+(?:and|et)\s+(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms)?',
    ]

    for pattern in interval_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            low = float(match.group(1).replace(",", "."))
            high = float(match.group(2).replace(",", "."))
            unit = match.group(3) if len(match.groups()) > 2 else None
            return IntervalValue(low=low, high=high, unit=unit)

    # 3. Détecter scalaire
    scalar_pattern = r'(\d+(?:[.,]\d+)?)\s*(%|min|h|s|d|ms|minutes?|hours?|seconds?)?'
    match = re.search(scalar_pattern, text, re.IGNORECASE)
    if match:
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2) if len(match.groups()) > 1 else None
        return ScalarValue(value=value, unit=unit)

    return None
