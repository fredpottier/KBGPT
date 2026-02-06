"""
OSMOSE Verification - Truth Regimes

Détection du régime de vérité basé sur le langage utilisé.
Le régime détermine la strictness de la comparaison.

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

import re
from enum import Enum
from typing import List, Tuple, Optional
from dataclasses import dataclass


class TruthRegime(str, Enum):
    """
    Régimes de vérité déterminant la strictness de comparaison.

    La détection est basée sur le LANGAGE utilisé, pas le domaine.
    Cela évite le biais de classification contextuelle.
    """

    NORMATIVE_STRICT = "NORMATIVE_STRICT"
    # Mots-clés: must, shall, required, SLA, contract, guarantee
    # → Match exact requis, aucune tolérance

    NORMATIVE_BOUNDED = "NORMATIVE_BOUNDED"
    # Mots-clés: at least, at most, minimum, maximum, ≤, ≥, up to
    # → Logique d'inégalités, direction compte

    EMPIRICAL_STATISTICAL = "EMPIRICAL_STATISTICAL"
    # Mots-clés: p-value, CI, confidence interval, ±, error margin
    # → Comparaison statistique, intervalles de confiance

    DESCRIPTIVE_APPROX = "DESCRIPTIVE_APPROX"
    # Mots-clés: about, approximately, around, ~, roughly, circa
    # → Tolérance autorisée (calculée, pas fixe)

    CONDITIONAL_SCOPE = "CONDITIONAL_SCOPE"
    # Mots-clés: depends on, for, when, if, in case of, given that
    # → Vérité indexée par contexte, scope requis

    TEXTUAL_SEMANTIC = "TEXTUAL_SEMANTIC"
    # Pas de valeur comparable détectée
    # → Fallback LLM pour analyse sémantique


@dataclass
class RegimeDetection:
    """Résultat de détection de régime."""
    regime: TruthRegime
    confidence: float  # 0.0 - 1.0
    matched_patterns: List[str]  # Patterns qui ont matché
    hedge_strength: float  # Force du hedge (0 = certain, 1 = très incertain)


class TruthRegimeDetector:
    """
    Détecte le régime de vérité à partir du texte.

    Stratégie: patterns regex ordonnés par priorité.
    Le premier régime matché avec haute confiance gagne.
    """

    # Patterns par régime, ordonnés par spécificité
    PATTERNS: List[Tuple[TruthRegime, List[Tuple[str, float]], float]] = [
        # (régime, [(pattern, weight), ...], base_confidence)

        # NORMATIVE_STRICT - Langage contractuel/obligatoire
        (TruthRegime.NORMATIVE_STRICT, [
            (r'\b(must|shall|required|obligatory|mandatory)\b', 1.0),
            (r'\b(guarantee[ds]?|warranted|committed)\b', 0.9),
            (r'\bSLA\b', 0.95),
            (r'\b(contract|contractual|binding)\b', 0.9),
            (r'\b(exactly|precisely|strictly)\b', 0.85),
            (r'\b(doit|obligatoire|garanti|contractuel)\b', 0.9),  # Français
            (r'\b(niveau\s+de\s+service)\b', 0.85),  # Français
        ], 0.90),

        # NORMATIVE_BOUNDED - Inégalités et bornes
        (TruthRegime.NORMATIVE_BOUNDED, [
            (r'\b(at\s+least|at\s+most|minimum|maximum)\b', 1.0),
            (r'[≤≥]', 1.0),
            (r'\b(>=|<=|>|<)\s*\d', 0.95),
            (r'\b(up\s+to|no\s+more\s+than|no\s+less\s+than)\b', 0.9),
            (r'\b(minimum|maximum|max|min)\s*[:\s]\s*\d', 0.9),
            (r'\b(au\s+moins|au\s+plus|jusqu\'?à)\b', 0.9),  # Français
            (r'\b(limite|plafond|plancher)\b', 0.8),  # Français
        ], 0.85),

        # EMPIRICAL_STATISTICAL - Statistiques et intervalles de confiance
        (TruthRegime.EMPIRICAL_STATISTICAL, [
            (r'\bp[\s-]?value\b', 1.0),
            (r'\bCI\s*[:\s]?\s*\d', 0.95),
            (r'\bconfidence\s+interval\b', 1.0),
            (r'±\s*\d', 0.95),
            (r'\berror\s+margin\b', 0.9),
            (r'\bstandard\s+deviation\b', 0.9),
            (r'\bstatistically\s+significant\b', 0.9),
            (r'\bintervalle\s+de\s+confiance\b', 1.0),  # Français
            (r'\bmarge\s+d\'?erreur\b', 0.9),  # Français
        ], 0.90),

        # CONDITIONAL_SCOPE - Vérité conditionnelle
        (TruthRegime.CONDITIONAL_SCOPE, [
            (r'\b(depends\s+on|depending\s+on)\b', 1.0),
            (r'\b(when|if|in\s+case\s+of|given\s+that)\b', 0.85),
            (r'\b(for|with)\s+\w+\s+(edition|version|mode|option)\b', 0.9),
            (r'\b(based\s+on|according\s+to)\b', 0.8),
            (r'\b(dépend\s+de|selon|en\s+fonction\s+de)\b', 1.0),  # Français
            (r'\b(si|quand|lorsque|dans\s+le\s+cas)\b', 0.8),  # Français
            (r'\b(pour\s+l\'?édition|pour\s+la\s+version)\b', 0.9),  # Français
        ], 0.80),

        # DESCRIPTIVE_APPROX - Approximations
        (TruthRegime.DESCRIPTIVE_APPROX, [
            (r'\b(about|approximately|around|roughly|circa)\b', 1.0),
            (r'~\s*\d', 0.95),
            (r'\b(typically|generally|usually|often)\b', 0.8),
            (r'\b(estimated|estimate)\b', 0.85),
            (r'\b(environ|approximativement|à\s+peu\s+près)\b', 1.0),  # Français
            (r'\b(généralement|typiquement|en\s+moyenne)\b', 0.8),  # Français
        ], 0.75),
    ]

    # Hedge words qui réduisent la certitude
    HEDGE_PATTERNS: List[Tuple[str, float]] = [
        (r'\b(may|might|could|possibly|perhaps)\b', 0.4),
        (r'\b(some|sometimes|occasionally)\b', 0.3),
        (r'\b(seems|appears|looks\s+like)\b', 0.35),
        (r'\b(probably|likely|unlikely)\b', 0.35),
        (r'\b(peut-être|possiblement|éventuellement)\b', 0.4),  # Français
        (r'\b(semble|paraît|apparemment)\b', 0.35),  # Français
    ]

    def __init__(self):
        # Pré-compiler les patterns pour performance
        self._compiled_patterns = []
        for regime, patterns, base_conf in self.PATTERNS:
            compiled = [(re.compile(p, re.IGNORECASE), w) for p, w in patterns]
            self._compiled_patterns.append((regime, compiled, base_conf))

        self._hedge_patterns = [
            (re.compile(p, re.IGNORECASE), w)
            for p, w in self.HEDGE_PATTERNS
        ]

    def detect(self, text: str) -> RegimeDetection:
        """
        Détecte le régime de vérité pour un texte.

        Args:
            text: Le texte à analyser

        Returns:
            RegimeDetection avec régime, confiance et patterns matchés
        """
        if not text or len(text.strip()) < 3:
            return RegimeDetection(
                regime=TruthRegime.TEXTUAL_SEMANTIC,
                confidence=0.5,
                matched_patterns=[],
                hedge_strength=0.0
            )

        # 1. Détecter hedge strength
        hedge_strength = self._detect_hedge_strength(text)

        # 2. Chercher les patterns par régime
        best_regime = TruthRegime.TEXTUAL_SEMANTIC
        best_confidence = 0.0
        best_patterns: List[str] = []

        for regime, patterns, base_conf in self._compiled_patterns:
            matches = []
            total_weight = 0.0

            for pattern, weight in patterns:
                if pattern.search(text):
                    matches.append(pattern.pattern)
                    total_weight += weight

            if matches:
                # Confiance = base * (poids normalisé) * (1 - hedge)
                normalized_weight = min(1.0, total_weight / len(patterns))
                confidence = base_conf * normalized_weight * (1.0 - hedge_strength * 0.3)

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_regime = regime
                    best_patterns = matches

        # 3. Si aucun match, fallback TEXTUAL_SEMANTIC
        if not best_patterns:
            return RegimeDetection(
                regime=TruthRegime.TEXTUAL_SEMANTIC,
                confidence=0.5,
                matched_patterns=[],
                hedge_strength=hedge_strength
            )

        return RegimeDetection(
            regime=best_regime,
            confidence=best_confidence,
            matched_patterns=best_patterns,
            hedge_strength=hedge_strength
        )

    def _detect_hedge_strength(self, text: str) -> float:
        """Détecte la force des hedges (incertitude) dans le texte."""
        total_hedge = 0.0

        for pattern, weight in self._hedge_patterns:
            if pattern.search(text):
                total_hedge += weight

        # Normaliser entre 0 et 1
        return min(1.0, total_hedge)

    def is_strict_regime(self, regime: TruthRegime) -> bool:
        """Vérifie si un régime requiert une comparaison stricte."""
        return regime in {
            TruthRegime.NORMATIVE_STRICT,
            TruthRegime.EMPIRICAL_STATISTICAL,  # p-values = stricts
        }

    def allows_tolerance(self, regime: TruthRegime) -> bool:
        """Vérifie si un régime permet une tolérance."""
        return regime == TruthRegime.DESCRIPTIVE_APPROX
