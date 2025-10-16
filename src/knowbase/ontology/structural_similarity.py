"""
Similarité structurelle pour canonicalisation (P1.2).

Analyse structure des noms d'entités au-delà de la similarité textuelle:
- Extraction et matching de sigles/acronymes (S/4HANA vs S4H)
- Analyse composants (Cloud ERP vs ERP Cloud)
- Détection préfixes/suffixes (SAP SuccessFactors vs SuccessFactors)
- Normalisation variantes typographiques (S/4HANA vs S4HANA)

Complète fuzzy matching textuel pour éviter faux négatifs sur variations structurelles.
"""
from typing import Tuple, List, Optional, Set, Dict
import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class StructuralPattern:
    """
    Patterns structurels pour matching avancé.

    Chaque pattern définit des règles de transformation/équivalence:
    - Acronymes: SAP S/4HANA → S4H, S4, S/4
    - Composants: Cloud ERP ↔ ERP Cloud (ordre inversé)
    - Variantes typo: S/4HANA ↔ S4HANA (slash optionnel)
    """

    # Patterns communs SAP
    SAP_ACRONYMS = {
        r"S/?4\s?HANA": ["S4HANA", "S/4HANA", "S4H", "S/4"],
        r"Success\s?Factors": ["SuccessFactors", "SF", "SFSF"],
        r"Business\s?One": ["BusinessOne", "B1", "SBO"],
        r"Business\s?ByDesign": ["BusinessByDesign", "ByDesign", "ByD"],
        r"Ariba": ["Ariba", "SAP Ariba"],
        r"Concur": ["Concur", "SAP Concur"],
        r"Fieldglass": ["Fieldglass", "SAP Fieldglass"],
    }

    # Patterns cloud/software
    CLOUD_PATTERNS = {
        r"Cloud\s+(\w+)": r"\1 Cloud",  # Cloud ERP ↔ ERP Cloud
        r"(\w+)\s+as\s+a\s+Service": r"\1aaS",  # Software as a Service → SaaS
    }

    # Préfixes/suffixes optionnels
    OPTIONAL_PREFIXES = ["SAP", "Microsoft", "Oracle", "IBM", "Amazon", "Google"]
    OPTIONAL_SUFFIXES = ["Cloud", "Online", "Enterprise", "Suite", "Platform"]

    # Variantes typographiques
    TYPO_VARIANTS = {
        r"\/": "",  # S/4HANA → S4HANA
        r"\s+": "",  # Business One → BusinessOne
        r"-": " ",  # Business-One → Business One
        r"_": " ",  # Business_One → Business One
    }


def extract_acronyms(text: str) -> Set[str]:
    """
    Extrait acronymes possibles d'un texte.

    Args:
        text: Texte source

    Returns:
        Set d'acronymes détectés

    Examples:
        "SAP S/4HANA Cloud" → {"S4HANA", "S/4HANA", "S4H", "S/4", "SAP"}
        "Microsoft Dynamics 365" → {"MS", "D365", "Dynamics365"}
    """
    acronyms = set()

    # Acronymes majuscules (2+ lettres)
    upper_acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
    acronyms.update(upper_acronyms)

    # Patterns SAP spécifiques
    for pattern, variants in StructuralPattern.SAP_ACRONYMS.items():
        if re.search(pattern, text, re.IGNORECASE):
            acronyms.update(variants)

    # Initiales (SAP SuccessFactors → SAPSF, SF)
    words = re.findall(r"\b[A-Z][a-z]+\b", text)
    if len(words) >= 2:
        initials = "".join(word[0] for word in words)
        acronyms.add(initials)

        # Initiales sans premier mot (SAP SuccessFactors → SF)
        if len(words) > 2:
            initials_no_first = "".join(word[0] for word in words[1:])
            acronyms.add(initials_no_first)

    logger.debug(f"[StructuralSimilarity] Extracted acronyms from '{text}': {acronyms}")

    return acronyms


def extract_components(text: str) -> List[str]:
    """
    Extrait composants significatifs d'un nom.

    Args:
        text: Nom d'entité

    Returns:
        Liste de composants (mots significatifs)

    Examples:
        "SAP S/4HANA Cloud ERP" → ["SAP", "S/4HANA", "Cloud", "ERP"]
        "Microsoft Dynamics 365 Finance" → ["Microsoft", "Dynamics", "365", "Finance"]
    """
    # Supprimer ponctuation mais garder slashes (S/4HANA)
    text_clean = re.sub(r"[^\w\s/]", " ", text)

    # Split en mots
    components = re.findall(r"\b[\w/]+\b", text_clean)

    # Filtrer mots vides courts (de, la, du, etc.)
    stopwords = {"de", "la", "le", "du", "des", "a", "as", "of", "the", "and", "or"}
    components = [c for c in components if c.lower() not in stopwords and len(c) > 1]

    logger.debug(f"[StructuralSimilarity] Extracted components from '{text}': {components}")

    return components


def normalize_typography(text: str) -> str:
    """
    Normalise variantes typographiques.

    Args:
        text: Texte source

    Returns:
        Texte normalisé

    Examples:
        "S/4HANA" → "S4HANA"
        "Business-One" → "Business One"
    """
    normalized = text

    for pattern, replacement in StructuralPattern.TYPO_VARIANTS.items():
        normalized = re.sub(pattern, replacement, normalized)

    # Normaliser casse: Title Case
    normalized = " ".join(word.capitalize() for word in normalized.split())

    return normalized


def strip_optional_affixes(text: str) -> str:
    """
    Retire préfixes/suffixes optionnels.

    Args:
        text: Nom d'entité

    Returns:
        Nom sans affixes optionnels

    Examples:
        "SAP SuccessFactors" → "SuccessFactors"
        "Dynamics 365 Cloud" → "Dynamics 365"
    """
    stripped = text.strip()

    # Retirer préfixes
    for prefix in StructuralPattern.OPTIONAL_PREFIXES:
        if stripped.lower().startswith(prefix.lower()):
            stripped = stripped[len(prefix):].strip()
            logger.debug(f"[StructuralSimilarity] Stripped prefix '{prefix}': '{text}' → '{stripped}'")

    # Retirer suffixes
    for suffix in StructuralPattern.OPTIONAL_SUFFIXES:
        if stripped.lower().endswith(suffix.lower()):
            stripped = stripped[:-len(suffix)].strip()
            logger.debug(f"[StructuralSimilarity] Stripped suffix '{suffix}': '{text}' → '{stripped}'")

    return stripped


def compute_component_overlap(components1: List[str], components2: List[str]) -> float:
    """
    Calcule overlap entre deux listes de composants (Jaccard).

    Args:
        components1: Composants texte 1
        components2: Composants texte 2

    Returns:
        Score overlap (0-1)

    Examples:
        ["SAP", "S4HANA", "Cloud"] vs ["S4HANA", "Cloud", "ERP"] → 0.5 (2/4)
    """
    if not components1 or not components2:
        return 0.0

    # Normaliser casse pour comparaison
    set1 = set(c.lower() for c in components1)
    set2 = set(c.lower() for c in components2)

    # Jaccard similarity
    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    overlap = intersection / union

    logger.debug(
        f"[StructuralSimilarity] Component overlap: {set1} ∩ {set2} = {intersection}/{union} = {overlap:.2f}"
    )

    return overlap


def compute_acronym_match(acronyms1: Set[str], acronyms2: Set[str]) -> bool:
    """
    Détecte si acronymes matchent.

    Args:
        acronyms1: Acronymes texte 1
        acronyms2: Acronymes texte 2

    Returns:
        True si au moins un acronyme commun

    Examples:
        {"S4HANA", "S4H"} vs {"S4H", "SAP"} → True
    """
    if not acronyms1 or not acronyms2:
        return False

    # Normaliser casse
    set1 = set(a.lower() for a in acronyms1)
    set2 = set(a.lower() for a in acronyms2)

    has_match = bool(set1 & set2)

    if has_match:
        logger.debug(
            f"[StructuralSimilarity] Acronym match found: {set1} ∩ {set2} = {set1 & set2}"
        )

    return has_match


def compute_structural_similarity(text1: str, text2: str) -> Tuple[float, Dict[str, float]]:
    """
    Calcule similarité structurelle entre deux noms d'entités.

    Analyse plusieurs dimensions:
    1. Overlap composants (Jaccard)
    2. Match acronymes
    3. Similarité après normalisation typo
    4. Similarité sans affixes optionnels

    Args:
        text1: Premier nom
        text2: Deuxième nom

    Returns:
        Tuple (score_total, details) où:
        - score_total: score agrégé (0-1)
        - details: dict avec scores par dimension

    Examples:
        "SAP S/4HANA Cloud" vs "S4HANA Cloud ERP"
        → score=0.85, details={component_overlap=0.67, acronym_match=1.0, ...}
    """
    details = {}

    # 1. Extraction composants
    components1 = extract_components(text1)
    components2 = extract_components(text2)
    component_overlap = compute_component_overlap(components1, components2)
    details["component_overlap"] = component_overlap

    # 2. Extraction acronymes
    acronyms1 = extract_acronyms(text1)
    acronyms2 = extract_acronyms(text2)
    acronym_match = 1.0 if compute_acronym_match(acronyms1, acronyms2) else 0.0
    details["acronym_match"] = acronym_match

    # 3. Normalisation typo
    norm1 = normalize_typography(text1)
    norm2 = normalize_typography(text2)
    typo_similarity = SequenceMatcher(None, norm1.lower(), norm2.lower()).ratio()
    details["typo_similarity"] = typo_similarity

    # 4. Sans affixes optionnels
    stripped1 = strip_optional_affixes(text1)
    stripped2 = strip_optional_affixes(text2)
    affix_similarity = SequenceMatcher(None, stripped1.lower(), stripped2.lower()).ratio()
    details["affix_similarity"] = affix_similarity

    # Agrégation pondérée
    # Component overlap: 40%
    # Acronym match: 30%
    # Typo similarity: 20%
    # Affix similarity: 10%
    score_total = (
        0.40 * component_overlap +
        0.30 * acronym_match +
        0.20 * typo_similarity +
        0.10 * affix_similarity
    )

    logger.info(
        f"[StructuralSimilarity] '{text1}' vs '{text2}': "
        f"total={score_total:.2f} (component={component_overlap:.2f}, "
        f"acronym={acronym_match:.2f}, typo={typo_similarity:.2f}, "
        f"affix={affix_similarity:.2f})"
    )

    return score_total, details


def is_structural_match(
    text1: str,
    text2: str,
    threshold: float = 0.75
) -> Tuple[bool, float, Dict[str, float]]:
    """
    Détermine si deux noms sont structurellement similaires.

    Args:
        text1: Premier nom
        text2: Deuxième nom
        threshold: Seuil de matching (défaut: 0.75)

    Returns:
        Tuple (is_match, score, details)

    Examples:
        "SAP S/4HANA Cloud" vs "S4HANA Cloud" → (True, 0.85, {...})
        "Oracle ERP" vs "SAP S/4HANA" → (False, 0.20, {...})
    """
    score, details = compute_structural_similarity(text1, text2)
    is_match = score >= threshold

    logger.info(
        f"[StructuralSimilarity] Match result: '{text1}' vs '{text2}' → "
        f"{'✅ MATCH' if is_match else '❌ NO MATCH'} (score={score:.2f}, threshold={threshold:.2f})"
    )

    return is_match, score, details


# ============================================================================
# Intégration avec Fuzzy Matching
# ============================================================================

def enhanced_fuzzy_match(
    text1: str,
    text2: str,
    textual_threshold: float = 0.85,
    structural_threshold: float = 0.75
) -> Tuple[bool, float, str]:
    """
    Matching hybride: textuel + structurel.

    Algorithme:
    1. Calculer similarité textuelle classique (SequenceMatcher)
    2. Si >= textual_threshold → match
    3. Sinon, calculer similarité structurelle
    4. Si >= structural_threshold → match
    5. Sinon → no match

    Args:
        text1: Premier nom
        text2: Deuxième nom
        textual_threshold: Seuil textuel (défaut: 0.85)
        structural_threshold: Seuil structurel (défaut: 0.75)

    Returns:
        Tuple (is_match, score, method) où:
        - is_match: True si match trouvé
        - score: score final retenu
        - method: méthode ayant matché ("textual" | "structural" | "none")

    Examples:
        "S/4HANA" vs "S4HANA" → (True, 0.93, "textual")
        "SAP S/4HANA Cloud" vs "S4H Cloud" → (True, 0.80, "structural")
        "Oracle ERP" vs "SAP ERP" → (False, 0.50, "none")
    """
    # Étape 1: Similarité textuelle
    textual_score = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    if textual_score >= textual_threshold:
        logger.info(
            f"[EnhancedFuzzy] ✅ TEXTUAL MATCH: '{text1}' vs '{text2}' "
            f"(score={textual_score:.2f} >= {textual_threshold:.2f})"
        )
        return True, textual_score, "textual"

    # Étape 2: Similarité structurelle (fallback)
    logger.debug(
        f"[EnhancedFuzzy] Textual match failed (score={textual_score:.2f} < {textual_threshold:.2f}), "
        f"trying structural matching..."
    )

    structural_match, structural_score, details = is_structural_match(
        text1, text2, threshold=structural_threshold
    )

    if structural_match:
        logger.info(
            f"[EnhancedFuzzy] ✅ STRUCTURAL MATCH: '{text1}' vs '{text2}' "
            f"(score={structural_score:.2f} >= {structural_threshold:.2f})"
        )
        return True, structural_score, "structural"

    # Aucun match
    final_score = max(textual_score, structural_score)
    logger.info(
        f"[EnhancedFuzzy] ❌ NO MATCH: '{text1}' vs '{text2}' "
        f"(textual={textual_score:.2f}, structural={structural_score:.2f})"
    )

    return False, final_score, "none"


__all__ = [
    "StructuralPattern",
    "extract_acronyms",
    "extract_components",
    "normalize_typography",
    "strip_optional_affixes",
    "compute_component_overlap",
    "compute_acronym_match",
    "compute_structural_similarity",
    "is_structural_match",
    "enhanced_fuzzy_match"
]
