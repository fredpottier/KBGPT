"""
OSMOSE Evidence Bundle - Predicate Extractor (Pass 3.5)

Extraction de prédicats entre entités via spaCy.

Sprint 1: Extraction basée sur les Universal Dependencies (POS, DEP, Morph).
Principe d'agnosticité: raisonner sur la FORME, jamais sur le CONTENU.

Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import spacy
from spacy.tokens import Doc, Span, Token

from knowbase.relations.evidence_bundle_models import PredicateCandidate

logger = logging.getLogger(__name__)


# ===================================
# SPACY MODEL LOADING
# ===================================

# Cache global pour le modèle spaCy
_nlp_cache: dict[str, spacy.Language] = {}


def get_spacy_model(lang: str = "fr") -> spacy.Language:
    """
    Charge et cache le modèle spaCy approprié.

    Args:
        lang: Code langue ("fr", "en", "de", etc.)

    Returns:
        Modèle spaCy chargé
    """
    global _nlp_cache

    # Mapping langue -> modèle
    model_map = {
        "fr": "fr_core_news_md",
        "en": "en_core_web_md",
        "de": "de_core_news_md",
        "multi": "xx_ent_wiki_sm",  # Fallback multilingue
    }

    model_name = model_map.get(lang, model_map["multi"])

    if model_name not in _nlp_cache:
        try:
            _nlp_cache[model_name] = spacy.load(model_name)
            logger.info(f"[OSMOSE:Pass3.5] Loaded spaCy model: {model_name}")
        except OSError:
            # Fallback sur modèle multilingue
            logger.warning(
                f"[OSMOSE:Pass3.5] Model {model_name} not found, falling back to multi"
            )
            if "xx_ent_wiki_sm" not in _nlp_cache:
                _nlp_cache["xx_ent_wiki_sm"] = spacy.load("xx_ent_wiki_sm")
            return _nlp_cache["xx_ent_wiki_sm"]

    return _nlp_cache[model_name]


# ===================================
# ENTITY LOCALIZATION
# ===================================

def locate_entity_in_doc(
    doc: Doc,
    char_start: int,
    char_end: int,
    label: str,
) -> Optional[Span]:
    """
    Localise une entité dans le document spaCy via charspan.

    Stratégie:
    1. Essayer char_span exact
    2. Essayer char_span avec alignment_mode="expand"
    3. Fallback: recherche fuzzy sur le label

    Args:
        doc: Document spaCy parsé
        char_start: Position début (caractère)
        char_end: Position fin (caractère)
        label: Label de l'entité pour fallback

    Returns:
        Span spaCy ou None si non trouvé
    """
    # Stratégie 1: char_span exact
    span = doc.char_span(char_start, char_end)
    if span is not None:
        return span

    # Stratégie 2: char_span avec expansion
    span = doc.char_span(char_start, char_end, alignment_mode="expand")
    if span is not None:
        return span

    # Stratégie 3: Fallback fuzzy sur label
    label_lower = label.lower()
    for token in doc:
        if token.text.lower() == label_lower:
            return doc[token.i : token.i + 1]

    # Recherche sous-chaîne
    text_lower = doc.text.lower()
    idx = text_lower.find(label_lower)
    if idx != -1:
        span = doc.char_span(idx, idx + len(label), alignment_mode="expand")
        if span is not None:
            return span

    logger.warning(
        f"[OSMOSE:Pass3.5] Could not locate entity '{label}' "
        f"at char [{char_start}:{char_end}]"
    )
    return None


# ===================================
# POS-BASED DETECTION (Agnostic)
# ===================================

def is_auxiliary_verb(token: Token) -> bool:
    """
    Détecte si un token est un verbe auxiliaire.

    Utilise POS=AUX des Universal Dependencies.
    Agnostique à la langue (pas de liste de mots).

    Args:
        token: Token spaCy

    Returns:
        True si auxiliaire
    """
    return token.pos_ == "AUX"


def is_copula_or_attributive(token: Token) -> bool:
    """
    Détecte si un token fait partie d'une structure copule/attributive.

    Utilise les relations de dépendance Universal Dependencies:
    - cop: relation copule
    - attr: attribut
    - acomp: complément adjectival

    Args:
        token: Token spaCy

    Returns:
        True si structure copule/attributive
    """
    # Le token est une copule
    if token.dep_ == "cop":
        return True

    # Le token a un enfant copule
    for child in token.children:
        if child.dep_ == "cop":
            return True

    # Le token est dans une relation attributive
    if token.dep_ in ("attr", "acomp"):
        return True

    return False


def is_modal_or_intentional(token: Token) -> bool:
    """
    Détecte si un token est modal ou intentionnel.

    Utilise les features morphologiques Universal Dependencies:
    - Vérifie si le token gouverne un infinitif (VerbForm=Inf)

    Args:
        token: Token spaCy

    Returns:
        True si modal/intentionnel
    """
    # Vérifie si le token a un complément infinitif
    for child in token.children:
        morph = child.morph.get("VerbForm")
        if morph and "Inf" in morph:
            return True

        # xcomp avec infinitif
        if child.dep_ == "xcomp" and child.pos_ == "VERB":
            child_morph = child.morph.get("VerbForm")
            if child_morph and "Inf" in child_morph:
                return True

    return False


def is_generic_verb(token: Token) -> bool:
    """
    Détecte si un verbe est trop générique pour former une relation.

    Sprint 1: Un verbe est générique si:
    - C'est un auxiliaire (POS=AUX)
    - C'est une copule/attributif
    - C'est un modal/intentionnel

    Agnostique à la langue (pas de liste hardcodée).

    Args:
        token: Token spaCy

    Returns:
        True si verbe générique
    """
    if is_auxiliary_verb(token):
        return True

    if is_copula_or_attributive(token):
        return True

    if is_modal_or_intentional(token):
        return True

    return False


# ===================================
# PREDICATE EXTRACTION
# ===================================

def get_predicate_between_entities(
    doc: Doc,
    subject_span: Span,
    object_span: Span,
) -> List[PredicateCandidate]:
    """
    Extrait les prédicats candidats entre deux entités.

    Cherche les verbes (VERB) entre les positions des entités.

    Args:
        doc: Document spaCy
        subject_span: Span du sujet
        object_span: Span de l'objet

    Returns:
        Liste de PredicateCandidate
    """
    candidates: List[PredicateCandidate] = []

    # Déterminer l'ordre (qui vient en premier dans le texte)
    if subject_span.start < object_span.start:
        start_idx = subject_span.end
        end_idx = object_span.start
    else:
        start_idx = object_span.end
        end_idx = subject_span.start

    # Chercher les verbes entre les deux entités
    for token in doc[start_idx:end_idx]:
        if token.pos_ == "VERB":
            candidate = PredicateCandidate(
                text=token.text,
                lemma=token.lemma_,
                pos=token.pos_,
                dep=token.dep_,
                char_start=token.idx,
                char_end=token.idx + len(token.text),
                token_index=token.i,
                is_auxiliary=is_auxiliary_verb(token),
                is_copula=is_copula_or_attributive(token),
                is_modal=is_modal_or_intentional(token),
                has_prep_complement=_has_prep_complement(token),
                structure_confidence=_compute_structure_confidence(token),
            )
            candidates.append(candidate)

    return candidates


def _has_prep_complement(token: Token) -> bool:
    """
    Vérifie si le token a un complément prépositionnel.

    Args:
        token: Token verbe

    Returns:
        True si complément prépositionnel présent
    """
    for child in token.children:
        if child.dep_ in ("prep", "obl", "nmod"):
            return True
    return False


def _compute_structure_confidence(token: Token) -> float:
    """
    Calcule la confiance structurelle d'un prédicat.

    Args:
        token: Token verbe

    Returns:
        Score de confiance [0.0-1.0]
    """
    confidence = 0.8  # Base

    # Bonus si verbe principal (ROOT ou relié directement au ROOT)
    if token.dep_ == "ROOT":
        confidence += 0.1
    elif token.head.dep_ == "ROOT":
        confidence += 0.05

    # Malus si auxiliaire ou copule
    if is_auxiliary_verb(token):
        confidence -= 0.3
    if is_copula_or_attributive(token):
        confidence -= 0.2
    if is_modal_or_intentional(token):
        confidence -= 0.15

    return max(0.0, min(1.0, confidence))


def extract_predicate_from_context(
    doc: Doc,
    subject_span: Span,
    object_span: Span,
) -> Optional[PredicateCandidate]:
    """
    Extrait le meilleur prédicat entre deux entités.

    Stratégie:
    1. Chercher verbes entre les entités
    2. Filtrer les verbes génériques
    3. Retourner le meilleur candidat (plus haute confiance)

    Args:
        doc: Document spaCy
        subject_span: Span du sujet
        object_span: Span de l'objet

    Returns:
        Meilleur PredicateCandidate ou None
    """
    candidates = get_predicate_between_entities(doc, subject_span, object_span)

    if not candidates:
        logger.debug(
            f"[OSMOSE:Pass3.5] No verb found between "
            f"'{subject_span.text}' and '{object_span.text}'"
        )
        return None

    # Filtrer les verbes génériques
    valid_candidates = [c for c in candidates if not is_generic_verb_candidate(c)]

    if not valid_candidates:
        logger.debug(
            f"[OSMOSE:Pass3.5] All verbs are generic between "
            f"'{subject_span.text}' and '{object_span.text}'"
        )
        return None

    # Retourner le meilleur (plus haute confiance)
    return max(valid_candidates, key=lambda c: c.structure_confidence)


def is_generic_verb_candidate(candidate: PredicateCandidate) -> bool:
    """
    Vérifie si un PredicateCandidate est générique.

    Args:
        candidate: Candidat prédicat

    Returns:
        True si générique
    """
    return candidate.is_auxiliary or candidate.is_copula or candidate.is_modal


# ===================================
# VALIDATION STRUCTURE PRÉDICATIVE
# ===================================

def is_valid_predicate_structure(
    doc: Doc,
    predicate_token_idx: int,
    subject_span: Span,
    object_span: Span,
) -> Tuple[bool, str]:
    """
    Valide la structure prédicative complète.

    Vérifie que le prédicat forme une structure valide avec sujet et objet:
    - Le verbe n'est pas générique
    - Il y a une relation syntaxique avec les entités
    - La structure est complète (pas juste un verbe isolé)

    Args:
        doc: Document spaCy
        predicate_token_idx: Index du token prédicat
        subject_span: Span du sujet
        object_span: Span de l'objet

    Returns:
        Tuple (is_valid, reason)
    """
    token = doc[predicate_token_idx]

    # Check 1: Pas un verbe générique
    if is_generic_verb(token):
        return False, "GENERIC_VERB"

    # Check 2: Le verbe a des dépendants
    children_deps = [child.dep_ for child in token.children]
    if not children_deps:
        return False, "NO_DEPENDENTS"

    # Check 3: Structure minimale (au moins un argument)
    arg_deps = {"nsubj", "nsubjpass", "dobj", "obj", "iobj", "obl", "prep"}
    has_arg = any(dep in arg_deps for dep in children_deps)
    if not has_arg:
        return False, "NO_ARGUMENTS"

    # Check 4: Proximité (verbe entre les entités ou adjacent)
    verb_idx = token.i
    subj_range = range(subject_span.start, subject_span.end)
    obj_range = range(object_span.start, object_span.end)

    # Le verbe doit être entre les deux ou dans un rayon de 5 tokens
    min_entity = min(subject_span.start, object_span.start)
    max_entity = max(subject_span.end, object_span.end)
    proximity_range = range(max(0, min_entity - 5), min(len(doc), max_entity + 5))

    if verb_idx not in proximity_range:
        return False, "OUT_OF_PROXIMITY"

    return True, "VALID"


# ===================================
# HIGH-LEVEL EXTRACTION
# ===================================

def extract_predicate_for_pair(
    section_text: str,
    subject_label: str,
    subject_char_start: int,
    subject_char_end: int,
    object_label: str,
    object_char_start: int,
    object_char_end: int,
    lang: str = "fr",
) -> Optional[PredicateCandidate]:
    """
    Extrait le prédicat pour une paire d'entités.

    Fonction de haut niveau utilisée par le resolver.

    Args:
        section_text: Texte de la section
        subject_label: Label du sujet
        subject_char_start: Position début du sujet
        subject_char_end: Position fin du sujet
        object_label: Label de l'objet
        object_char_start: Position début de l'objet
        object_char_end: Position fin de l'objet
        lang: Code langue

    Returns:
        PredicateCandidate ou None
    """
    # Charger le modèle spaCy
    nlp = get_spacy_model(lang)

    # Parser le texte
    doc = nlp(section_text)

    # Localiser les entités
    subject_span = locate_entity_in_doc(
        doc, subject_char_start, subject_char_end, subject_label
    )
    if subject_span is None:
        logger.warning(
            f"[OSMOSE:Pass3.5] Could not locate subject '{subject_label}'"
        )
        return None

    object_span = locate_entity_in_doc(
        doc, object_char_start, object_char_end, object_label
    )
    if object_span is None:
        logger.warning(
            f"[OSMOSE:Pass3.5] Could not locate object '{object_label}'"
        )
        return None

    # Extraire le prédicat
    predicate = extract_predicate_from_context(doc, subject_span, object_span)

    if predicate:
        # Valider la structure
        is_valid, reason = is_valid_predicate_structure(
            doc, predicate.token_index, subject_span, object_span
        )
        if not is_valid:
            logger.debug(
                f"[OSMOSE:Pass3.5] Predicate '{predicate.text}' rejected: {reason}"
            )
            return None

    return predicate
