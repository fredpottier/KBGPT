"""
OSMOSE Pipeline V2 - Volet A: Validateur Verbatim
==================================================
Ref: doc/ongoing/PLAN_QWEN_STRUCTURED_OUTPUTS_2026-01-27.md

Valide que les assertions extraites sont bien des copies verbatim du texte source.
Si une assertion est reformulée par le LLM (Qwen), elle est marquée ABSTAIN.

Règles de validation:
1. Le texte de l'assertion DOIT être un substring exact du texte source
2. Les spans (start_char, end_char) DOIVENT être alignés avec le texte
3. Tolérance whitespace (normalisation espaces/retours ligne)
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class VerbatimStatus(str, Enum):
    """Statut de validation verbatim."""
    VALID = "valid"                    # Texte exact trouvé
    VALID_NORMALIZED = "valid_normalized"  # Texte trouvé après normalisation whitespace
    ABSTAIN_NOT_SUBSTRING = "abstain_not_substring"  # Texte reformulé, pas dans source
    ABSTAIN_SPAN_MISALIGNED = "abstain_span_misaligned"  # Spans incorrects
    ABSTAIN_TOO_SHORT = "abstain_too_short"  # Texte trop court (<10 chars)
    ABSTAIN_TOO_LONG = "abstain_too_long"   # Texte trop long (>1000 chars)


@dataclass
class VerbatimValidationResult:
    """Résultat de la validation verbatim."""
    status: VerbatimStatus
    is_valid: bool
    corrected_start: Optional[int] = None  # Position corrigée si trouvée
    corrected_end: Optional[int] = None
    match_type: str = ""  # "exact", "normalized", "fuzzy", "none"
    similarity: float = 1.0  # 1.0 = exact, <1.0 = partial


def normalize_whitespace(text: str) -> str:
    """Normalise les espaces et retours ligne."""
    # Remplacer tous les whitespaces consécutifs par un seul espace
    return " ".join(text.split())


def find_substring_position(needle: str, haystack: str) -> Optional[Tuple[int, int]]:
    """
    Trouve la position exacte d'un substring dans le texte source.

    Returns:
        (start, end) ou None si non trouvé
    """
    pos = haystack.find(needle)
    if pos >= 0:
        return (pos, pos + len(needle))
    return None


def find_normalized_position(needle: str, haystack: str) -> Optional[Tuple[int, int]]:
    """
    Trouve la position après normalisation whitespace.

    Complexe car on doit mapper les positions normalisées vers les originales.
    """
    norm_needle = normalize_whitespace(needle)
    norm_haystack = normalize_whitespace(haystack)

    pos = norm_haystack.find(norm_needle)
    if pos < 0:
        return None

    # Mapper la position normalisée vers l'originale
    # On parcourt haystack en comptant les caractères non-whitespace
    char_count = 0
    start_pos = None
    end_pos = None

    in_whitespace = False
    normalized_idx = 0

    for i, char in enumerate(haystack):
        if char.isspace():
            if not in_whitespace:
                in_whitespace = True
                if normalized_idx > 0:
                    normalized_idx += 1  # Compte l'espace normalisé
        else:
            in_whitespace = False
            if start_pos is None and normalized_idx >= pos:
                start_pos = i
            normalized_idx += 1
            if start_pos is not None and normalized_idx >= pos + len(norm_needle):
                end_pos = i + 1
                break

    if start_pos is not None and end_pos is not None:
        return (start_pos, end_pos)

    return None


def validate_assertion_verbatim(
    assertion_text: str,
    source_text: str,
    claimed_start: int = -1,
    claimed_end: int = -1,
    min_length: int = 10,
    max_length: int = 1000
) -> VerbatimValidationResult:
    """
    Valide qu'une assertion est bien une copie verbatim du texte source.

    Args:
        assertion_text: Texte de l'assertion extraite par le LLM
        source_text: Texte source (chunk) dont l'assertion a été extraite
        claimed_start: Position start_char revendiquée par le LLM
        claimed_end: Position end_char revendiquée par le LLM
        min_length: Longueur minimale (défaut: 10)
        max_length: Longueur maximale (défaut: 1000)

    Returns:
        VerbatimValidationResult avec statut et positions corrigées si possible
    """
    # Vérification longueur
    text_len = len(assertion_text.strip())

    if text_len < min_length:
        return VerbatimValidationResult(
            status=VerbatimStatus.ABSTAIN_TOO_SHORT,
            is_valid=False,
            match_type="none"
        )

    if text_len > max_length:
        return VerbatimValidationResult(
            status=VerbatimStatus.ABSTAIN_TOO_LONG,
            is_valid=False,
            match_type="none"
        )

    # 1. Recherche exacte
    exact_pos = find_substring_position(assertion_text, source_text)
    if exact_pos:
        # Vérifier si les spans revendiqués sont corrects
        if claimed_start >= 0 and claimed_end > claimed_start:
            if claimed_start == exact_pos[0] and claimed_end == exact_pos[1]:
                return VerbatimValidationResult(
                    status=VerbatimStatus.VALID,
                    is_valid=True,
                    corrected_start=exact_pos[0],
                    corrected_end=exact_pos[1],
                    match_type="exact"
                )
            else:
                # Spans incorrects mais texte trouvé - on corrige
                return VerbatimValidationResult(
                    status=VerbatimStatus.VALID,
                    is_valid=True,
                    corrected_start=exact_pos[0],
                    corrected_end=exact_pos[1],
                    match_type="exact_corrected"
                )
        else:
            return VerbatimValidationResult(
                status=VerbatimStatus.VALID,
                is_valid=True,
                corrected_start=exact_pos[0],
                corrected_end=exact_pos[1],
                match_type="exact"
            )

    # 2. Recherche avec normalisation whitespace
    normalized_pos = find_normalized_position(assertion_text, source_text)
    if normalized_pos:
        return VerbatimValidationResult(
            status=VerbatimStatus.VALID_NORMALIZED,
            is_valid=True,
            corrected_start=normalized_pos[0],
            corrected_end=normalized_pos[1],
            match_type="normalized"
        )

    # 3. Vérifier si les spans revendiqués pointent vers du texte valide
    if claimed_start >= 0 and claimed_end > claimed_start and claimed_end <= len(source_text):
        claimed_text = source_text[claimed_start:claimed_end]

        # Comparer le texte aux spans avec le texte de l'assertion
        norm_claimed = normalize_whitespace(claimed_text)
        norm_assertion = normalize_whitespace(assertion_text)

        if norm_claimed == norm_assertion:
            return VerbatimValidationResult(
                status=VerbatimStatus.VALID_NORMALIZED,
                is_valid=True,
                corrected_start=claimed_start,
                corrected_end=claimed_end,
                match_type="span_match"
            )

        # Span existe mais texte différent = reformulation détectée
        return VerbatimValidationResult(
            status=VerbatimStatus.ABSTAIN_SPAN_MISALIGNED,
            is_valid=False,
            match_type="reformulated"
        )

    # 4. Texte non trouvé = reformulation
    return VerbatimValidationResult(
        status=VerbatimStatus.ABSTAIN_NOT_SUBSTRING,
        is_valid=False,
        match_type="none"
    )


@dataclass
class BatchValidationStats:
    """Statistiques de validation batch."""
    total: int = 0
    valid_exact: int = 0
    valid_normalized: int = 0
    abstain_not_substring: int = 0
    abstain_span_misaligned: int = 0
    abstain_too_short: int = 0
    abstain_too_long: int = 0

    @property
    def valid_count(self) -> int:
        return self.valid_exact + self.valid_normalized

    @property
    def abstain_count(self) -> int:
        return (self.abstain_not_substring + self.abstain_span_misaligned +
                self.abstain_too_short + self.abstain_too_long)

    @property
    def verbatim_rate(self) -> float:
        """Taux de verbatim (% assertions valides)."""
        if self.total == 0:
            return 0.0
        return self.valid_count / self.total

    @property
    def reformulation_rate(self) -> float:
        """Taux de reformulation (% assertions reformulées par le LLM)."""
        if self.total == 0:
            return 0.0
        return self.abstain_not_substring / self.total


def validate_assertions_batch(
    assertions: List[Dict],
    source_texts: Dict[str, str],
    chunk_id_field: str = "chunk_id",
    text_field: str = "text",
    start_field: str = "start_char",
    end_field: str = "end_char"
) -> Tuple[List[Dict], List[Dict], BatchValidationStats]:
    """
    Valide un batch d'assertions et sépare valid/abstain.

    Args:
        assertions: Liste d'assertions (dicts avec text, start_char, end_char)
        source_texts: Dict chunk_id -> texte source
        chunk_id_field: Nom du champ pour chunk_id
        text_field: Nom du champ pour le texte de l'assertion
        start_field: Nom du champ pour start_char
        end_field: Nom du champ pour end_char

    Returns:
        (valid_assertions, abstained_assertions, stats)
    """
    valid = []
    abstained = []
    stats = BatchValidationStats()

    for assertion in assertions:
        stats.total += 1

        chunk_id = assertion.get(chunk_id_field, "")
        source_text = source_texts.get(chunk_id, "")

        if not source_text:
            # Pas de texte source - abstain
            assertion["verbatim_status"] = VerbatimStatus.ABSTAIN_NOT_SUBSTRING.value
            assertion["verbatim_reason"] = "no_source_text"
            abstained.append(assertion)
            stats.abstain_not_substring += 1
            continue

        result = validate_assertion_verbatim(
            assertion_text=assertion.get(text_field, ""),
            source_text=source_text,
            claimed_start=assertion.get(start_field, -1),
            claimed_end=assertion.get(end_field, -1)
        )

        assertion["verbatim_status"] = result.status.value
        assertion["verbatim_match_type"] = result.match_type

        if result.is_valid:
            # Corriger les spans si nécessaire
            if result.corrected_start is not None:
                assertion[start_field] = result.corrected_start
            if result.corrected_end is not None:
                assertion[end_field] = result.corrected_end

            valid.append(assertion)

            if result.status == VerbatimStatus.VALID:
                stats.valid_exact += 1
            else:
                stats.valid_normalized += 1
        else:
            assertion["verbatim_reason"] = result.status.value
            abstained.append(assertion)

            if result.status == VerbatimStatus.ABSTAIN_NOT_SUBSTRING:
                stats.abstain_not_substring += 1
            elif result.status == VerbatimStatus.ABSTAIN_SPAN_MISALIGNED:
                stats.abstain_span_misaligned += 1
            elif result.status == VerbatimStatus.ABSTAIN_TOO_SHORT:
                stats.abstain_too_short += 1
            elif result.status == VerbatimStatus.ABSTAIN_TOO_LONG:
                stats.abstain_too_long += 1

    # Log statistiques
    logger.info(
        f"[OSMOSE:VerbatimValidator] Validation: {stats.total} assertions → "
        f"{stats.valid_count} valid ({stats.verbatim_rate:.1%}), "
        f"{stats.abstain_count} abstain "
        f"(reformulated: {stats.abstain_not_substring}, "
        f"misaligned: {stats.abstain_span_misaligned})"
    )

    if stats.reformulation_rate > 0.10:
        logger.warning(
            f"[OSMOSE:VerbatimValidator] ALERTE: Taux de reformulation élevé "
            f"({stats.reformulation_rate:.1%} > 10%). Le LLM ne respecte pas l'instruction verbatim."
        )

    return valid, abstained, stats


# ============================================================================
# INTEGRATION AVEC ASSERTION EXTRACTOR
# ============================================================================

def validate_raw_assertions(
    assertions: List["RawAssertion"],
    chunks: Dict[str, str]
) -> Tuple[List["RawAssertion"], List[Tuple["RawAssertion", str]], BatchValidationStats]:
    """
    Valide les RawAssertions et retourne (valid, abstained, stats).

    Compatible avec le format existant de AssertionExtractorV2.

    Args:
        assertions: Liste de RawAssertion
        chunks: Dict chunk_id -> texte source

    Returns:
        (valid_assertions, abstained_with_reason, stats)
    """
    valid = []
    abstained = []
    stats = BatchValidationStats()

    for assertion in assertions:
        stats.total += 1

        source_text = chunks.get(assertion.chunk_id, "")

        if not source_text:
            abstained.append((assertion, "no_source_text"))
            stats.abstain_not_substring += 1
            continue

        result = validate_assertion_verbatim(
            assertion_text=assertion.text,
            source_text=source_text,
            claimed_start=assertion.start_char,
            claimed_end=assertion.end_char
        )

        if result.is_valid:
            # Corriger les spans
            if result.corrected_start is not None:
                assertion.start_char = result.corrected_start
            if result.corrected_end is not None:
                assertion.end_char = result.corrected_end

            valid.append(assertion)

            if result.status == VerbatimStatus.VALID:
                stats.valid_exact += 1
            else:
                stats.valid_normalized += 1
        else:
            abstained.append((assertion, result.status.value))

            if result.status == VerbatimStatus.ABSTAIN_NOT_SUBSTRING:
                stats.abstain_not_substring += 1
            elif result.status == VerbatimStatus.ABSTAIN_SPAN_MISALIGNED:
                stats.abstain_span_misaligned += 1
            elif result.status == VerbatimStatus.ABSTAIN_TOO_SHORT:
                stats.abstain_too_short += 1
            elif result.status == VerbatimStatus.ABSTAIN_TOO_LONG:
                stats.abstain_too_long += 1

    logger.info(
        f"[OSMOSE:VerbatimValidator] {stats.total} assertions → "
        f"{stats.valid_count} valid ({stats.verbatim_rate:.1%}), "
        f"{stats.abstain_count} abstain"
    )

    return valid, abstained, stats
