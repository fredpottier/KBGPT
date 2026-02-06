# src/knowbase/claimfirst/applicability/evidence_unit_segmenter.py
"""
Layer A: EvidenceUnitSegmenter — Découpe les Passages en EvidenceUnits.

Réutilise la logique de split phrase de AssertionUnitIndexer
(méthodes _split_sentences et _is_sentence_end).

Principes:
- ID format: EU:{passage_reading_order}:{sentence_index} — déterministe, stable
- Pas de min_length trop restrictif (lignes courtes type "Version 2023" conservées)
- Phrases > 500 chars splitées sur ';' ou ','
- Propage page_no et section_title du Passage parent
"""

from __future__ import annotations

import logging
from typing import List

from knowbase.claimfirst.applicability.models import EvidenceUnit
from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger(__name__)

# Longueur max avant re-split sur ';' ou ','
MAX_SENTENCE_LENGTH = 500

# Longueur minimale pour conserver une phrase (très bas pour capturer "Version 2023")
MIN_SENTENCE_LENGTH = 5


class EvidenceUnitSegmenter:
    """
    Découpe une liste de Passages en EvidenceUnits (phrase-level).

    Chaque EvidenceUnit a un ID stable EU:{p_idx}:{s_idx} permettant
    au LLM de référencer des unités spécifiques sans voir le texte brut.
    """

    def segment(self, passages: List[Passage]) -> List[EvidenceUnit]:
        """
        Segmente tous les passages en EvidenceUnits.

        Args:
            passages: Liste de Passages ordonnés par reading_order

        Returns:
            Liste d'EvidenceUnits avec IDs stables
        """
        units: List[EvidenceUnit] = []

        for p_idx, passage in enumerate(passages):
            if not passage.text or not passage.text.strip():
                continue

            sentences = self._split_sentences(passage.text)
            s_idx = 0

            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < MIN_SENTENCE_LENGTH:
                    continue

                # Re-split si trop long
                if len(sentence) > MAX_SENTENCE_LENGTH:
                    sub_parts = self._split_long_sentence(sentence)
                    for sub in sub_parts:
                        sub = sub.strip()
                        if len(sub) < MIN_SENTENCE_LENGTH:
                            continue
                        unit = EvidenceUnit(
                            unit_id=f"EU:{p_idx}:{s_idx}",
                            text=sub,
                            passage_idx=p_idx,
                            sentence_idx=s_idx,
                            page_no=passage.page_no,
                            section_title=passage.section_title,
                        )
                        units.append(unit)
                        s_idx += 1
                else:
                    unit = EvidenceUnit(
                        unit_id=f"EU:{p_idx}:{s_idx}",
                        text=sentence,
                        passage_idx=p_idx,
                        sentence_idx=s_idx,
                        page_no=passage.page_no,
                        section_title=passage.section_title,
                    )
                    units.append(unit)
                    s_idx += 1

        logger.debug(
            f"[OSMOSE:EvidenceUnitSegmenter] {len(passages)} passages → "
            f"{len(units)} evidence units"
        )

        return units

    # =========================================================================
    # Sentence Splitting (adapté de AssertionUnitIndexer)
    # =========================================================================

    def _split_sentences(self, text: str) -> List[str]:
        """
        Découpe le texte en phrases en protégeant les abréviations.

        Réutilise la logique de AssertionUnitIndexer._split_sentences
        et _is_sentence_end.
        """
        sentences: List[str] = []
        current_start = 0
        i = 0

        while i < len(text):
            if text[i] in '.!?':
                if self._is_sentence_end(text, i):
                    sentence = text[current_start:i + 1].strip()
                    if sentence:
                        sentences.append(sentence)
                    current_start = i + 1
                    # Skip whitespace
                    while current_start < len(text) and text[current_start] in ' \t\n\r':
                        current_start += 1
            i += 1

        # Dernier segment
        if current_start < len(text):
            remaining = text[current_start:].strip()
            if remaining:
                sentences.append(remaining)

        return sentences

    def _is_sentence_end(self, text: str, dot_pos: int) -> bool:
        """
        Détermine si un point/!/?  est une fin de phrase.

        Mêmes patterns que AssertionUnitIndexer._is_sentence_end:
        1. ! et ? → toujours fin de phrase
        2. Mot court (≤3 lettres) avant → probablement abréviation
        3. Point interne (x.x) → pas fin de phrase
        4. Version (digit.digit) → pas fin de phrase
        5. Suivi d'une majuscule après espace → fin de phrase
        6. Fin de texte → fin de phrase
        """
        char = text[dot_pos]

        # ! et ? sont toujours des fins de phrase
        if char in '!?':
            return True

        # Mot court avant le point (1-3 lettres) → probablement abréviation
        word_before = ""
        j = dot_pos - 1
        while j >= 0 and text[j].isalpha():
            word_before = text[j] + word_before
            j -= 1

        if 1 <= len(word_before) <= 3:
            if dot_pos + 2 < len(text):
                next_char = text[dot_pos + 1:dot_pos + 3].lstrip()
                if next_char and next_char[0].isupper():
                    if word_before.isupper():
                        return False  # Acronyme
                    return True
            return False  # Probablement abréviation

        # Point interne dans un token (i.e., e.g.)
        if dot_pos > 0 and dot_pos + 1 < len(text):
            if text[dot_pos - 1].isalpha() and text[dot_pos + 1].isalpha():
                return False

        # Version (1.2, 2.0.1)
        if dot_pos > 0 and dot_pos + 1 < len(text):
            if text[dot_pos - 1].isdigit() and text[dot_pos + 1].isdigit():
                return False

        # Suivi d'une majuscule après espace → fin de phrase
        if dot_pos + 2 < len(text):
            rest = text[dot_pos + 1:].lstrip()
            if rest and rest[0].isupper():
                return True

        # Fin de texte
        if dot_pos == len(text) - 1:
            return True

        # Suivi uniquement de whitespace puis fin
        rest = text[dot_pos + 1:].strip()
        if not rest:
            return True

        # Par défaut, considérer comme fin de phrase si suivi d'espace
        if dot_pos + 1 < len(text) and text[dot_pos + 1] in ' \t\n\r':
            return True

        return False

    def _split_long_sentence(self, text: str) -> List[str]:
        """
        Re-découpe une phrase trop longue sur ';' puis ',' si nécessaire.
        """
        # Essayer ';' d'abord
        if ';' in text:
            parts = [p.strip() for p in text.split(';') if p.strip()]
            if all(len(p) <= MAX_SENTENCE_LENGTH for p in parts):
                return parts

        # Sinon essayer ','
        if ',' in text:
            result = []
            current = ""
            for part in text.split(','):
                candidate = (current + ',' + part) if current else part
                if len(candidate) > MAX_SENTENCE_LENGTH and current:
                    result.append(current.strip())
                    current = part
                else:
                    current = candidate
            if current.strip():
                result.append(current.strip())
            if result:
                return result

        # Pas de découpage possible
        return [text]


__all__ = [
    "EvidenceUnitSegmenter",
]
