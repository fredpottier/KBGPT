"""
Validateur de Taux de Refus

Vérifie qu'un document procédural génère suffisamment de refus.
Un document qui accepte tout est suspect.
"""

from typing import List
from dataclasses import dataclass
from enum import Enum


class DocumentComplexity(str, Enum):
    """Complexité conceptuelle attendue du document"""
    CONCEPT_RICH = "CONCEPT_RICH"      # Guide, norme, spec technique
    PROCEDURAL = "PROCEDURAL"          # Protocole, procédure, checklist
    MIXED = "MIXED"                    # Document mixte


@dataclass
class RefusalRateResult:
    """Résultat de validation du taux de refus"""
    is_valid: bool
    refusal_rate: float
    expected_min_rate: float
    message: str


class RefusalRateValidator:
    """
    Valide que le taux de refus est cohérent avec le type de document.

    Règles:
    - Document procédural: refusal_rate >= 30% (beaucoup de termes génériques)
    - Document conceptuel: refusal_rate >= 10% (quelques termes génériques)
    - Document mixte: refusal_rate >= 20%

    Un refusal_rate de 0% est TOUJOURS suspect.
    """

    # Seuils de refus attendus par type
    REFUSAL_THRESHOLDS = {
        DocumentComplexity.CONCEPT_RICH: 0.10,  # 10% minimum
        DocumentComplexity.PROCEDURAL: 0.30,    # 30% minimum
        DocumentComplexity.MIXED: 0.20,         # 20% minimum
    }

    # Seuil absolu minimum (0% = toujours suspect)
    ABSOLUTE_MIN_REFUSAL = 0.05  # Au moins 5% de refus

    def validate(
        self,
        concept_count: int,
        refusal_count: int,
        doc_complexity: DocumentComplexity = DocumentComplexity.MIXED
    ) -> RefusalRateResult:
        """
        Valide le taux de refus.

        Args:
            concept_count: Nombre de concepts acceptés
            refusal_count: Nombre de termes refusés
            doc_complexity: Complexité conceptuelle du document

        Returns:
            RefusalRateResult
        """
        total_terms = concept_count + refusal_count

        if total_terms == 0:
            return RefusalRateResult(
                is_valid=False,
                refusal_rate=0.0,
                expected_min_rate=self.ABSOLUTE_MIN_REFUSAL,
                message="Aucun terme analysé"
            )

        refusal_rate = refusal_count / total_terms
        expected_min = self.REFUSAL_THRESHOLDS.get(
            doc_complexity,
            self.REFUSAL_THRESHOLDS[DocumentComplexity.MIXED]
        )

        # Cas 1: Refusal rate de 0% = toujours suspect
        if refusal_rate == 0:
            return RefusalRateResult(
                is_valid=False,
                refusal_rate=0.0,
                expected_min_rate=expected_min,
                message="ALERTE: Aucun refus (0%). Le modèle accepte tout = sur-structuration probable"
            )

        # Cas 2: Refusal rate sous le seuil absolu
        if refusal_rate < self.ABSOLUTE_MIN_REFUSAL:
            return RefusalRateResult(
                is_valid=False,
                refusal_rate=refusal_rate,
                expected_min_rate=expected_min,
                message=f"Taux de refus très faible ({refusal_rate:.1%} < {self.ABSOLUTE_MIN_REFUSAL:.1%})"
            )

        # Cas 3: Refusal rate sous le seuil attendu pour le type
        if refusal_rate < expected_min:
            return RefusalRateResult(
                is_valid=False,
                refusal_rate=refusal_rate,
                expected_min_rate=expected_min,
                message=f"Taux de refus insuffisant pour {doc_complexity.value}: {refusal_rate:.1%} < {expected_min:.1%}"
            )

        # Cas nominal
        return RefusalRateResult(
            is_valid=True,
            refusal_rate=refusal_rate,
            expected_min_rate=expected_min,
            message=f"OK: {refusal_rate:.1%} refus (>= {expected_min:.1%} attendu)"
        )

    def detect_document_complexity(
        self,
        structure: str,
        doc_title: str
    ) -> DocumentComplexity:
        """
        Détecte la complexité conceptuelle attendue d'un document.

        Args:
            structure: Structure de dépendance (CENTRAL, TRANSVERSAL, CONTEXTUAL)
            doc_title: Titre du document

        Returns:
            DocumentComplexity estimée
        """
        title_lower = doc_title.lower()

        # Indicateurs de document procédural
        procedural_keywords = [
            "protocol", "procedure", "checklist", "assessment",
            "protocole", "procédure", "évaluation", "test",
            "verification", "validation", "inspection"
        ]

        # Indicateurs de document conceptuel
        concept_keywords = [
            "guide", "regulation", "standard", "policy",
            "norme", "règlement", "politique", "framework",
            "architecture", "specification", "référentiel"
        ]

        for kw in procedural_keywords:
            if kw in title_lower:
                return DocumentComplexity.PROCEDURAL

        for kw in concept_keywords:
            if kw in title_lower:
                return DocumentComplexity.CONCEPT_RICH

        # CONTEXTUAL structure = souvent procédural
        if structure == "CONTEXTUAL":
            return DocumentComplexity.PROCEDURAL

        return DocumentComplexity.MIXED
