"""
OSMOSE Verification - Structured Extractor

Extraction de ClaimForm depuis le texte.
Stratégie hybride: rule-based (regex) → fallback LLM.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

import re
import logging
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass

from knowbase.verification.comparison.truth_regimes import TruthRegime, TruthRegimeDetector
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
    parse_numeric_value,
)
from knowbase.verification.comparison.claim_forms import ClaimForm, ClaimFormType

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Résultat d'extraction avec métadonnées."""
    claim_form: Optional[ClaimForm]
    extraction_method: str  # "regex", "llm", "failed"
    parse_confidence: float
    raw_extractions: List[dict]  # Détails des patterns matchés


# Patterns de propriétés connues
PROPERTY_PATTERNS: List[Tuple[str, str, List[str]]] = [
    # (claim_key, regex_pattern, aliases)
    ("service_level_agreement", r'\b(SLA|service\s+level|availability|uptime|disponibilit[ée])\b', ["SLA", "availability", "uptime"]),
    ("recovery_point_objective", r'\b(RPO|recovery\s+point|point\s+de\s+reprise)\b', ["RPO"]),
    ("recovery_time_objective", r'\b(RTO|recovery\s+time|temps\s+de\s+reprise)\b', ["RTO"]),
    ("latency", r'\b(latency|latence|response\s+time|temps\s+de\s+r[ée]ponse)\b', ["latency"]),
    ("throughput", r'\b(throughput|d[ée]bit|capacity|capacit[ée])\b', ["throughput", "capacity"]),
    ("version", r'\b(version|v\d|TLS|SSL)\b', ["version"]),
    ("encryption", r'\b(encryption|chiffrement|encrypted|crypt[ée])\b', ["encryption"]),
    ("backup_frequency", r'\b(backup|sauvegarde)\s*(frequency|fr[ée]quence)?\b', ["backup"]),
]


class StructuredExtractor:
    """
    Extrait des ClaimForms structurés depuis du texte.

    Stratégie:
    1. Détecter le régime de vérité (patterns linguistiques)
    2. Extraire les valeurs (regex pour numériques, patterns pour booléens)
    3. Identifier la propriété (patterns de mots-clés)
    4. Si échec, fallback LLM (optionnel)
    """

    def __init__(self):
        self.regime_detector = TruthRegimeDetector()

        # Pré-compiler les patterns de propriétés
        self._property_patterns = [
            (key, re.compile(pattern, re.IGNORECASE), aliases)
            for key, pattern, aliases in PROPERTY_PATTERNS
        ]

        # Patterns pour les valeurs
        self._value_patterns = self._compile_value_patterns()

    def _compile_value_patterns(self) -> List[Tuple[str, re.Pattern, callable]]:
        """Compile les patterns d'extraction de valeurs."""
        patterns = []

        # 1. Intervalles de pourcentages: 99.7-99.9%, 99,7% à 99,9%
        patterns.append((
            "interval_percent",
            re.compile(
                r'(\d+(?:[.,]\d+)?)\s*[-–àto]\s*(\d+(?:[.,]\d+)?)\s*(%|pour\s*cent)',
                re.IGNORECASE
            ),
            lambda m: IntervalValue(
                low=float(m.group(1).replace(",", ".")),
                high=float(m.group(2).replace(",", ".")),
                unit="%"
            )
        ))

        # 2. Intervalles de durées: 0-30 min, 0 à 30 minutes
        patterns.append((
            "interval_duration",
            re.compile(
                r'(\d+(?:[.,]\d+)?)\s*[-–àto]\s*(\d+(?:[.,]\d+)?)\s*(min(?:utes?)?|h(?:ours?|eures?)?|s(?:econds?|econdes?)?)',
                re.IGNORECASE
            ),
            lambda m: IntervalValue(
                low=float(m.group(1).replace(",", ".")),
                high=float(m.group(2).replace(",", ".")),
                unit=self._normalize_duration_unit(m.group(3))
            )
        ))

        # 3. Sets: "0 or 30 min", "0 ou 30 minutes"
        patterns.append((
            "set_values",
            re.compile(
                r'(\d+(?:[.,]\d+)?)\s*(?:or|ou)\s*(\d+(?:[.,]\d+)?)\s*(min(?:utes?)?|h(?:ours?)?)?',
                re.IGNORECASE
            ),
            lambda m: SetValue(
                values={
                    float(m.group(1).replace(",", ".")),
                    float(m.group(2).replace(",", "."))
                },
                unit=self._normalize_duration_unit(m.group(3)) if m.group(3) else None
            )
        ))

        # 4. Inégalités: at least 99.5%, minimum 30 min, ≤30
        patterns.append((
            "inequality_ge",
            re.compile(
                r'(?:at\s+least|minimum|au\s+moins|≥|>=)\s*(\d+(?:[.,]\d+)?)\s*(%|min(?:utes?)?|h(?:ours?)?)?',
                re.IGNORECASE
            ),
            lambda m: InequalityValue(
                operator=">=",
                bound=float(m.group(1).replace(",", ".")),
                unit=m.group(2) if m.group(2) else None
            )
        ))

        patterns.append((
            "inequality_le",
            re.compile(
                r'(?:at\s+most|maximum|au\s+plus|≤|<=)\s*(\d+(?:[.,]\d+)?)\s*(%|min(?:utes?)?|h(?:ours?)?)?',
                re.IGNORECASE
            ),
            lambda m: InequalityValue(
                operator="<=",
                bound=float(m.group(1).replace(",", ".")),
                unit=m.group(2) if m.group(2) else None
            )
        ))

        # 5. Pourcentages simples: 99.5%, 99,5%
        patterns.append((
            "scalar_percent",
            re.compile(
                r'(\d+(?:[.,]\d+)?)\s*(%|pour\s*cent)',
                re.IGNORECASE
            ),
            lambda m: ScalarValue(
                value=float(m.group(1).replace(",", ".")),
                unit="%"
            )
        ))

        # 6. Durées simples: 30 min, 2 heures
        patterns.append((
            "scalar_duration",
            re.compile(
                r'(\d+(?:[.,]\d+)?)\s*(min(?:utes?)?|h(?:ours?|eures?)?|s(?:econds?|econdes?)?|d(?:ays?|ours?)?|ms)',
                re.IGNORECASE
            ),
            lambda m: ScalarValue(
                value=float(m.group(1).replace(",", ".")),
                unit=self._normalize_duration_unit(m.group(2))
            )
        ))

        # 7. Versions: TLS 1.2, v2023.10
        patterns.append((
            "version",
            re.compile(
                r'\b(?:TLS|SSL|v|version)\s*(\d+(?:\.\d+)?(?:\.\d+)?)',
                re.IGNORECASE
            ),
            lambda m: VersionValue.parse(m.group(0))
        ))

        # 8. Booléens négatifs (AVANT les positifs pour éviter match partiel)
        patterns.append((
            "boolean_false",
            re.compile(
                r'\b(not\s+supported|disabled|unavailable|not\s+available|not\s+enabled|non\s+support[ée]|désactivé|indisponible)\b',
                re.IGNORECASE
            ),
            lambda m: BooleanValue(value=False)
        ))

        # 9. Booléens positifs
        patterns.append((
            "boolean_true",
            re.compile(
                r'\b(supported|enabled|available|required|yes|oui|activé|supporté|disponible)\b',
                re.IGNORECASE
            ),
            lambda m: BooleanValue(value=True)
        ))

        return patterns

    def _normalize_duration_unit(self, unit: Optional[str]) -> Optional[str]:
        """Normalise une unité de durée."""
        if not unit:
            return None
        unit = unit.lower()
        if unit.startswith("min"):
            return "min"
        if unit.startswith("h"):
            return "h"
        if unit.startswith("s"):
            return "s"
        if unit.startswith("d") or unit.startswith("j"):
            return "d"
        if unit == "ms":
            return "ms"
        return unit

    async def extract(
        self,
        text: str,
        default_authority: AuthorityLevel = AuthorityLevel.MEDIUM,
        use_llm_fallback: bool = False
    ) -> Optional[ClaimForm]:
        """
        Extrait un ClaimForm depuis le texte.

        Args:
            text: Texte à parser
            default_authority: Niveau d'autorité par défaut
            use_llm_fallback: Utiliser LLM si extraction regex échoue

        Returns:
            ClaimForm ou None si extraction impossible
        """
        if not text or len(text.strip()) < 3:
            return None

        text = text.strip()

        # 1. Détecter le régime de vérité
        regime_detection = self.regime_detector.detect(text)

        # 2. Extraire les valeurs (pattern matching)
        value, value_type, parse_confidence = self._extract_value(text)

        if value is None:
            if use_llm_fallback:
                return await self._llm_extract(text, default_authority)

            # Fallback TextValue
            value = TextValue(text=text)
            value_type = "text"
            parse_confidence = 0.3

        # 3. Identifier la propriété
        property_surface, claim_key = self._extract_property(text)

        # 4. Extraire le scope (optionnel)
        scope = self._extract_scope(text)

        # 5. Déterminer le form_type
        form_type = self._determine_form_type(value)

        return ClaimForm(
            form_type=form_type,
            property_surface=property_surface,
            claim_key=claim_key,
            value=value,
            truth_regime=regime_detection.regime,
            authority=default_authority,
            original_text=text,
            verbatim_quote=text,
            parse_confidence=parse_confidence * (1.0 - regime_detection.hedge_strength * 0.2),
            scope_version=scope.get("version"),
            scope_region=scope.get("region"),
            scope_edition=scope.get("edition"),
            scope_conditions=scope.get("conditions", []),
        )

    def _extract_value(self, text: str) -> Tuple[Optional[Value], str, float]:
        """
        Extrait une valeur typée depuis le texte.

        Returns:
            (Value, type_name, confidence) ou (None, "", 0.0)
        """
        for pattern_name, pattern, constructor in self._value_patterns:
            match = pattern.search(text)
            if match:
                try:
                    value = constructor(match)
                    return (value, pattern_name, 0.95)
                except Exception as e:
                    logger.debug(f"Pattern {pattern_name} match failed: {e}")
                    continue

        return (None, "", 0.0)

    def _extract_property(self, text: str) -> Tuple[str, Optional[str]]:
        """
        Extrait le nom de propriété depuis le texte.

        Returns:
            (property_surface, claim_key) ou ("unknown", None)
        """
        text_lower = text.lower()

        for claim_key, pattern, aliases in self._property_patterns:
            if pattern.search(text):
                # Trouver l'alias exact qui a matché
                for alias in aliases:
                    if alias.lower() in text_lower:
                        return (alias, claim_key)
                return (aliases[0] if aliases else claim_key, claim_key)

        # Fallback: premier mot significatif
        words = text.split()
        for word in words[:3]:
            word_clean = re.sub(r'[^\w]', '', word)
            if len(word_clean) >= 2:
                return (word_clean, None)

        return ("unknown", None)

    def _extract_scope(self, text: str) -> dict:
        """Extrait les informations de scope (version, région, édition)."""
        scope = {}

        # Version/édition: "for 2023 edition", "version 2024"
        version_match = re.search(
            r'\b(?:for|version|édition|edition)\s*(\d{4}(?:\.\d+)?)\b',
            text,
            re.IGNORECASE
        )
        if version_match:
            scope["version"] = version_match.group(1)

        # Région: "EU", "US", "APAC"
        region_match = re.search(
            r'\b(EU|US|APAC|Europe|Asia|Americas?|EMEA)\b',
            text,
            re.IGNORECASE
        )
        if region_match:
            scope["region"] = region_match.group(1).upper()

        # Édition: "Enterprise", "Professional", "Standard"
        edition_match = re.search(
            r'\b(Enterprise|Professional|Standard|Basic|Premium)\b',
            text,
            re.IGNORECASE
        )
        if edition_match:
            scope["edition"] = edition_match.group(1).capitalize()

        # Conditions: "when X", "if Y"
        conditions = []
        cond_matches = re.findall(
            r'\b(?:when|if|pour|quand|si)\s+([^,.]+)',
            text,
            re.IGNORECASE
        )
        for match in cond_matches:
            conditions.append(match.strip())

        if conditions:
            scope["conditions"] = conditions

        return scope

    def _determine_form_type(self, value: Value) -> ClaimFormType:
        """Détermine le ClaimFormType depuis le type de Value."""
        type_map = {
            ScalarValue: ClaimFormType.EXACT_VALUE,
            IntervalValue: ClaimFormType.INTERVAL_VALUE,
            InequalityValue: ClaimFormType.BOUNDED_VALUE,
            SetValue: ClaimFormType.SET_VALUE,
            BooleanValue: ClaimFormType.BOOLEAN_VALUE,
            VersionValue: ClaimFormType.VERSION_VALUE,
            TextValue: ClaimFormType.TEXT_VALUE,
        }
        return type_map.get(type(value), ClaimFormType.TEXT_VALUE)

    async def _llm_extract(
        self,
        text: str,
        authority: AuthorityLevel
    ) -> Optional[ClaimForm]:
        """
        Fallback LLM pour extraction complexe.

        À implémenter selon le LLM router disponible.
        """
        # TODO: Implémenter le fallback LLM
        logger.debug(f"LLM fallback not implemented, returning TextValue for: {text[:50]}...")

        return ClaimForm(
            form_type=ClaimFormType.TEXT_VALUE,
            property_surface="unknown",
            claim_key=None,
            value=TextValue(text=text),
            truth_regime=TruthRegime.TEXTUAL_SEMANTIC,
            authority=authority,
            original_text=text,
            verbatim_quote=text,
            parse_confidence=0.3,
        )

    def extract_sync(
        self,
        text: str,
        default_authority: AuthorityLevel = AuthorityLevel.MEDIUM
    ) -> Optional[ClaimForm]:
        """
        Version synchrone de extract() pour usage dans du code non-async.
        """
        import asyncio

        # Si on est déjà dans une boucle async
        try:
            loop = asyncio.get_running_loop()
            # On est dans une boucle, utiliser un wrapper
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self.extract(text, default_authority, use_llm_fallback=False)
                )
                return future.result()
        except RuntimeError:
            # Pas de boucle, on peut utiliser asyncio.run
            return asyncio.run(
                self.extract(text, default_authority, use_llm_fallback=False)
            )
