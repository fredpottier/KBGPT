"""
OSMOSE Linguistic Layer - Gating Named↔Named pour la coréférence

Ce module implémente la politique de gating pour les paires d'entités nommées
(Named↔Named), conformément à l'ADR ADR_COREF_NAMED_NAMED_VALIDATION.md.

Principe clé: Modèle "signaux de risque" - pas de règles guillotine.
Seuls les cas extrêmes (similarité très faible ou tokens disjoints) justifient
un REJECT direct. Les autres signaux (head noun, TF-IDF) incrémentent un score
de risque qui peut mener à REVIEW (arbitrage LLM).

Ref: doc/ongoing/ADR_COREF_NAMED_NAMED_VALIDATION.md
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List, Set

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from knowbase.linguistic.coref_models import ReasonCode, DecisionType

logger = logging.getLogger(__name__)


class GatingDecision(str, Enum):
    """Décision du gating Named↔Named."""
    ACCEPT = "ACCEPT"   # Coréférence acceptée directement
    REVIEW = "REVIEW"   # Zone grise, nécessite arbitrage LLM
    REJECT = "REJECT"   # Coréférence rejetée directement


@dataclass
class NamedGatingResult:
    """Résultat de l'évaluation Named↔Named."""
    decision: GatingDecision
    reason_code: ReasonCode
    reason_detail: str

    # Métriques calculées (pour debug/audit)
    jaro_winkler: float = 0.0
    token_jaccard: float = 0.0
    head_noun_match: bool = True
    risk_score: int = 0

    def __repr__(self) -> str:
        return (
            f"NamedGatingResult({self.decision.value}, {self.reason_code.value}, "
            f"jw={self.jaro_winkler:.2f}, tj={self.token_jaccard:.2f}, "
            f"head_match={self.head_noun_match}, risk={self.risk_score})"
        )


class NamedNamedGatingPolicy:
    """
    Politique de gating pour les paires Named↔Named.

    Implémente le modèle "signaux de risque" de l'ADR:
    - REJECT direct si similarité très faible ou tokens disjoints
    - ACCEPT direct si similarité très haute
    - Sinon, accumule des signaux de risque et décide ACCEPT/REVIEW

    Cette classe est agnostique au domaine - aucun catalogue métier.
    """

    # Seuils pour REJECT direct
    JARO_WINKLER_REJECT_THRESHOLD = 0.55

    # Seuils pour ACCEPT direct
    JARO_WINKLER_ACCEPT_THRESHOLD = 0.95
    TOKEN_JACCARD_ACCEPT_THRESHOLD = 0.8

    # Seuils pour signaux de risque
    JARO_WINKLER_RISK_LOWER = 0.55
    JARO_WINKLER_RISK_UPPER = 0.85
    TOKEN_JACCARD_RISK_LOWER = 0.1
    TOKEN_JACCARD_RISK_UPPER = 0.5

    def __init__(
        self,
        jaro_reject_threshold: float = JARO_WINKLER_REJECT_THRESHOLD,
        jaro_accept_threshold: float = JARO_WINKLER_ACCEPT_THRESHOLD,
        jaccard_accept_threshold: float = TOKEN_JACCARD_ACCEPT_THRESHOLD,
    ):
        """
        Initialise la politique de gating.

        Args:
            jaro_reject_threshold: Seuil Jaro-Winkler pour REJECT (défaut: 0.55)
            jaro_accept_threshold: Seuil Jaro-Winkler pour ACCEPT (défaut: 0.95)
            jaccard_accept_threshold: Seuil Token Jaccard pour ACCEPT (défaut: 0.8)
        """
        self.jaro_reject_threshold = jaro_reject_threshold
        self.jaro_accept_threshold = jaro_accept_threshold
        self.jaccard_accept_threshold = jaccard_accept_threshold

    def _normalize_text(self, text: str) -> str:
        """Normalise le texte pour comparaison."""
        # Lowercase, supprime ponctuation excessive, collapse espaces
        text = text.lower().strip()
        text = re.sub(r'[^\w\s/-]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenize le texte en ensemble de tokens."""
        normalized = self._normalize_text(text)
        # Split sur espaces et slashes
        tokens = re.split(r'[\s/]+', normalized)
        # Filtrer tokens vides et très courts
        return {t for t in tokens if len(t) > 1}

    def _compute_jaro_winkler(self, a: str, b: str) -> float:
        """Calcule la similarité Jaro-Winkler entre deux strings."""
        norm_a = self._normalize_text(a)
        norm_b = self._normalize_text(b)
        return JaroWinkler.similarity(norm_a, norm_b)

    def _compute_token_jaccard(self, a: str, b: str) -> float:
        """Calcule le coefficient de Jaccard sur les tokens."""
        tokens_a = self._tokenize(a)
        tokens_b = self._tokenize(b)

        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _extract_head_noun(self, text: str) -> str:
        """
        Extrait la tête nominale (dernier token significatif).

        Heuristique simple: le dernier token non-générique.
        Pour une extraction plus précise, utiliser spaCy.
        """
        tokens = list(self._tokenize(text))
        if not tokens:
            return ""

        # Filtrer les tokens génériques
        generic_tokens = {'the', 'a', 'an', 'this', 'that', 'for', 'with', 'of', 'in'}
        significant_tokens = [t for t in tokens if t not in generic_tokens]

        if not significant_tokens:
            return tokens[-1] if tokens else ""

        # Retourner le dernier token significatif
        return significant_tokens[-1]

    def _check_head_noun_match(self, a: str, b: str) -> bool:
        """
        Vérifie si les têtes nominales correspondent.

        IMPORTANT: Cette fonction est stricte pour éviter les faux positifs
        comme "Product X2000" vs "Product X" où les têtes sont "x2000" vs "x".
        """
        head_a = self._extract_head_noun(a)
        head_b = self._extract_head_noun(b)

        if not head_a or not head_b:
            return True  # Pas de signal si extraction échoue

        # Match exact
        if head_a == head_b:
            return True

        # Cas spécial: versions numériques (ex: "s4hana" vs "hana")
        # Si l'un est préfixé par un chiffre/lettre et l'autre non → mismatch
        # Exemples: "4hana" vs "hana", "s4hana" vs "hana"
        if head_a.endswith(head_b) or head_b.endswith(head_a):
            shorter = head_a if len(head_a) < len(head_b) else head_b
            longer = head_b if len(head_a) < len(head_b) else head_a
            prefix = longer[:-len(shorter)]

            # Si le préfixe contient un chiffre ou est significatif → mismatch
            if any(c.isdigit() for c in prefix) or len(prefix) > 1:
                return False

            # Préfixe court sans chiffre (ex: "shana" vs "hana") → potentiellement OK
            return True

        # Vérifier similarité Jaro-Winkler des têtes (>= 0.9 pour match)
        head_similarity = JaroWinkler.similarity(head_a, head_b)
        if head_similarity >= 0.9:
            return True

        return False

    def evaluate(
        self,
        surface_a: str,
        surface_b: str,
        context_a: Optional[str] = None,
        context_b: Optional[str] = None,
    ) -> NamedGatingResult:
        """
        Évalue une paire Named↔Named.

        Args:
            surface_a: Surface de la première mention
            surface_b: Surface de la seconde mention
            context_a: Contexte autour de la première mention (optionnel)
            context_b: Contexte autour de la seconde mention (optionnel)

        Returns:
            NamedGatingResult avec la décision et les métriques
        """
        # Calculer les métriques
        jw = self._compute_jaro_winkler(surface_a, surface_b)
        tj = self._compute_token_jaccard(surface_a, surface_b)
        head_match = self._check_head_noun_match(surface_a, surface_b)

        # === REJECT direct (cas extrêmes) ===
        if jw < self.jaro_reject_threshold:
            return NamedGatingResult(
                decision=GatingDecision.REJECT,
                reason_code=ReasonCode.STRING_SIMILARITY_LOW,
                reason_detail=f"Jaro-Winkler {jw:.2f} < {self.jaro_reject_threshold}",
                jaro_winkler=jw,
                token_jaccard=tj,
                head_noun_match=head_match,
                risk_score=0,
            )

        if tj == 0:
            return NamedGatingResult(
                decision=GatingDecision.REJECT,
                reason_code=ReasonCode.NO_TOKEN_OVERLAP,
                reason_detail="Aucun token commun entre les mentions",
                jaro_winkler=jw,
                token_jaccard=tj,
                head_noun_match=head_match,
                risk_score=0,
            )

        # === ACCEPT direct (similarité très haute) ===
        if jw >= self.jaro_accept_threshold and tj >= self.jaccard_accept_threshold:
            return NamedGatingResult(
                decision=GatingDecision.ACCEPT,
                reason_code=ReasonCode.HIGH_SIMILARITY,
                reason_detail=f"Haute similarité: jw={jw:.2f}, tj={tj:.2f}",
                jaro_winkler=jw,
                token_jaccard=tj,
                head_noun_match=head_match,
                risk_score=0,
            )

        # === Accumulation de signaux de risque ===
        risk = 0
        risk_factors = []

        if not head_match:
            risk += 1
            risk_factors.append("head_noun_mismatch")

        if self.JARO_WINKLER_RISK_LOWER <= jw <= self.JARO_WINKLER_RISK_UPPER:
            risk += 1
            risk_factors.append(f"jw_zone_grise({jw:.2f})")

        if self.TOKEN_JACCARD_RISK_LOWER < tj < self.TOKEN_JACCARD_RISK_UPPER:
            risk += 1
            risk_factors.append(f"tj_faible({tj:.2f})")

        # === Décision finale ===
        if risk == 0:
            return NamedGatingResult(
                decision=GatingDecision.ACCEPT,
                reason_code=ReasonCode.LOW_RISK,
                reason_detail=f"Aucun signal de risque: jw={jw:.2f}, tj={tj:.2f}",
                jaro_winkler=jw,
                token_jaccard=tj,
                head_noun_match=head_match,
                risk_score=risk,
            )

        # Zone grise → REVIEW (arbitrage LLM)
        return NamedGatingResult(
            decision=GatingDecision.REVIEW,
            reason_code=ReasonCode.NEEDS_LLM_VALIDATION,
            reason_detail=f"Signaux de risque ({risk}): {', '.join(risk_factors)}",
            jaro_winkler=jw,
            token_jaccard=tj,
            head_noun_match=head_match,
            risk_score=risk,
        )

    def evaluate_batch(
        self,
        pairs: List[Tuple[str, str]],
    ) -> List[NamedGatingResult]:
        """
        Évalue un batch de paires Named↔Named.

        Args:
            pairs: Liste de tuples (surface_a, surface_b)

        Returns:
            Liste de NamedGatingResult
        """
        return [self.evaluate(a, b) for a, b in pairs]


def create_named_gating_policy(
    jaro_reject_threshold: float = 0.55,
    jaro_accept_threshold: float = 0.95,
    jaccard_accept_threshold: float = 0.8,
) -> NamedNamedGatingPolicy:
    """
    Factory function pour créer une politique de gating Named↔Named.

    Args:
        jaro_reject_threshold: Seuil Jaro-Winkler pour REJECT
        jaro_accept_threshold: Seuil Jaro-Winkler pour ACCEPT
        jaccard_accept_threshold: Seuil Token Jaccard pour ACCEPT

    Returns:
        Instance de NamedNamedGatingPolicy
    """
    return NamedNamedGatingPolicy(
        jaro_reject_threshold=jaro_reject_threshold,
        jaro_accept_threshold=jaro_accept_threshold,
        jaccard_accept_threshold=jaccard_accept_threshold,
    )


# Export
__all__ = [
    "GatingDecision",
    "NamedGatingResult",
    "NamedNamedGatingPolicy",
    "create_named_gating_policy",
]
