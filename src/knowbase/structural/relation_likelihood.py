"""
OSMOSE Structural Awareness - Relation Likelihood Features

Module agnostique pour évaluer la probabilité qu'un texte contienne
des relations sémantiques explicites.

Principe:
- Signaux purement structurels (pas de lexique métier)
- Distingue "texte relationnel" vs "énumération/catalogue"
- Score monotone avec tiers (HIGH/MEDIUM/LOW/VERY_LOW)

Utilisé par:
- Pass 3 pour filtrer les sections "catalogue-like"
- Candidate generation pour réduire le bruit

Date: 2026-01-09
Spec: ChatGPT Clean-Room Agnostique
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ========================================================================
# CONSTANTES
# ========================================================================

# Patterns pour détecter les lignes "liste" (agnostique)
LIST_MARKER_PATTERNS = [
    r"^\s*[-•*–—›▸○●]\s+",        # Bullets: -, •, *, –, etc.
    r"^\s*\d+[\.\)]\s+",           # Numérotation: 1. ou 1)
    r"^\s*[a-zA-Z][\.\)]\s+",      # Lettres: a. ou a)
    r"^\s*[ivxIVX]+[\.\)]\s+",     # Romains: i. ii. iii.
]

# Ponctuation relationnelle (souvent utilisée pour exprimer des liens)
RELATION_PUNCTUATION = [":", "→", "=>", "=", "(", ")"]

# Seuils pour les tiers
TIER_HIGH = 0.55
TIER_MEDIUM = 0.35
TIER_LOW = 0.20


# ========================================================================
# DATACLASS
# ========================================================================

@dataclass
class RelationLikelihoodFeatures:
    """
    Features structurelles pour évaluer la probabilité de relations.

    Tous les signaux sont agnostiques au domaine.
    """
    # Features brutes
    bullet_ratio: float           # % de lignes qui sont des items de liste
    avg_line_len: float           # Longueur moyenne des lignes
    verb_density: float           # Densité de tokens "verb-like"
    sentence_count: int           # Nombre approximatif de phrases
    punct_relation_density: float # Densité de ponctuation relationnelle
    enumeration_ratio: float      # % de lignes nominales courtes
    template_likelihood: float    # Score template (si disponible)

    # Score calculé
    relation_likelihood: float    # Score final 0-1
    tier: str                     # HIGH | MEDIUM | LOW | VERY_LOW


# ========================================================================
# FONCTIONS UTILITAIRES
# ========================================================================

def split_non_empty_lines(text: str) -> List[str]:
    """Retourne les lignes non vides, stripped."""
    return [l.strip() for l in text.splitlines() if l.strip()]


def is_bullet_line(line: str) -> bool:
    """Détecte si une ligne est un item de liste."""
    return any(re.match(p, line) for p in LIST_MARKER_PATTERNS)


def approx_sentence_count(text: str) -> int:
    """
    Compte approximatif des phrases (agnostique).

    Split sur ponctuation de fin de phrase.
    """
    parts = re.split(r"[.!?;]+", text)
    return sum(1 for p in parts if p.strip())


def punct_relation_density(text: str) -> float:
    """
    Densité de ponctuation relationnelle.

    Ces caractères sont souvent utilisés pour exprimer des liens/définitions.
    """
    if not text:
        return 0.0
    count = sum(text.count(p) for p in RELATION_PUNCTUATION)
    return count / len(text)


def enumeration_ratio(lines: List[str]) -> float:
    """
    Ratio de lignes "nominales" (courtes, sans ponctuation de fin).

    Proxy pour détecter les énumérations/catalogues.
    """
    if not lines:
        return 0.0

    short_nominal = 0
    for l in lines:
        # Ligne courte (<40 chars) sans ponctuation de fin
        if len(l) < 40 and not re.search(r"[.!?;:]$", l):
            short_nominal += 1

    return short_nominal / len(lines)


def approx_verb_density(text: str) -> float:
    """
    Densité approximative de verbes (agnostique, multi-langue).

    Heuristique basée sur les terminaisons verbales fréquentes.
    Pas parfait, mais suffisant pour séparer "narratif" vs "catalogue".
    """
    tokens = re.findall(r"\b[\w']+\b", text.lower())
    if not tokens:
        return 0.0

    verb_like = 0
    for t in tokens:
        # Contractions (it's, don't, etc.)
        if "'" in t:
            verb_like += 1
            continue

        # Terminaisons verbales approximatives (multi-lang)
        # EN-ish
        if re.search(r"(ed|ing|en|ify|ise|ize)$", t):
            verb_like += 1
        # FR-ish
        elif re.search(r"(er|ir|re|é|ée|és|ées|ant|ent|ons|ez)$", t):
            verb_like += 1
        # ES-ish
        elif re.search(r"(ar|er|ir|ando|iendo|ado|ido)$", t):
            verb_like += 1
        # IT-ish
        elif re.search(r"(are|ere|ire|ando|endo|ato|ito)$", t):
            verb_like += 1
        # DE-ish
        elif re.search(r"(en|te|st|t)$", t) and len(t) > 4:
            verb_like += 1

    return verb_like / len(tokens)


# ========================================================================
# CALCUL DU SCORE
# ========================================================================

def clamp01(x: float) -> float:
    """Clamp entre 0 et 1."""
    return max(0.0, min(1.0, x))


def compute_relation_likelihood_score(
    bullet_ratio: float,
    avg_line_len: float,
    verb_density: float,
    sentence_count: int,
    punct_relation_density: float,
    enumeration_ratio: float,
    template_likelihood: float = 0.0
) -> float:
    """
    Calcule le score de probabilité de relations.

    Formule pondérée (agnostique):
    - Signaux positifs: verb_density, punct_density, sentence_count
    - Signaux négatifs: bullet_ratio, enumeration_ratio, template_likelihood
    """
    score = 0.0

    # Signaux positifs (texte relationnel)
    score += 0.35 * clamp01(verb_density / 0.06)           # 6% verb-like ~ narratif
    score += 0.25 * clamp01(punct_relation_density / 0.015)
    score += 0.20 * clamp01(sentence_count / 4.0)

    # Signaux négatifs (catalogue/énumération)
    score -= 0.35 * bullet_ratio
    score -= 0.20 * enumeration_ratio
    score -= 0.25 * template_likelihood

    return clamp01(score)


def get_tier(score: float) -> str:
    """Convertit le score en tier."""
    if score >= TIER_HIGH:
        return "HIGH"
    if score >= TIER_MEDIUM:
        return "MEDIUM"
    if score >= TIER_LOW:
        return "LOW"
    return "VERY_LOW"


# ========================================================================
# FONCTION PRINCIPALE
# ========================================================================

def compute_features(
    text: str,
    template_likelihood: float = 0.0
) -> RelationLikelihoodFeatures:
    """
    Calcule toutes les features de relation likelihood pour un texte.

    Args:
        text: Texte brut (chunk, section, etc.)
        template_likelihood: Score de template si disponible (0-1)

    Returns:
        RelationLikelihoodFeatures avec score et tier
    """
    if not text or not text.strip():
        return RelationLikelihoodFeatures(
            bullet_ratio=0.0,
            avg_line_len=0.0,
            verb_density=0.0,
            sentence_count=0,
            punct_relation_density=0.0,
            enumeration_ratio=0.0,
            template_likelihood=template_likelihood,
            relation_likelihood=0.0,
            tier="VERY_LOW"
        )

    lines = split_non_empty_lines(text)

    # Calcul des features brutes
    bullet_lines = sum(1 for l in lines if is_bullet_line(l))
    bullet_ratio_val = bullet_lines / max(1, len(lines))

    avg_line_len_val = sum(len(l) for l in lines) / max(1, len(lines))

    sentence_count_val = approx_sentence_count(text)
    verb_density_val = approx_verb_density(text)
    punct_density_val = punct_relation_density(text)
    enum_ratio_val = enumeration_ratio(lines)

    # Score et tier
    score = compute_relation_likelihood_score(
        bullet_ratio=bullet_ratio_val,
        avg_line_len=avg_line_len_val,
        verb_density=verb_density_val,
        sentence_count=sentence_count_val,
        punct_relation_density=punct_density_val,
        enumeration_ratio=enum_ratio_val,
        template_likelihood=template_likelihood
    )

    tier_val = get_tier(score)

    return RelationLikelihoodFeatures(
        bullet_ratio=bullet_ratio_val,
        avg_line_len=avg_line_len_val,
        verb_density=verb_density_val,
        sentence_count=sentence_count_val,
        punct_relation_density=punct_density_val,
        enumeration_ratio=enum_ratio_val,
        template_likelihood=template_likelihood,
        relation_likelihood=score,
        tier=tier_val
    )


def is_section_allowed(features: RelationLikelihoodFeatures) -> bool:
    """
    Vérifie si une section est autorisée pour la génération de candidats.

    Seules les sections HIGH et MEDIUM génèrent des candidats.
    """
    return features.tier in ("HIGH", "MEDIUM")


# ========================================================================
# LOGGING / DEBUG
# ========================================================================

def log_features(features: RelationLikelihoodFeatures, context_id: str = ""):
    """Log les features pour debug."""
    logger.debug(
        f"[OSMOSE:RelationLikelihood] {context_id}: "
        f"tier={features.tier}, score={features.relation_likelihood:.2f}, "
        f"bullet={features.bullet_ratio:.2f}, verb={features.verb_density:.2f}, "
        f"enum={features.enumeration_ratio:.2f}"
    )
