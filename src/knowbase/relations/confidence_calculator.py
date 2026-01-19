"""
OSMOSE Evidence Bundle - Confidence Calculator (Pass 3.5)

Calcul de la confiance des bundles.

Règle principale: confidence = min(tous les fragments)
Le maillon le plus faible gouverne.

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
"""

from __future__ import annotations

import logging
from typing import List, Optional

from knowbase.relations.evidence_bundle_models import (
    EvidenceBundle,
    EvidenceFragment,
    ExtractionMethodBundle,
    PredicateCandidate,
)

logger = logging.getLogger(__name__)


# ===================================
# CONFIDENCE CONSTANTS
# ===================================

# Confiance de base par méthode d'extraction
EXTRACTION_METHOD_CONFIDENCE = {
    # Textuel - Sprint 1
    ExtractionMethodBundle.CHARSPAN_EXACT: 0.95,
    ExtractionMethodBundle.CHARSPAN_EXPAND: 0.85,
    ExtractionMethodBundle.FUZZY_MATCH: 0.60,
    ExtractionMethodBundle.SPACY_DEP: 0.80,

    # Visuel - Sprint 2
    ExtractionMethodBundle.DIAGRAM_ELEMENT: 0.75,
    ExtractionMethodBundle.VISUAL_ARROW: 0.70,
    ExtractionMethodBundle.VISUAL_CAPTION: 0.65,

    # Coréférence - Sprint 2
    ExtractionMethodBundle.TOPIC_BINDING: 0.70,
    ExtractionMethodBundle.DOMINANCE_WITH_SCOPE: 0.75,
    ExtractionMethodBundle.D_PLUS_STRUCTURAL: 0.80,
}

# Bonus/malus pour le calcul
BONUS_SAME_SENTENCE = 0.05  # Bonus si sujet et objet dans même phrase
MALUS_LONG_DISTANCE = 0.10  # Malus si distance > 200 chars
MALUS_FUZZY_MATCH = 0.15    # Malus si fallback fuzzy utilisé


# ===================================
# FRAGMENT CONFIDENCE
# ===================================

def compute_fragment_confidence(
    fragment: EvidenceFragment,
    apply_bonuses: bool = True,
) -> float:
    """
    Calcule la confiance d'un fragment individuel.

    La confiance de base vient de la méthode d'extraction,
    avec ajustements optionnels.

    Args:
        fragment: Fragment à évaluer
        apply_bonuses: Si True, applique les bonus/malus

    Returns:
        Score de confiance [0.0-1.0]
    """
    # Confiance de base selon la méthode
    base_confidence = EXTRACTION_METHOD_CONFIDENCE.get(
        fragment.extraction_method, 0.70
    )

    # Si le fragment a déjà une confiance, utiliser le min
    if fragment.confidence > 0:
        base_confidence = min(base_confidence, fragment.confidence)

    return max(0.0, min(1.0, base_confidence))


def compute_entity_fragment_confidence(
    text: str,
    char_start: Optional[int],
    char_end: Optional[int],
    extraction_method: ExtractionMethodBundle,
    label: str,
) -> float:
    """
    Calcule la confiance pour un fragment entité.

    Args:
        text: Texte extrait
        char_start: Position début
        char_end: Position fin
        extraction_method: Méthode d'extraction
        label: Label attendu de l'entité

    Returns:
        Score de confiance [0.0-1.0]
    """
    # Base selon méthode
    confidence = EXTRACTION_METHOD_CONFIDENCE.get(extraction_method, 0.70)

    # Bonus si le texte correspond exactement au label
    if text.lower().strip() == label.lower().strip():
        confidence = min(1.0, confidence + 0.05)

    # Malus si charspan manquant
    if char_start is None or char_end is None:
        confidence -= 0.15

    # Malus si texte très court (< 2 chars)
    if len(text.strip()) < 2:
        confidence -= 0.10

    return max(0.0, min(1.0, confidence))


def compute_predicate_confidence(
    candidate: PredicateCandidate,
) -> float:
    """
    Calcule la confiance pour un prédicat candidat.

    Args:
        candidate: Prédicat candidat

    Returns:
        Score de confiance [0.0-1.0]
    """
    # Utiliser la confiance structurelle du candidat
    confidence = candidate.structure_confidence

    # Malus si auxiliaire, copule ou modal
    if candidate.is_auxiliary:
        confidence -= 0.30
    if candidate.is_copula:
        confidence -= 0.20
    if candidate.is_modal:
        confidence -= 0.15

    # Bonus si complément prépositionnel (structure plus riche)
    if candidate.has_prep_complement:
        confidence += 0.05

    return max(0.0, min(1.0, confidence))


# ===================================
# BUNDLE CONFIDENCE
# ===================================

def compute_bundle_confidence(
    subject_confidence: float,
    object_confidence: float,
    predicate_confidences: List[float],
    link_confidence: Optional[float] = None,
) -> float:
    """
    Calcule la confiance globale d'un bundle.

    Règle: confidence = min(EA, EB, EP, [EL])
    Le maillon le plus faible gouverne.

    Args:
        subject_confidence: Confiance du sujet (EA)
        object_confidence: Confiance de l'objet (EB)
        predicate_confidences: Confiances des prédicats (EP)
        link_confidence: Confiance du lien (EL) - Sprint 2

    Returns:
        Score de confiance global [0.0-1.0]
    """
    # Collecter toutes les confiances
    all_confidences = [subject_confidence, object_confidence]

    # Ajouter la confiance du meilleur prédicat
    if predicate_confidences:
        all_confidences.append(max(predicate_confidences))
    else:
        # Pas de prédicat = confiance minimale
        all_confidences.append(0.0)

    # Ajouter la confiance du lien si présent (Sprint 2)
    if link_confidence is not None:
        all_confidences.append(link_confidence)

    # Min de toutes les confiances
    return min(all_confidences)


def compute_bundle_confidence_from_fragments(
    evidence_subject: EvidenceFragment,
    evidence_object: EvidenceFragment,
    evidence_predicates: List[EvidenceFragment],
    evidence_link: Optional[EvidenceFragment] = None,
) -> float:
    """
    Calcule la confiance d'un bundle à partir de ses fragments.

    Args:
        evidence_subject: Fragment sujet
        evidence_object: Fragment objet
        evidence_predicates: Fragments prédicat
        evidence_link: Fragment lien (optionnel, Sprint 2)

    Returns:
        Score de confiance global [0.0-1.0]
    """
    subject_conf = compute_fragment_confidence(evidence_subject)
    object_conf = compute_fragment_confidence(evidence_object)

    predicate_confs = [
        compute_fragment_confidence(ep) for ep in evidence_predicates
    ]

    link_conf = None
    if evidence_link:
        link_conf = compute_fragment_confidence(evidence_link)

    return compute_bundle_confidence(
        subject_conf, object_conf, predicate_confs, link_conf
    )


def update_bundle_confidence(bundle: EvidenceBundle) -> EvidenceBundle:
    """
    Recalcule et met à jour la confiance d'un bundle.

    Args:
        bundle: Bundle à mettre à jour

    Returns:
        Bundle avec confiance mise à jour
    """
    bundle.confidence = compute_bundle_confidence_from_fragments(
        bundle.evidence_subject,
        bundle.evidence_object,
        bundle.evidence_predicate,
        bundle.evidence_link,
    )

    logger.debug(
        f"[OSMOSE:Pass3.5] Bundle {bundle.bundle_id} confidence updated: "
        f"{bundle.confidence:.3f}"
    )

    return bundle


# ===================================
# TYPING CONFIDENCE
# ===================================

def compute_typing_confidence(
    predicate_text: str,
    relation_type: str,
    predicate_confidence: float,
) -> float:
    """
    Calcule la confiance sur le typage de la relation.

    Sprint 1: Typage direct via le lemme du prédicat.
    La confiance dépend de la clarté du mapping.

    Args:
        predicate_text: Texte du prédicat
        relation_type: Type de relation candidat
        predicate_confidence: Confiance sur le prédicat

    Returns:
        Score de confiance sur le typage [0.0-1.0]
    """
    # Sprint 1: La confiance du typage hérite de celle du prédicat
    # avec un léger malus car le mapping peut être ambigu
    typing_confidence = predicate_confidence * 0.9

    return max(0.0, min(1.0, typing_confidence))


# ===================================
# PROXIMITY ADJUSTMENTS
# ===================================

def adjust_confidence_for_proximity(
    base_confidence: float,
    subject_char_start: Optional[int],
    subject_char_end: Optional[int],
    object_char_start: Optional[int],
    object_char_end: Optional[int],
) -> float:
    """
    Ajuste la confiance selon la proximité textuelle.

    Bonus si très proches, malus si très éloignés.

    Args:
        base_confidence: Confiance de base
        subject_char_start: Début du sujet
        subject_char_end: Fin du sujet
        object_char_start: Début de l'objet
        object_char_end: Fin de l'objet

    Returns:
        Confiance ajustée
    """
    # Si pas de charspans, retourner la confiance de base
    if (
        subject_char_start is None
        or subject_char_end is None
        or object_char_start is None
        or object_char_end is None
    ):
        return base_confidence

    # Calculer la distance
    if subject_char_end <= object_char_start:
        distance = object_char_start - subject_char_end
    elif object_char_end <= subject_char_start:
        distance = subject_char_start - object_char_end
    else:
        distance = 0  # Chevauchement

    # Ajustements
    adjusted = base_confidence

    if distance <= 50:
        # Très proche: bonus
        adjusted += BONUS_SAME_SENTENCE
    elif distance > 200:
        # Éloigné: malus
        adjusted -= MALUS_LONG_DISTANCE

    return max(0.0, min(1.0, adjusted))
