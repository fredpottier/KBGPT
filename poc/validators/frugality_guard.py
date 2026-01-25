"""
Coupe-circuit Frugalite - CRITIQUE

Garde-fou dur pour eviter la sur-structuration.
Si >60 concepts -> FAIL immediat, pas de post-filtrage.
"""

from typing import List, Tuple
from dataclasses import dataclass
from enum import Enum

from poc.models.schemas import ConceptSitue


class FrugalityStatus(str, Enum):
    """Statut de validation frugalite"""
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SUCCESS_HOSTILE = "SUCCESS_HOSTILE"


@dataclass
class FrugalityResult:
    """Resultat de validation frugalite"""
    status: FrugalityStatus
    message: str
    concept_count: int
    is_valid: bool


class FrugalityGuard:
    """
    Coupe-circuit dur pour la frugalite conceptuelle.

    Regles:
    - MAX_CONCEPTS = 60 : Dur, non negociable
    - MIN_CONCEPTS = 5 : Trop peu = doc hostile ou erreur
    - Doc hostile avec <10 concepts = SUCCES
    """

    MAX_CONCEPTS = 60  # Dur, non negociable
    MIN_CONCEPTS = 5   # Trop peu = doc hostile ou erreur
    HOSTILE_THRESHOLD = 10  # Seuil pour doc hostile

    def validate(
        self,
        concepts: List[ConceptSitue],
        doc_type: str = "NORMAL"
    ) -> FrugalityResult:
        """
        Valide le nombre de concepts extraits.

        Args:
            concepts: Liste des concepts extraits
            doc_type: Type de document ("CENTRAL", "TRANSVERSAL", "CONTEXTUAL", "HOSTILE")

        Returns:
            FrugalityResult avec statut et message
        """
        count = len(concepts)
        is_hostile = doc_type.upper() == "HOSTILE"

        # FAIL immediat si >60 concepts
        if count > self.MAX_CONCEPTS:
            return FrugalityResult(
                status=FrugalityStatus.FAIL,
                message=f"FAIL: {count} concepts > {self.MAX_CONCEPTS} (sur-structuration detectee)",
                concept_count=count,
                is_valid=False
            )

        # Document hostile avec peu de concepts = SUCCES
        if is_hostile and count < self.HOSTILE_THRESHOLD:
            return FrugalityResult(
                status=FrugalityStatus.SUCCESS_HOSTILE,
                message=f"SUCCESS: Document hostile correctement refuse ({count} concepts < {self.HOSTILE_THRESHOLD})",
                concept_count=count,
                is_valid=True
            )

        # Document hostile avec trop de concepts = echec du test
        if is_hostile and count >= self.HOSTILE_THRESHOLD:
            return FrugalityResult(
                status=FrugalityStatus.FAIL,
                message=f"FAIL: Document hostile sur-structure ({count} concepts >= {self.HOSTILE_THRESHOLD})",
                concept_count=count,
                is_valid=False
            )

        # Document normal avec trop peu de concepts = warning
        if count < self.MIN_CONCEPTS and not is_hostile:
            return FrugalityResult(
                status=FrugalityStatus.WARN,
                message=f"WARN: {count} concepts < {self.MIN_CONCEPTS} (sous-extraction possible)",
                concept_count=count,
                is_valid=True  # Warning, pas fail
            )

        # Cas nominal
        return FrugalityResult(
            status=FrugalityStatus.OK,
            message=f"OK: {count} concepts dans la plage acceptable [{self.MIN_CONCEPTS}-{self.MAX_CONCEPTS}]",
            concept_count=count,
            is_valid=True
        )

    def validate_or_raise(
        self,
        concepts: List[ConceptSitue],
        doc_type: str = "NORMAL"
    ) -> FrugalityResult:
        """
        Valide et leve une exception si FAIL.

        Raises:
            ValueError: Si le coupe-circuit est declenche
        """
        result = self.validate(concepts, doc_type)

        if not result.is_valid:
            raise ValueError(result.message)

        return result
