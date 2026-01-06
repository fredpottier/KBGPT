"""
ConfidenceScorer - Calcul heuristique du parse_confidence.

QW-2 de ADR_REDUCTO_PARSING_PRIMITIVES:
- Score de confiance sur la qualité du parsing (pas de l'extraction)
- Basé sur des heuristiques: longueur, structure, cohérence, OCR

Signaux utilisés:
1. LENGTH_SIGNAL: Texte trop court = faible confiance
2. STRUCTURE_SIGNAL: Présence de structure (headings, listes) = haute confiance
3. OCR_SIGNAL: Caractères suspects = parsing OCR dégradé
4. COHERENCE_SIGNAL: Ratio mots vs caractères normaux = cohérence linguistique
5. MARKER_SIGNAL: Présence de marqueurs OSMOSE = texte bien formaté

Usage:
    >>> scorer = ConfidenceScorer()
    >>> result = scorer.compute(text)
    >>> print(result.score)  # 0.0-1.0
    >>> print(result.signals)  # détails par signal
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# === Constantes de scoring ===

# Poids des signaux (total = 1.0)
SIGNAL_WEIGHTS = {
    "length": 0.20,      # Longueur minimale
    "structure": 0.25,   # Structure détectée
    "ocr_quality": 0.20, # Qualité OCR
    "coherence": 0.20,   # Cohérence linguistique
    "markers": 0.15,     # Marqueurs OSMOSE
}

# Seuils de longueur (en caractères)
LENGTH_THRESHOLDS = {
    "min_chars": 50,     # En dessous = score 0.0
    "low_chars": 200,    # Score partiel
    "good_chars": 500,   # Score complet
}

# Patterns pour détection structure
STRUCTURE_PATTERNS = {
    "heading": re.compile(r"^#+\s|\[TITLE\s|^={3,}|^-{3,}", re.MULTILINE),
    "list": re.compile(r"^\s*[-*•]\s|^\s*\d+\.\s", re.MULTILINE),
    "table": re.compile(r"\|.*\||\[TABLE"),
    "paragraph": re.compile(r"\[PARAGRAPH\]"),
}

# Patterns OCR suspects (caractères mal reconnus)
OCR_SUSPECT_PATTERNS = [
    re.compile(r"[^\x00-\x7F\u00C0-\u024F\u4E00-\u9FFF]{3,}"),  # Séquences non-latin/CJK
    re.compile(r"[|!1lI]{5,}"),  # Confusion OCR classique
    re.compile(r"(?:[^aeiouAEIOU\s]{10,})"),  # Séquences sans voyelles
    re.compile(r"(.)\1{4,}"),  # Caractère répété 5+ fois
    re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]"),  # Caractères de contrôle
]

# Patterns marqueurs OSMOSE (bon signe)
MARKER_PATTERN = re.compile(
    r"\[(PAGE|TITLE|PARAGRAPH|TABLE_START|TABLE_END|TABLE_SUMMARY|VISUAL_ENRICHMENT|END_VISUAL_ENRICHMENT)"
)


@dataclass
class ConfidenceResult:
    """
    Résultat du calcul de parse_confidence.

    Attributes:
        score: Score global 0.0-1.0
        signals: Scores individuels par signal
        details: Informations de debug
    """
    score: float
    signals: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Sérialise en dictionnaire."""
        return {
            "score": round(self.score, 3),
            "signals": {k: round(v, 3) for k, v in self.signals.items()},
            "details": self.details,
        }


class ConfidenceScorer:
    """
    Calcule le parse_confidence basé sur des heuristiques.

    Le parse_confidence mesure la qualité du parsing, pas de l'extraction.
    Un texte bien parsé (clair, structuré, sans artefacts OCR) aura un score élevé.

    Signaux:
    - length: Longueur suffisante pour être informatif
    - structure: Présence de structure (headings, listes, tables)
    - ocr_quality: Absence de patterns OCR suspects
    - coherence: Ratio mots/caractères normaux
    - markers: Présence de marqueurs OSMOSE (texte bien formaté)

    Usage:
        >>> scorer = ConfidenceScorer()
        >>> result = scorer.compute("Mon texte à évaluer...")
        >>> if result.score < 0.5:
        ...     logger.warning("Texte de faible qualité")
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        min_score: float = 0.1,
        max_score: float = 1.0,
    ):
        """
        Initialise le scorer.

        Args:
            weights: Poids personnalisés pour les signaux
            min_score: Score minimum (floor)
            max_score: Score maximum (ceiling)
        """
        self.weights = weights or SIGNAL_WEIGHTS.copy()
        self.min_score = min_score
        self.max_score = max_score

        # Normaliser les poids
        total_weight = sum(self.weights.values())
        if abs(total_weight - 1.0) > 0.01:
            self.weights = {k: v / total_weight for k, v in self.weights.items()}

        logger.debug(f"[ConfidenceScorer] Initialized with weights: {self.weights}")

    def compute(self, text: str) -> ConfidenceResult:
        """
        Calcule le parse_confidence pour un texte.

        Args:
            text: Texte à évaluer

        Returns:
            ConfidenceResult avec score et détails
        """
        if not text or not text.strip():
            return ConfidenceResult(
                score=0.0,
                signals={k: 0.0 for k in self.weights.keys()},
                details={"reason": "empty_text"}
            )

        signals = {}
        details = {}

        # 1. Signal longueur
        signals["length"], details["length"] = self._compute_length_signal(text)

        # 2. Signal structure
        signals["structure"], details["structure"] = self._compute_structure_signal(text)

        # 3. Signal qualité OCR
        signals["ocr_quality"], details["ocr_quality"] = self._compute_ocr_signal(text)

        # 4. Signal cohérence
        signals["coherence"], details["coherence"] = self._compute_coherence_signal(text)

        # 5. Signal marqueurs OSMOSE
        signals["markers"], details["markers"] = self._compute_markers_signal(text)

        # Score pondéré
        raw_score = sum(
            signals.get(name, 0) * weight
            for name, weight in self.weights.items()
        )

        # Clamp au min/max
        final_score = max(self.min_score, min(self.max_score, raw_score))

        return ConfidenceResult(
            score=final_score,
            signals=signals,
            details=details
        )

    def _compute_length_signal(self, text: str) -> tuple[float, dict]:
        """
        Signal basé sur la longueur du texte.

        Un texte très court est moins fiable.
        """
        char_count = len(text)

        if char_count < LENGTH_THRESHOLDS["min_chars"]:
            score = 0.0
        elif char_count < LENGTH_THRESHOLDS["low_chars"]:
            # Interpolation linéaire
            score = (char_count - LENGTH_THRESHOLDS["min_chars"]) / (
                LENGTH_THRESHOLDS["low_chars"] - LENGTH_THRESHOLDS["min_chars"]
            ) * 0.5
        elif char_count < LENGTH_THRESHOLDS["good_chars"]:
            score = 0.5 + (char_count - LENGTH_THRESHOLDS["low_chars"]) / (
                LENGTH_THRESHOLDS["good_chars"] - LENGTH_THRESHOLDS["low_chars"]
            ) * 0.5
        else:
            score = 1.0

        return score, {"char_count": char_count}

    def _compute_structure_signal(self, text: str) -> tuple[float, dict]:
        """
        Signal basé sur la présence de structure.

        Un texte structuré (headings, listes, tables) est mieux parsé.
        """
        found_structures = []

        for struct_type, pattern in STRUCTURE_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                found_structures.append(struct_type)

        # Score basé sur le nombre de types de structure trouvés
        if not found_structures:
            score = 0.3  # Texte plat mais pas forcément mauvais
        elif len(found_structures) == 1:
            score = 0.6
        elif len(found_structures) == 2:
            score = 0.85
        else:
            score = 1.0

        return score, {"structures_found": found_structures}

    def _compute_ocr_signal(self, text: str) -> tuple[float, dict]:
        """
        Signal basé sur la qualité OCR.

        Détecte des patterns suspects indiquant un OCR dégradé.
        """
        suspect_count = 0
        suspect_patterns = []

        for i, pattern in enumerate(OCR_SUSPECT_PATTERNS):
            matches = pattern.findall(text)
            if matches:
                suspect_count += len(matches)
                suspect_patterns.append(f"pattern_{i}")

        # Ratio de caractères suspects
        char_count = len(text) if text else 1
        suspect_ratio = min(1.0, suspect_count * 10 / char_count)  # Pénalité x10

        # Score inverse (moins de suspects = meilleur score)
        score = max(0.0, 1.0 - suspect_ratio)

        return score, {
            "suspect_count": suspect_count,
            "suspect_patterns": suspect_patterns
        }

    def _compute_coherence_signal(self, text: str) -> tuple[float, dict]:
        """
        Signal basé sur la cohérence linguistique.

        Un texte cohérent a un bon ratio mots/caractères et des mots reconnaissables.
        """
        # Compter les mots (séquences alphanumériques)
        words = re.findall(r'\b\w+\b', text, re.UNICODE)
        word_count = len(words)

        # Ratio caractères dans des mots vs total
        chars_in_words = sum(len(w) for w in words)
        total_chars = len(text.replace(" ", "").replace("\n", ""))

        if total_chars == 0:
            return 0.0, {"word_count": 0}

        word_char_ratio = chars_in_words / total_chars

        # Longueur moyenne des mots (mots très courts ou très longs = suspect)
        avg_word_len = chars_in_words / word_count if word_count > 0 else 0
        word_len_score = 1.0
        if avg_word_len < 2 or avg_word_len > 15:
            word_len_score = 0.5
        elif avg_word_len < 3 or avg_word_len > 12:
            word_len_score = 0.75

        # Score combiné
        score = word_char_ratio * 0.6 + word_len_score * 0.4

        return score, {
            "word_count": word_count,
            "avg_word_length": round(avg_word_len, 1),
            "word_char_ratio": round(word_char_ratio, 3)
        }

    def _compute_markers_signal(self, text: str) -> tuple[float, dict]:
        """
        Signal basé sur la présence de marqueurs OSMOSE.

        Des marqueurs OSMOSE indiquent un texte bien linéarisé.
        """
        matches = MARKER_PATTERN.findall(text)
        marker_count = len(matches)
        unique_markers = set(matches)

        # Score basé sur la diversité des marqueurs
        if marker_count == 0:
            score = 0.5  # Pas de marqueurs = neutre (texte brut)
        elif len(unique_markers) == 1:
            score = 0.7
        elif len(unique_markers) <= 3:
            score = 0.85
        else:
            score = 1.0

        return score, {
            "marker_count": marker_count,
            "unique_markers": list(unique_markers)
        }


# === Factory ===

_scorer_instance: Optional[ConfidenceScorer] = None


def get_confidence_scorer() -> ConfidenceScorer:
    """
    Récupère l'instance singleton du scorer.

    Returns:
        ConfidenceScorer instance
    """
    global _scorer_instance

    if _scorer_instance is None:
        _scorer_instance = ConfidenceScorer()
        logger.info("[ConfidenceScorer] Singleton initialized")

    return _scorer_instance


__all__ = ["ConfidenceScorer", "ConfidenceResult", "get_confidence_scorer"]
