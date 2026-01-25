"""
Validateur d'Anchors

Verifie que les anchors des Information pointent vers du texte valide.
Seuil de succes: >=95% (acceptable: >=85%, fail: <80%)
"""

from typing import List, Dict, Tuple
from dataclasses import dataclass

from poc.models.schemas import Information, Anchor


@dataclass
class AnchorValidationResult:
    """Resultat de validation des anchors"""
    total_count: int
    valid_count: int
    invalid_count: int
    success_rate: float
    is_valid: bool
    invalid_anchors: List[str]  # Liste des anchor_id invalides


class AnchorValidator:
    """
    Validateur d'anchors pour les Information.

    Verifie que chaque anchor pointe vers un texte existant
    et que le span est valide.
    """

    # Seuils
    SUCCESS_THRESHOLD = 0.95  # Cible
    ACCEPTABLE_THRESHOLD = 0.85  # Acceptable
    FAIL_THRESHOLD = 0.80  # En dessous = FAIL

    MIN_TEXT_LENGTH = 10  # Minimum 10 caracteres pour etre valide

    def validate_single(
        self,
        anchor: Anchor,
        chunks: Dict[str, str]
    ) -> Tuple[bool, str]:
        """
        Valide un anchor unique.

        Args:
            anchor: L'anchor a valider
            chunks: Dictionnaire chunk_id -> texte

        Returns:
            (is_valid, extracted_text_or_error)
        """
        # Verifier que le chunk existe
        if anchor.chunk_id not in chunks:
            return False, f"Chunk {anchor.chunk_id} non trouve"

        chunk_text = chunks[anchor.chunk_id]

        # Verifier les bornes
        if anchor.start_char < 0 or anchor.end_char < 0:
            return False, "Bornes negatives"

        if anchor.start_char >= anchor.end_char:
            return False, "start_char >= end_char"

        if anchor.end_char > len(chunk_text):
            return False, f"end_char ({anchor.end_char}) > longueur chunk ({len(chunk_text)})"

        # Extraire le texte
        extracted = chunk_text[anchor.start_char:anchor.end_char]

        # Verifier la longueur minimale
        if len(extracted.strip()) < self.MIN_TEXT_LENGTH:
            return False, f"Texte trop court ({len(extracted.strip())} < {self.MIN_TEXT_LENGTH})"

        return True, extracted

    def validate_all(
        self,
        informations: List[Information],
        chunks: Dict[str, str]
    ) -> AnchorValidationResult:
        """
        Valide tous les anchors d'une liste d'Information.

        Args:
            informations: Liste des Information a valider
            chunks: Dictionnaire chunk_id -> texte

        Returns:
            AnchorValidationResult avec statistiques
        """
        if not informations:
            return AnchorValidationResult(
                total_count=0,
                valid_count=0,
                invalid_count=0,
                success_rate=1.0,
                is_valid=True,
                invalid_anchors=[]
            )

        valid_count = 0
        invalid_anchors = []

        for info in informations:
            is_valid, _ = self.validate_single(info.anchor, chunks)
            if is_valid:
                valid_count += 1
            else:
                invalid_anchors.append(info.id)

        total_count = len(informations)
        invalid_count = total_count - valid_count
        success_rate = valid_count / total_count

        return AnchorValidationResult(
            total_count=total_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            success_rate=success_rate,
            is_valid=success_rate >= self.FAIL_THRESHOLD,
            invalid_anchors=invalid_anchors
        )

    def get_text_from_anchor(
        self,
        anchor: Anchor,
        chunks: Dict[str, str]
    ) -> str:
        """
        Recupere le texte pointe par un anchor.

        Args:
            anchor: L'anchor
            chunks: Dictionnaire chunk_id -> texte

        Returns:
            Le texte extrait ou une chaine vide si invalide
        """
        is_valid, result = self.validate_single(anchor, chunks)
        return result if is_valid else ""

    def get_texts_for_informations(
        self,
        informations: List[Information],
        chunks: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Recupere les textes pour une liste d'Information.

        Returns:
            Dictionnaire info_id -> texte
        """
        return {
            info.id: self.get_text_from_anchor(info.anchor, chunks)
            for info in informations
        }
