"""
OSMOSE Linguistic Layer - Politique de Gating pour la coréférence

Ce module implémente la politique conservative + abstention pour la résolution
de coréférence, conformément aux invariants L3 et L4 de l'ADR.

Principe clé: L'abstention est préférable à une mauvaise résolution.

Critères d'admissibilité (résolution autorisée si):
- Candidat dans fenêtre courte (same/prev sentence, ou prev chunk immédiat)
- Compatibilité morpho-syntaxique (FR: genre/nombre quand possible)
- Score engine >= 0.85
- Pas de signal "non référentiel" (il pleut, it rains, c'est X)

Abstention obligatoire si:
- Plusieurs candidats valides (ambiguïté)
- Distance trop grande sans support structurel
- "Bridging" (the device → the server) non explicitement coréférentiel
- Candidats hors liste (si LLM arbiter)

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10.7
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Set

from knowbase.linguistic.coref_models import (
    MentionSpan,
    CorefDecision,
    DecisionType,
    ReasonCode,
    CorefScope,
    MentionType,
)

logger = logging.getLogger(__name__)


@dataclass
class GatingResult:
    """Résultat de l'évaluation par la politique de gating."""

    # Décision
    allowed: bool = False
    decision_type: DecisionType = DecisionType.ABSTAIN
    reason_code: ReasonCode = ReasonCode.NO_CANDIDATE
    reason_detail: str = ""

    # Candidat choisi (si résolu)
    chosen_candidate_idx: Optional[int] = None
    confidence: float = 0.0

    # Scope de la résolution
    scope: CorefScope = CorefScope.SAME_SENTENCE


@dataclass
class GatingCandidate:
    """Candidat évalué par la politique de gating."""

    # Identifiants
    mention_id: str
    surface: str

    # Position
    sentence_idx: int
    char_offset: int

    # Compatibilité morphologique (FR)
    gender: Optional[str] = None     # m | f | None
    number: Optional[str] = None     # s | p | None

    # Score de l'engine
    engine_score: float = 0.0

    # Distance
    sentence_distance: int = 0       # 0 = même phrase
    char_distance: int = 0


class CorefGatingPolicy:
    """
    Politique de gating conservative pour la résolution de coréférence.

    Invariants respectés:
    - L3: Closed-world disambiguation (candidats locaux uniquement)
    - L4: Abstention-first (ambiguïté → ABSTAIN)
    """

    # Seuil de confiance minimum (ADR: 0.85)
    DEFAULT_CONFIDENCE_THRESHOLD = 0.85

    # Distance maximale en phrases
    MAX_SENTENCE_DISTANCE = 2

    # Distance maximale en caractères (pour prev_chunk)
    MAX_CHAR_DISTANCE = 500

    # Pronoms impersonnels par langue
    IMPERSONAL_PATTERNS: Dict[str, List[re.Pattern]] = {
        "fr": [
            re.compile(r"\bil\s+(pleut|neige|fait|faut|semble|paraît|convient|s'agit)", re.IGNORECASE),
            re.compile(r"\bc'est\b", re.IGNORECASE),
            re.compile(r"\bil\s+est\s+(important|nécessaire|possible|évident|clair)", re.IGNORECASE),
        ],
        "en": [
            re.compile(r"\bit\s+(rains?|snows?|seems?|appears?)", re.IGNORECASE),
            re.compile(r"\bit\s+is\s+(important|necessary|possible|clear|evident)", re.IGNORECASE),
            re.compile(r"\bthere\s+(is|are|was|were)\b", re.IGNORECASE),
        ],
        "de": [
            re.compile(r"\bes\s+(regnet|schneit|scheint|gibt)", re.IGNORECASE),
            re.compile(r"\bes\s+ist\s+(wichtig|notwendig|möglich|klar)", re.IGNORECASE),
        ],
    }

    # Pronoms référentiels par langue
    REFERENTIAL_PRONOUNS: Dict[str, Set[str]] = {
        "fr": {"il", "elle", "ils", "elles", "celui-ci", "celle-ci", "ceux-ci", "celles-ci", "ce dernier", "cette dernière"},
        "en": {"it", "they", "them", "he", "she", "him", "her", "this", "that", "these", "those"},
        "de": {"er", "sie", "es", "dieser", "diese", "dieses", "jener", "jene", "jenes"},
    }

    # Genre grammatical des pronoms (FR)
    PRONOUN_GENDER_FR: Dict[str, str] = {
        "il": "m", "elle": "f", "ils": "m", "elles": "f",
        "celui-ci": "m", "celle-ci": "f", "ceux-ci": "m", "celles-ci": "f",
        "ce dernier": "m", "cette dernière": "f",
    }

    # Nombre grammatical des pronoms (FR)
    PRONOUN_NUMBER_FR: Dict[str, str] = {
        "il": "s", "elle": "s", "ils": "p", "elles": "p",
        "celui-ci": "s", "celle-ci": "s", "ceux-ci": "p", "celles-ci": "p",
        "ce dernier": "s", "cette dernière": "s",
    }

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_sentence_distance: int = MAX_SENTENCE_DISTANCE,
        max_char_distance: int = MAX_CHAR_DISTANCE,
    ):
        """
        Initialise la politique de gating.

        Args:
            confidence_threshold: Seuil de confiance minimum (défaut: 0.85)
            max_sentence_distance: Distance max en phrases (défaut: 2)
            max_char_distance: Distance max en caractères (défaut: 500)
        """
        self.confidence_threshold = confidence_threshold
        self.max_sentence_distance = max_sentence_distance
        self.max_char_distance = max_char_distance

    def is_non_referential(
        self,
        pronoun: str,
        sentence: str,
        lang: str = "en"
    ) -> Tuple[bool, Optional[ReasonCode]]:
        """
        Vérifie si un pronom est non-référentiel (impersonnel, explétif).

        Args:
            pronoun: Le pronom à vérifier
            sentence: La phrase contenant le pronom
            lang: Langue (en, fr, de)

        Returns:
            (is_non_ref, reason_code) - True si non-référentiel avec raison
        """
        # Vérifier les patterns impersonnels
        patterns = self.IMPERSONAL_PATTERNS.get(lang, [])
        for pattern in patterns:
            if pattern.search(sentence):
                return True, ReasonCode.IMPERSONAL

        # Vérifier si c'est un pronom référentiel connu
        pronouns = self.REFERENTIAL_PRONOUNS.get(lang, set())
        if pronoun.lower() not in pronouns:
            # Pronom inconnu - considérer comme potentiellement non-référentiel
            return True, ReasonCode.GENERIC

        return False, None

    def check_morphological_agreement(
        self,
        pronoun: str,
        candidate: GatingCandidate,
        lang: str = "fr"
    ) -> bool:
        """
        Vérifie l'accord morphologique (genre/nombre) entre pronom et candidat.

        Note: Implémenté uniquement pour le français. Pour les autres langues,
        retourne True (pas de filtre morphologique).

        Args:
            pronoun: Le pronom à résoudre
            candidate: Le candidat antécédent
            lang: Langue

        Returns:
            True si accord OK ou non vérifiable
        """
        if lang != "fr":
            return True

        pronoun_lower = pronoun.lower()

        # Genre du pronom
        pronoun_gender = self.PRONOUN_GENDER_FR.get(pronoun_lower)
        if pronoun_gender and candidate.gender:
            if pronoun_gender != candidate.gender:
                return False

        # Nombre du pronom
        pronoun_number = self.PRONOUN_NUMBER_FR.get(pronoun_lower)
        if pronoun_number and candidate.number:
            if pronoun_number != candidate.number:
                return False

        return True

    def evaluate_candidates(
        self,
        pronoun: str,
        pronoun_sentence_idx: int,
        candidates: List[GatingCandidate],
        sentence_context: str,
        lang: str = "en"
    ) -> GatingResult:
        """
        Évalue les candidats et décide de la résolution.

        Implémente la politique conservative:
        - 1 candidat valide avec confiance >= seuil → RESOLVED
        - 0 candidat → ABSTAIN (NO_CANDIDATE)
        - > 1 candidat valide → ABSTAIN (AMBIGUOUS)

        Args:
            pronoun: Le pronom à résoudre
            pronoun_sentence_idx: Index de la phrase du pronom
            candidates: Liste des candidats antécédents
            sentence_context: Contexte de la phrase pour détection impersonnel
            lang: Langue du document

        Returns:
            GatingResult avec la décision
        """
        # 1. Vérifier si non-référentiel
        is_non_ref, reason = self.is_non_referential(pronoun, sentence_context, lang)
        if is_non_ref:
            return GatingResult(
                allowed=False,
                decision_type=DecisionType.NON_REFERENTIAL,
                reason_code=reason or ReasonCode.IMPERSONAL,
                reason_detail=f"Pronom '{pronoun}' détecté comme non-référentiel",
            )

        # 2. Pas de candidats
        if not candidates:
            return GatingResult(
                allowed=False,
                decision_type=DecisionType.ABSTAIN,
                reason_code=ReasonCode.NO_CANDIDATE,
                reason_detail="Aucun candidat antécédent trouvé",
            )

        # 3. Filtrer par distance
        valid_candidates = []
        for i, candidate in enumerate(candidates):
            distance = abs(pronoun_sentence_idx - candidate.sentence_idx)

            # Vérifier distance en phrases
            if distance > self.max_sentence_distance:
                continue

            # Vérifier distance en caractères (pour prev_chunk)
            if candidate.char_distance > self.max_char_distance:
                continue

            # Vérifier accord morphologique (FR)
            if not self.check_morphological_agreement(pronoun, candidate, lang):
                continue

            # Vérifier score de confiance
            if candidate.engine_score < self.confidence_threshold:
                continue

            valid_candidates.append((i, candidate, distance))

        # 4. Décision basée sur les candidats valides
        if len(valid_candidates) == 0:
            # Candidats filtrés - abstention
            if candidates:
                return GatingResult(
                    allowed=False,
                    decision_type=DecisionType.ABSTAIN,
                    reason_code=ReasonCode.LOW_CONFIDENCE,
                    reason_detail=f"Tous les {len(candidates)} candidats sous le seuil de confiance {self.confidence_threshold}",
                )
            return GatingResult(
                allowed=False,
                decision_type=DecisionType.ABSTAIN,
                reason_code=ReasonCode.NO_CANDIDATE,
                reason_detail="Aucun candidat après filtrage",
            )

        if len(valid_candidates) > 1:
            # Ambiguïté - abstention (invariant L4)
            surfaces = [c[1].surface for c in valid_candidates[:3]]
            return GatingResult(
                allowed=False,
                decision_type=DecisionType.ABSTAIN,
                reason_code=ReasonCode.AMBIGUOUS,
                reason_detail=f"Ambiguïté: {len(valid_candidates)} candidats valides ({', '.join(surfaces)}...)",
            )

        # 5. Un seul candidat valide - résolution
        idx, chosen, distance = valid_candidates[0]

        # Déterminer le scope
        if distance == 0:
            scope = CorefScope.SAME_SENTENCE
        elif distance == 1:
            scope = CorefScope.PREV_SENTENCE
        else:
            scope = CorefScope.PREV_CHUNK

        return GatingResult(
            allowed=True,
            decision_type=DecisionType.RESOLVED,
            reason_code=ReasonCode.UNAMBIGUOUS,
            reason_detail=f"Candidat unique: '{chosen.surface}' (distance={distance}, score={chosen.engine_score:.2f})",
            chosen_candidate_idx=idx,
            confidence=chosen.engine_score,
            scope=scope,
        )

    def create_decision(
        self,
        tenant_id: str,
        doc_version_id: str,
        mention_span_key: str,
        candidates: List[GatingCandidate],
        result: GatingResult,
        method: str = "gating_policy"
    ) -> CorefDecision:
        """
        Crée un objet CorefDecision à partir du résultat de gating.

        Args:
            tenant_id: ID du tenant
            doc_version_id: ID de version du document
            mention_span_key: Clé du span de la mention
            candidates: Liste des candidats évalués
            result: Résultat du gating
            method: Méthode de résolution

        Returns:
            CorefDecision pour audit
        """
        chosen_key = None
        if result.allowed and result.chosen_candidate_idx is not None:
            chosen_key = candidates[result.chosen_candidate_idx].mention_id

        return CorefDecision(
            tenant_id=tenant_id,
            doc_version_id=doc_version_id,
            mention_span_key=mention_span_key,
            candidate_count=len(candidates),
            candidate_keys=[c.mention_id for c in candidates],
            chosen_candidate_key=chosen_key,
            decision_type=result.decision_type,
            confidence=result.confidence,
            method=method,
            reason_code=result.reason_code,
            reason_detail=result.reason_detail,
        )


def create_gating_policy(
    confidence_threshold: float = 0.85,
    max_sentence_distance: int = 2,
    max_char_distance: int = 500,
) -> CorefGatingPolicy:
    """
    Factory function pour créer une politique de gating.

    Args:
        confidence_threshold: Seuil de confiance (défaut: 0.85)
        max_sentence_distance: Distance max en phrases (défaut: 2)
        max_char_distance: Distance max en chars (défaut: 500)

    Returns:
        Instance de CorefGatingPolicy
    """
    return CorefGatingPolicy(
        confidence_threshold=confidence_threshold,
        max_sentence_distance=max_sentence_distance,
        max_char_distance=max_char_distance,
    )
