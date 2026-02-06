"""
OSMOSE Verification - Claim Forms

Structure logique des claims pour comparaison structurée.
Chaque ClaimForm a un type, une valeur, et des métadonnées.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Any
from pydantic import BaseModel

from knowbase.verification.comparison.value_algebra import Value, AuthorityLevel
from knowbase.verification.comparison.truth_regimes import TruthRegime


class ClaimFormType(str, Enum):
    """
    Types de formes logiques pour les claims.

    Chaque type a des règles de comparaison spécifiques.
    """
    EXACT_VALUE = "EXACT_VALUE"       # property = value (scalaire)
    INTERVAL_VALUE = "INTERVAL_VALUE" # property ∈ [low, high]
    BOUNDED_VALUE = "BOUNDED_VALUE"   # property ≤/≥ value
    SET_VALUE = "SET_VALUE"           # property ∈ {v1, v2, ...}
    BOOLEAN_VALUE = "BOOLEAN_VALUE"   # property = true/false
    EXISTS_VALUE = "EXISTS_VALUE"     # property exists
    VERSION_VALUE = "VERSION_VALUE"   # property = version
    TEXT_VALUE = "TEXT_VALUE"         # fallback sémantique


@dataclass
class ClaimForm:
    """
    Forme logique structurée d'un claim ou assertion.

    Cette structure permet la comparaison déterministe
    sans dépendre du LLM pour le verdict.

    Attributes:
        form_type: Type de forme logique
        property_surface: Nom de propriété tel que détecté ("SLA", "availability")
        claim_key: Clé canonique optionnelle ("service_level_agreement")
        value: Valeur typée (Scalar, Interval, Set, etc.)
        truth_regime: Régime de vérité détecté
        authority: Niveau d'autorité de la source
        original_text: Texte original complet
        verbatim_quote: Citation exacte (si différente de original_text)
        parse_confidence: Confiance de l'extraction (0-1)

        # Scope (contexte conditionnel)
        scope_version: Version concernée (ex: "2023")
        scope_region: Région concernée (ex: "EU", "US")
        scope_edition: Édition concernée (ex: "Enterprise")
        scope_conditions: Conditions supplémentaires

        # Metadata
        schema_version: Version du schéma pour migrations futures
    """
    form_type: ClaimFormType
    property_surface: str  # Tel que détecté: "SLA", "availability", "uptime"
    value: Value
    truth_regime: TruthRegime
    authority: AuthorityLevel
    original_text: str
    verbatim_quote: str

    # Optionnels
    claim_key: Optional[str] = None  # Clé canonique: "service_level_agreement"
    parse_confidence: float = 1.0

    # Scope
    scope_version: Optional[str] = None
    scope_region: Optional[str] = None
    scope_edition: Optional[str] = None
    scope_conditions: List[str] = field(default_factory=list)

    # Metadata
    schema_version: str = "1.1"

    def has_scope(self) -> bool:
        """Vérifie si un scope est défini."""
        return bool(
            self.scope_version or
            self.scope_region or
            self.scope_edition or
            self.scope_conditions
        )

    def get_scope_keys(self) -> List[str]:
        """Retourne les clés de scope définies."""
        keys = []
        if self.scope_version:
            keys.append("version")
        if self.scope_region:
            keys.append("region")
        if self.scope_edition:
            keys.append("edition")
        if self.scope_conditions:
            keys.append("conditions")
        return keys

    def scope_matches(self, other: "ClaimForm") -> bool:
        """
        Vérifie si les scopes sont compatibles.

        Returns True si:
        - Aucun scope défini des deux côtés
        - Les scopes définis correspondent

        Returns False si:
        - other a un scope que self n'a pas (self peut manquer de contexte)
        """
        # Si aucun scope des deux côtés
        if not self.has_scope() and not other.has_scope():
            return True

        # Si other a un scope que self n'a pas = MISMATCH
        # (self doit spécifier le même scope pour être comparable)
        if other.scope_version and not self.scope_version:
            return False
        if other.scope_region and not self.scope_region:
            return False
        if other.scope_edition and not self.scope_edition:
            return False

        # Comparer chaque scope défini
        if self.scope_version and other.scope_version:
            if self.scope_version.lower() != other.scope_version.lower():
                return False

        if self.scope_region and other.scope_region:
            if self.scope_region.lower() != other.scope_region.lower():
                return False

        if self.scope_edition and other.scope_edition:
            if self.scope_edition.lower() != other.scope_edition.lower():
                return False

        return True

    def property_matches(self, other: "ClaimForm") -> bool:
        """
        Vérifie si les propriétés sont comparables.

        Rules:
        - Si les deux ont un claim_key identique → True
        - Si claim_key différent des deux côtés → False
        - Si un seul a un claim_key → utiliser property_surface
        - Si aucun claim_key → comparaison surface prudente
        """
        # Cas 1: Les deux ont un claim_key
        if self.claim_key and other.claim_key:
            return self.claim_key.lower() == other.claim_key.lower()

        # Cas 2: Comparaison sur property_surface (moins fiable)
        # Normalisation basique
        self_prop = self.property_surface.lower().strip()
        other_prop = other.property_surface.lower().strip()

        # Match exact
        if self_prop == other_prop:
            return True

        # Aliases connus
        aliases = {
            "sla": {"service level", "availability", "uptime"},
            "rpo": {"recovery point", "point de reprise"},
            "rto": {"recovery time", "temps de reprise"},
        }

        for key, alias_set in aliases.items():
            if self_prop == key or self_prop in alias_set:
                if other_prop == key or other_prop in alias_set:
                    return True

        return False

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "form_type": self.form_type.value,
            "property_surface": self.property_surface,
            "claim_key": self.claim_key,
            "value": self.value.to_canonical(),
            "value_type": type(self.value).__name__,
            "truth_regime": self.truth_regime.value,
            "authority": self.authority.value,
            "original_text": self.original_text,
            "verbatim_quote": self.verbatim_quote,
            "parse_confidence": self.parse_confidence,
            "scope_version": self.scope_version,
            "scope_region": self.scope_region,
            "scope_edition": self.scope_edition,
            "scope_conditions": self.scope_conditions,
            "schema_version": self.schema_version,
        }


class StructuredClaimForm(BaseModel):
    """
    Version Pydantic de ClaimForm pour stockage Neo4j et API.

    Utilisé pour le champ structured_form des Claim nodes.
    """
    form_type: str
    property_surface: str
    claim_key: Optional[str] = None
    value_type: str  # Nom de la classe Value
    value_data: dict  # Données sérialisées de la Value
    truth_regime: str
    authority: str = "MEDIUM"
    parse_confidence: float = 1.0
    scope_version: Optional[str] = None
    scope_region: Optional[str] = None
    scope_edition: Optional[str] = None
    scope_conditions: List[str] = []
    schema_version: str = "1.1"

    class Config:
        extra = "allow"  # Permettre champs additionnels pour compatibilité

    @classmethod
    def from_claim_form(cls, form: ClaimForm) -> "StructuredClaimForm":
        """Crée depuis un ClaimForm."""
        # Sérialiser la valeur selon son type
        value_data = {}
        value = form.value

        from knowbase.verification.comparison.value_algebra import (
            ScalarValue, IntervalValue, InequalityValue, SetValue,
            BooleanValue, VersionValue, TextValue
        )

        if isinstance(value, ScalarValue):
            value_data = {"value": value.value, "unit": value.unit}
        elif isinstance(value, IntervalValue):
            value_data = {
                "low": value.low,
                "high": value.high,
                "unit": value.unit,
                "inclusive_low": value.inclusive_low,
                "inclusive_high": value.inclusive_high,
            }
        elif isinstance(value, InequalityValue):
            value_data = {
                "operator": value.operator,
                "bound": value.bound,
                "unit": value.unit,
            }
        elif isinstance(value, SetValue):
            value_data = {
                "values": list(value.values),
                "unit": value.unit,
                "conditions": value.conditions,
            }
        elif isinstance(value, BooleanValue):
            value_data = {"value": value.value}
        elif isinstance(value, VersionValue):
            value_data = {
                "major": value.major,
                "minor": value.minor,
                "patch": value.patch,
                "suffix": value.suffix,
                "original": value.original,
            }
        elif isinstance(value, TextValue):
            value_data = {"text": value.text}

        return cls(
            form_type=form.form_type.value,
            property_surface=form.property_surface,
            claim_key=form.claim_key,
            value_type=type(form.value).__name__,
            value_data=value_data,
            truth_regime=form.truth_regime.value,
            authority=form.authority.value,
            parse_confidence=form.parse_confidence,
            scope_version=form.scope_version,
            scope_region=form.scope_region,
            scope_edition=form.scope_edition,
            scope_conditions=form.scope_conditions,
            schema_version=form.schema_version,
        )

    def to_claim_form(self, original_text: str = "", verbatim_quote: str = "") -> ClaimForm:
        """Reconstruit un ClaimForm depuis la version sérialisée."""
        from knowbase.verification.comparison.value_algebra import (
            ScalarValue, IntervalValue, InequalityValue, SetValue,
            BooleanValue, VersionValue, TextValue
        )

        # Reconstruire la Value
        value: Value
        if self.value_type == "ScalarValue":
            value = ScalarValue(
                value=self.value_data.get("value", 0),
                unit=self.value_data.get("unit")
            )
        elif self.value_type == "IntervalValue":
            value = IntervalValue(
                low=self.value_data.get("low", 0),
                high=self.value_data.get("high", 0),
                unit=self.value_data.get("unit"),
                inclusive_low=self.value_data.get("inclusive_low", True),
                inclusive_high=self.value_data.get("inclusive_high", True),
            )
        elif self.value_type == "InequalityValue":
            value = InequalityValue(
                operator=self.value_data.get("operator", "<="),
                bound=self.value_data.get("bound", 0),
                unit=self.value_data.get("unit"),
            )
        elif self.value_type == "SetValue":
            value = SetValue(
                values=set(self.value_data.get("values", [])),
                unit=self.value_data.get("unit"),
                conditions=self.value_data.get("conditions"),
            )
        elif self.value_type == "BooleanValue":
            value = BooleanValue(value=self.value_data.get("value", False))
        elif self.value_type == "VersionValue":
            value = VersionValue(
                major=self.value_data.get("major", 0),
                minor=self.value_data.get("minor"),
                patch=self.value_data.get("patch"),
                suffix=self.value_data.get("suffix"),
                original=self.value_data.get("original", ""),
            )
        else:
            value = TextValue(text=self.value_data.get("text", ""))

        return ClaimForm(
            form_type=ClaimFormType(self.form_type),
            property_surface=self.property_surface,
            claim_key=self.claim_key,
            value=value,
            truth_regime=TruthRegime(self.truth_regime),
            authority=AuthorityLevel(self.authority),
            original_text=original_text,
            verbatim_quote=verbatim_quote,
            parse_confidence=self.parse_confidence,
            scope_version=self.scope_version,
            scope_region=self.scope_region,
            scope_edition=self.scope_edition,
            scope_conditions=self.scope_conditions,
            schema_version=self.schema_version,
        )
