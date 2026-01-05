"""
Heuristiques pour analyse de contexte d'anchor.

Detection deterministe (sans LLM) de:
- Polarity: negation, future, deprecated, conditional
- Local markers: versions, editions dans le passage
- Override patterns: contrast, "new in", "starting with"

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 3.3
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
import re
import logging

from knowbase.extraction_v2.context.anchor_models import (
    Polarity,
    AssertionScope,
    OverrideType,
    LocalMarker,
)

logger = logging.getLogger(__name__)


# === PATTERNS NEGATION ===

NEGATION_PATTERNS = [
    # Anglais
    r'\b(?:not|no|never|none|without|lacks?|missing|absent)\b',
    r'\b(?:cannot|can\'t|won\'t|doesn\'t|don\'t|isn\'t|aren\'t)\b',
    r'\b(?:unavailable|unsupported|not\s+(?:available|supported|included))\b',
    r'\b(?:excluded|removed|eliminated|dropped)\b',
    # Francais
    r'\b(?:pas|non|aucun|sans|manque|absent)\b',
    r'\b(?:ne\s+(?:peut|doit|sera))\b',
    r'\b(?:indisponible|non\s+(?:disponible|support[ée]))\b',
    # Allemand
    r'\b(?:nicht|kein|ohne|fehlt|entfernt)\b',
]

# === PATTERNS FUTURE ===

FUTURE_PATTERNS = [
    # Anglais
    r'\b(?:will\s+be|coming\s+(?:soon|in)|planned\s+for|future|upcoming)\b',
    r'\b(?:to\s+be\s+(?:released|added|implemented))\b',
    r'\b(?:expected\s+(?:in|by)|roadmap|next\s+(?:release|version))\b',
    # Francais
    r'\b(?:sera|futur|prochain[e]?|pr[ée]vu|planifi[ée])\b',
    r'\b(?:[àa]\s+venir|bient[oô]t\s+disponible)\b',
    # Allemand
    r'\b(?:wird|zuk[üu]nftig|geplant|kommend)\b',
]

# === PATTERNS DEPRECATED ===

DEPRECATED_PATTERNS = [
    # Anglais
    r'\b(?:deprecated|obsolete|legacy|end[- ]of[- ]life|retired)\b',
    r'\b(?:no\s+longer\s+(?:supported|available|recommended))\b',
    r'\b(?:removed\s+(?:in|from)|discontinued)\b',
    r'\b(?:replaced\s+by|superseded\s+by)\b',
    # Francais
    r'\b(?:obsol[èe]te|d[ée]pr[ée]ci[ée]|abandonn[ée]|retir[ée])\b',
    r'\b(?:plus\s+(?:support[ée]|disponible|recommand[ée]))\b',
    r'\b(?:remplac[ée]\s+par)\b',
    # Allemand
    r'\b(?:veraltet|abgek[üu]ndigt|entfernt|ersetzt\s+durch)\b',
]

# === PATTERNS CONDITIONAL ===

CONDITIONAL_PATTERNS = [
    # Anglais
    r'\b(?:if|when|unless|provided\s+that|depending\s+on)\b',
    r'\b(?:requires?|only\s+(?:if|when)|condition(?:al)?)\b',
    r'\b(?:in\s+case\s+of|subject\s+to)\b',
    # Francais
    r'\b(?:si|quand|[àa]\s+condition|selon|d[ée]pend)\b',
    r'\b(?:n[ée]cessite|uniquement\s+(?:si|quand))\b',
    # Allemand
    r'\b(?:wenn|falls|sofern|abh[äa]ngig\s+von|vorausgesetzt)\b',
]

# === PATTERNS OVERRIDE (contrast/comparison) ===

OVERRIDE_PATTERNS = [
    # Switch patterns
    (r'\b(?:unlike|in\s+contrast\s+to|contrary\s+to)\b', OverrideType.SWITCH),
    (r'\b(?:but\s+in|however\s+in|whereas\s+in)\b', OverrideType.SWITCH),
    (r'\b(?:different\s+(?:from|in)|differs?\s+from)\b', OverrideType.SWITCH),
    # Range patterns
    (r'\b(?:from\s+\w+\s+to\s+\w+|starting\s+(?:with|from)\s+\w+)\b', OverrideType.RANGE),
    (r'\b(?:since\s+(?:version|release)|as\s+of)\b', OverrideType.RANGE),
    (r'\b(?:between\s+\w+\s+and\s+\w+)\b', OverrideType.RANGE),
    # Generalization patterns
    (r'\b(?:all\s+versions?|any\s+(?:version|release)|every\s+release)\b', OverrideType.GENERALIZATION),
    (r'\b(?:regardless\s+of\s+version|version[- ]independent)\b', OverrideType.GENERALIZATION),
    # New in patterns (special case of switch)
    (r'\b(?:new\s+in|introduced\s+in|added\s+in|available\s+(?:in|from))\b', OverrideType.SWITCH),
]

# === PATTERNS VERSION/MARKER ===

# Reutilises depuis candidate_mining.py
VERSION_PATTERNS = [
    r'\b(1[89]\d{2}|20[0-9]{2}|2[1-4]\d{2}|25\d{2})\b',
    r'\bv?(\d+\.\d+(?:\.\d+)?)\b',
    r'\b(FPS\d{2})\b',
    r'\b(SP\d{2,3})\b',
]


@dataclass
class HeuristicResult:
    """
    Resultat d'analyse heuristique d'un passage.

    Attributes:
        polarity: Polarite detectee
        polarity_confidence: Confiance dans la polarite
        polarity_evidence: Evidence pour la polarite
        local_markers: Marqueurs detectes dans le passage
        is_override: True si pattern d'override detecte
        override_type: Type d'override
        override_evidence: Evidence pour l'override
        needs_llm: True si l'heuristique recommande appel LLM
    """
    polarity: Polarity = Polarity.UNKNOWN
    polarity_confidence: float = 0.0
    polarity_evidence: List[str] = None
    local_markers: List[LocalMarker] = None
    is_override: bool = False
    override_type: OverrideType = OverrideType.NULL
    override_evidence: str = ""
    needs_llm: bool = False

    def __post_init__(self):
        if self.polarity_evidence is None:
            self.polarity_evidence = []
        if self.local_markers is None:
            self.local_markers = []


class PassageHeuristics:
    """
    Analyseur heuristique de passages pour detection de contexte.

    Analyse un passage de texte pour detecter:
    - Polarite (negation, future, deprecated, conditional)
    - Marqueurs locaux (versions, editions)
    - Patterns d'override (contrast, range, generalization)

    Usage:
        >>> heuristics = PassageHeuristics()
        >>> result = heuristics.analyze("This feature is not available in 1809")
        >>> print(result.polarity)  # Polarity.NEGATIVE
    """

    def __init__(self):
        """Initialise les patterns compiles."""
        self._negation_patterns = [
            re.compile(p, re.IGNORECASE) for p in NEGATION_PATTERNS
        ]
        self._future_patterns = [
            re.compile(p, re.IGNORECASE) for p in FUTURE_PATTERNS
        ]
        self._deprecated_patterns = [
            re.compile(p, re.IGNORECASE) for p in DEPRECATED_PATTERNS
        ]
        self._conditional_patterns = [
            re.compile(p, re.IGNORECASE) for p in CONDITIONAL_PATTERNS
        ]
        self._override_patterns = [
            (re.compile(p, re.IGNORECASE), t) for p, t in OVERRIDE_PATTERNS
        ]
        self._version_patterns = [
            re.compile(p, re.IGNORECASE) for p in VERSION_PATTERNS
        ]

    def analyze(self, passage: str) -> HeuristicResult:
        """
        Analyse un passage et retourne le resultat heuristique.

        Args:
            passage: Texte du passage a analyser

        Returns:
            HeuristicResult avec polarity, markers et override info
        """
        if not passage or len(passage) < 5:
            return HeuristicResult(polarity=Polarity.POSITIVE, polarity_confidence=0.3)

        result = HeuristicResult()

        # 1. Detecter la polarite
        polarity, confidence, evidence = self._detect_polarity(passage)
        result.polarity = polarity
        result.polarity_confidence = confidence
        result.polarity_evidence = evidence

        # 2. Detecter les marqueurs locaux
        result.local_markers = self._detect_local_markers(passage)

        # 3. Detecter les patterns d'override
        is_override, override_type, override_evidence = self._detect_override(passage)
        result.is_override = is_override
        result.override_type = override_type
        result.override_evidence = override_evidence

        # 4. Determiner si LLM necessaire
        result.needs_llm = self._should_call_llm(result, passage)

        return result

    def _detect_polarity(self, passage: str) -> Tuple[Polarity, float, List[str]]:
        """
        Detecte la polarite du passage.

        Returns:
            (polarity, confidence, evidence_list)
        """
        evidence = []

        # Chercher dans l'ordre de priorite: deprecated > future > negative > conditional
        # Deprecated a la priorite car implique souvent aussi "negative"
        deprecated_matches = []
        for pattern in self._deprecated_patterns:
            for match in pattern.finditer(passage):
                deprecated_matches.append(match.group())

        if deprecated_matches:
            evidence = deprecated_matches[:2]
            return (Polarity.DEPRECATED, 0.8, evidence)

        # Future
        future_matches = []
        for pattern in self._future_patterns:
            for match in pattern.finditer(passage):
                future_matches.append(match.group())

        if future_matches:
            evidence = future_matches[:2]
            return (Polarity.FUTURE, 0.8, evidence)

        # Negative
        negation_matches = []
        for pattern in self._negation_patterns:
            for match in pattern.finditer(passage):
                negation_matches.append(match.group())

        if negation_matches:
            evidence = negation_matches[:2]
            # Moins de confiance car negation peut etre partielle
            return (Polarity.NEGATIVE, 0.7, evidence)

        # Conditional
        conditional_matches = []
        for pattern in self._conditional_patterns:
            for match in pattern.finditer(passage):
                conditional_matches.append(match.group())

        if conditional_matches:
            evidence = conditional_matches[:2]
            return (Polarity.CONDITIONAL, 0.6, evidence)

        # Pas de signal = positive par defaut (confiance moderee)
        return (Polarity.POSITIVE, 0.5, [])

    def _detect_local_markers(self, passage: str) -> List[LocalMarker]:
        """
        Detecte les marqueurs de version/edition dans le passage.

        Returns:
            Liste de LocalMarker
        """
        markers = []
        seen_values: Set[str] = set()

        for pattern in self._version_patterns:
            for match in pattern.finditer(passage):
                value = match.group(1) if match.groups() else match.group()
                value = value.strip()

                # Eviter les doublons
                if value in seen_values:
                    continue
                seen_values.add(value)

                # Extraire le contexte
                start = max(0, match.start() - 20)
                end = min(len(passage), match.end() + 20)
                evidence = passage[start:end].strip()

                markers.append(LocalMarker(
                    value=value,
                    evidence=evidence,
                    confidence=0.8,
                ))

        return markers

    def _detect_override(self, passage: str) -> Tuple[bool, OverrideType, str]:
        """
        Detecte les patterns d'override dans le passage.

        Returns:
            (is_override, override_type, evidence)
        """
        for pattern, override_type in self._override_patterns:
            match = pattern.search(passage)
            if match:
                # Extraire le contexte
                start = max(0, match.start() - 10)
                end = min(len(passage), match.end() + 30)
                evidence = passage[start:end].strip()

                return (True, override_type, evidence)

        return (False, OverrideType.NULL, "")

    def _should_call_llm(self, result: HeuristicResult, passage: str) -> bool:
        """
        Determine si un appel LLM est recommande.

        Criteres (ADR Section 3.3):
        - polarity is unknown
        - override patterns detected
        - heuristic conflict detected
        """
        # Polarity inconnue avec passage non trivial
        if result.polarity == Polarity.UNKNOWN and len(passage) > 50:
            return True

        # Override detecte = besoin de clarification
        if result.is_override:
            return True

        # Confiance faible sur polarity non-positive
        if result.polarity != Polarity.POSITIVE and result.polarity_confidence < 0.6:
            return True

        # Passage contient des marqueurs locaux ET override
        if result.local_markers and result.is_override:
            return True

        return False


def detect_polarity_simple(text: str) -> Polarity:
    """
    Detection simple de polarite (sans instancier PassageHeuristics).

    Utile pour des analyses rapides.
    """
    text_lower = text.lower()

    # Patterns simples
    if any(w in text_lower for w in ["deprecated", "obsolete", "legacy", "retired"]):
        return Polarity.DEPRECATED

    if any(w in text_lower for w in ["will be", "coming soon", "planned", "future"]):
        return Polarity.FUTURE

    if any(w in text_lower for w in ["not ", "no ", "without", "cannot", "unavailable"]):
        return Polarity.NEGATIVE

    if any(w in text_lower for w in ["if ", "when ", "unless", "depending"]):
        return Polarity.CONDITIONAL

    return Polarity.POSITIVE


def detect_local_markers_simple(text: str) -> List[str]:
    """
    Detection simple de marqueurs locaux.
    """
    markers = []
    patterns = [
        r'\b(1[89]\d{2}|20[0-9]{2}|2[1-4]\d{2})\b',
        r'\b(FPS\d{2})\b',
        r'\b(SP\d{2,3})\b',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1) if match.groups() else match.group()
            if value not in markers:
                markers.append(value)

    return markers


__all__ = [
    "PassageHeuristics",
    "HeuristicResult",
    "detect_polarity_simple",
    "detect_local_markers_simple",
]
