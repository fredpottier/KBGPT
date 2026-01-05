"""
LinguisticCueDetector - Scoring des patterns linguistiques.

Detecte et score la presence de patterns linguistiques universels
autour d'un candidat marker :
- Scope language : indique un marqueur de contexte (version, release, as of...)
- Legal language : indique du template/boilerplate (©, all rights reserved...)
- Contrast language : indique comparaison (vs, unlike...)

Ces patterns sont agnostiques et applicables a tout domaine.

Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md - Section 4.4
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re
import logging


logger = logging.getLogger(__name__)


# === PATTERNS LINGUISTIQUES AGNOSTIQUES ===

# Scope language : indique un marqueur de contexte/version
SCOPE_LANGUAGE_PATTERNS = [
    # Version/Release identifiers
    r'\b(?:version|release|edition|revision|build)\b',
    r'\b(?:v\d+|\d+\.\d+)\b',  # v2, 1.0, etc.

    # Temporal scope
    r'\b(?:as\s+of|from|since|starting|beginning)\b',
    r'\b(?:until|before|after|between)\b',

    # Applicability
    r'\b(?:applies?\s+to|valid\s+for|available\s+(?:in|for|from))\b',
    r'\b(?:supported\s+(?:in|by|from)|compatible\s+with)\b',

    # Feature lifecycle
    r'\b(?:new\s+in|introduced\s+in|added\s+in)\b',
    r'\b(?:removed\s+in|deprecated|obsolete|legacy)\b',
    r'\b(?:updated\s+in|changed\s+in|modified\s+in)\b',

    # Exclusivity
    r'\b(?:only\s+(?:in|for)|exclusively?\s+(?:in|for))\b',
    r'\b(?:specific\s+to|limited\s+to)\b',

    # Multilingual (FR, DE)
    r'\b(?:version|edition|revision)\b',  # FR/DE similar
    r'\b(?:[àa]\s+partir\s+de|depuis|valide\s+pour)\b',  # FR
    r'\b(?:ab\s+version|seit|verfügbar\s+(?:in|ab))\b',  # DE
]

# Legal language : indique du template/boilerplate legal
LEGAL_LANGUAGE_PATTERNS = [
    # Copyright symbols
    r'[©®™]',
    r'\(c\)',
    r'\bcopyright\b',

    # Rights reserved
    r'\ball\s+rights\s+reserved\b',
    r'\bdroits\s+réservés\b',  # FR
    r'\balle\s+rechte\s+vorbehalten\b',  # DE

    # Confidentiality
    r'\bconfidential\b',
    r'\bproprietary\b',
    r'\binternal\s+use\s+only\b',
    r'\bdo\s+not\s+distribute\b',

    # Legal notices
    r'\blegal\s+notice\b',
    r'\bdisclaimer\b',
    r'\btrademark\b',
    r'\bregistered\s+trademark\b',

    # Company identifiers (agnostic)
    r'\bor\s+(?:an?\s+)?affiliate\s+company\b',
    r'\bsubsidiar(?:y|ies)\b',
    r'\binc\.|corp\.|ltd\.|llc\.|gmbh\.|s\.?a\.?\b',
]

# Contrast language : indique comparaison (potentiellement MIXED scope)
CONTRAST_LANGUAGE_PATTERNS = [
    r'\bvs\.?\b',
    r'\bversus\b',
    r'\bunlike\b',
    r'\bin\s+contrast\s+(?:to|with)\b',
    r'\bcompared\s+(?:to|with)\b',
    r'\bdiffers?\s+from\b',
    r'\bwhereas\b',
    r'\bwhile\b.*\b(?:has|does|is|was)\b',
    r'\bbut\s+in\b',
    r'\bhowever\b',

    # Multilingual
    r'\bcontrairement\s+[àa]\b',  # FR
    r'\bpar\s+rapport\s+[àa]\b',  # FR
    r'\bim\s+gegensatz\s+zu\b',  # DE
]


@dataclass
class ContextualCues:
    """
    Scores des patterns linguistiques pour un contexte textuel.

    Tous les scores sont normalises entre 0.0 et 1.0.
    """
    scope_language_score: float = 0.0
    legal_language_score: float = 0.0
    contrast_language_score: float = 0.0

    # Details pour explicabilite
    scope_matches: List[str] = field(default_factory=list)
    legal_matches: List[str] = field(default_factory=list)
    contrast_matches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_language_score": round(self.scope_language_score, 2),
            "legal_language_score": round(self.legal_language_score, 2),
            "contrast_language_score": round(self.contrast_language_score, 2),
        }

    def to_dict_with_matches(self) -> Dict[str, Any]:
        """Version complete avec les matches pour debug."""
        return {
            "scope_language_score": round(self.scope_language_score, 2),
            "legal_language_score": round(self.legal_language_score, 2),
            "contrast_language_score": round(self.contrast_language_score, 2),
            "scope_matches": self.scope_matches[:5],
            "legal_matches": self.legal_matches[:5],
            "contrast_matches": self.contrast_matches[:5],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextualCues":
        return cls(
            scope_language_score=data.get("scope_language_score", 0.0),
            legal_language_score=data.get("legal_language_score", 0.0),
            contrast_language_score=data.get("contrast_language_score", 0.0),
        )


class LinguisticCueDetector:
    """
    Detecte et score les patterns linguistiques dans un contexte textuel.

    Usage:
        >>> detector = LinguisticCueDetector()
        >>> cues = detector.score_context("Available in version 1809")
        >>> print(cues.scope_language_score)  # > 0.5
    """

    def __init__(
        self,
        scope_weight: float = 1.0,
        legal_weight: float = 1.0,
        contrast_weight: float = 1.0,
    ):
        """
        Initialise le detecteur.

        Args:
            scope_weight: Poids pour normalisation scope
            legal_weight: Poids pour normalisation legal
            contrast_weight: Poids pour normalisation contrast
        """
        self.scope_weight = scope_weight
        self.legal_weight = legal_weight
        self.contrast_weight = contrast_weight

        # Compiler les patterns
        self._scope_patterns = [
            re.compile(p, re.IGNORECASE) for p in SCOPE_LANGUAGE_PATTERNS
        ]
        self._legal_patterns = [
            re.compile(p, re.IGNORECASE) for p in LEGAL_LANGUAGE_PATTERNS
        ]
        self._contrast_patterns = [
            re.compile(p, re.IGNORECASE) for p in CONTRAST_LANGUAGE_PATTERNS
        ]

    def score_context(self, text: str) -> ContextualCues:
        """
        Score les patterns linguistiques dans un texte.

        Args:
            text: Contexte textuel autour d'un candidat (evidence)

        Returns:
            ContextualCues avec scores normalises
        """
        if not text:
            return ContextualCues()

        text_lower = text.lower()

        # Compter les matches
        scope_matches = self._find_matches(text, self._scope_patterns)
        legal_matches = self._find_matches(text, self._legal_patterns)
        contrast_matches = self._find_matches(text, self._contrast_patterns)

        # Normaliser les scores (0.0 - 1.0)
        # On utilise une fonction saturante pour eviter les scores > 1
        scope_score = self._normalize_score(len(scope_matches), self.scope_weight)
        legal_score = self._normalize_score(len(legal_matches), self.legal_weight)
        contrast_score = self._normalize_score(len(contrast_matches), self.contrast_weight)

        return ContextualCues(
            scope_language_score=scope_score,
            legal_language_score=legal_score,
            contrast_language_score=contrast_score,
            scope_matches=scope_matches,
            legal_matches=legal_matches,
            contrast_matches=contrast_matches,
        )

    def score_evidence_samples(
        self,
        samples: List[Dict[str, Any]],
    ) -> ContextualCues:
        """
        Score les patterns sur plusieurs samples d'evidence.

        Fait la moyenne ponderee des scores sur tous les samples.

        Args:
            samples: Liste de {"text": "...", "page": N, "zone": "..."}

        Returns:
            ContextualCues agreges
        """
        if not samples:
            return ContextualCues()

        total_scope = 0.0
        total_legal = 0.0
        total_contrast = 0.0
        all_scope_matches: List[str] = []
        all_legal_matches: List[str] = []
        all_contrast_matches: List[str] = []

        for sample in samples:
            text = sample.get("text", "")
            cues = self.score_context(text)

            total_scope += cues.scope_language_score
            total_legal += cues.legal_language_score
            total_contrast += cues.contrast_language_score

            all_scope_matches.extend(cues.scope_matches)
            all_legal_matches.extend(cues.legal_matches)
            all_contrast_matches.extend(cues.contrast_matches)

        n = len(samples)
        return ContextualCues(
            scope_language_score=total_scope / n,
            legal_language_score=total_legal / n,
            contrast_language_score=total_contrast / n,
            scope_matches=list(set(all_scope_matches))[:10],
            legal_matches=list(set(all_legal_matches))[:10],
            contrast_matches=list(set(all_contrast_matches))[:10],
        )

    def _find_matches(
        self,
        text: str,
        patterns: List[re.Pattern],
    ) -> List[str]:
        """Trouve tous les matches pour une liste de patterns."""
        matches = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                matches.append(match.group(0))
        return matches

    def _normalize_score(self, count: int, weight: float = 1.0) -> float:
        """
        Normalise un count en score 0.0-1.0.

        Utilise une fonction saturante: score = 1 - 1/(1 + count * weight)
        - 0 matches -> 0.0
        - 1 match -> 0.5
        - 2 matches -> 0.67
        - 3+ matches -> 0.75+
        """
        if count == 0:
            return 0.0
        return 1.0 - 1.0 / (1.0 + count * weight)

    def is_likely_template_context(self, cues: ContextualCues) -> bool:
        """
        Determine si le contexte indique probablement du template.

        Heuristique simple basee sur les scores.
        """
        # Legal score eleve ET scope score faible = template
        return (
            cues.legal_language_score > 0.5 and
            cues.scope_language_score < 0.3
        )

    def is_likely_context_setting(self, cues: ContextualCues) -> bool:
        """
        Determine si le contexte indique probablement un marker de contexte.

        Heuristique simple basee sur les scores.
        """
        # Scope score eleve ET legal score faible = context setting
        return (
            cues.scope_language_score > 0.3 and
            cues.legal_language_score < 0.5
        )


# === Singleton ===

_detector_instance: Optional[LinguisticCueDetector] = None


def get_linguistic_cue_detector() -> LinguisticCueDetector:
    """Retourne l'instance singleton du LinguisticCueDetector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = LinguisticCueDetector()
    return _detector_instance


__all__ = [
    "LinguisticCueDetector",
    "ContextualCues",
    "get_linguistic_cue_detector",
    "SCOPE_LANGUAGE_PATTERNS",
    "LEGAL_LANGUAGE_PATTERNS",
    "CONTRAST_LANGUAGE_PATTERNS",
]
