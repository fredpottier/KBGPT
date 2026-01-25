"""
Validateur de Justification - Anti-Fallback

Vérifie que les justifications sont réelles, pas des fallbacks.
Rejette les justifications génériques type "par défaut".
"""

from typing import Tuple, List
from dataclasses import dataclass
import re


@dataclass
class JustificationResult:
    """Résultat de validation de justification"""
    is_valid: bool
    issues: List[str]
    score: float  # 0-1, qualité de la justification


class JustificationValidator:
    """
    Valide que les justifications sont substantielles.

    Règles:
    - Pas de "par défaut", "default", "fallback"
    - Minimum 30 caractères
    - Doit mentionner le contenu du document
    - Les rejets doivent être argumentés
    """

    # Patterns de fallback à rejeter
    FALLBACK_PATTERNS = [
        r"par\s+d[eé]faut",
        r"default",
        r"fallback",
        r"moins\s+pertinent\s+que",
        r"non\s+s[eé]lectionn[eé]",
        r"structure\s+par\s+d[eé]faut",
        r"analyse\s+automatique",
    ]

    # Mots-clés attendus dans une vraie justification
    QUALITY_INDICATORS = [
        r"document",
        r"contenu",
        r"assertions?",
        r"d[eé]pend",
        r"ind[eé]pendant",
        r"conditionn",
        r"artefact",
        r"central",
        r"g[eé]n[eé]ral",
        r"sp[eé]cifique",
    ]

    MIN_JUSTIFICATION_LENGTH = 30
    MIN_REJECTION_LENGTH = 15

    def validate_structure_justification(
        self,
        chosen: str,
        justification: str,
        rejected: dict
    ) -> JustificationResult:
        """
        Valide la justification de structure de dépendance.

        Args:
            chosen: Structure choisie (CENTRAL, TRANSVERSAL, CONTEXTUAL)
            justification: Justification du choix
            rejected: Dict des structures rejetées avec raisons

        Returns:
            JustificationResult
        """
        issues = []
        score = 1.0

        # 1. Vérifier longueur minimale
        if len(justification) < self.MIN_JUSTIFICATION_LENGTH:
            issues.append(f"Justification trop courte ({len(justification)} < {self.MIN_JUSTIFICATION_LENGTH})")
            score -= 0.3

        # 2. Détecter les patterns de fallback
        justification_lower = justification.lower()
        for pattern in self.FALLBACK_PATTERNS:
            if re.search(pattern, justification_lower):
                issues.append(f"Pattern fallback détecté: '{pattern}'")
                score -= 0.4

        # 3. Vérifier les indicateurs de qualité
        quality_found = 0
        for indicator in self.QUALITY_INDICATORS:
            if re.search(indicator, justification_lower):
                quality_found += 1

        if quality_found == 0:
            issues.append("Aucun indicateur de qualité (document, contenu, assertions...)")
            score -= 0.2

        # 4. Vérifier les rejets
        expected_rejections = {"CENTRAL", "TRANSVERSAL", "CONTEXTUAL"} - {chosen}
        for struct in expected_rejections:
            if struct not in rejected:
                issues.append(f"Rejet manquant pour {struct}")
                score -= 0.2
            else:
                rejection_text = rejected[struct]
                # Vérifier que le rejet n'est pas un fallback
                if len(rejection_text) < self.MIN_REJECTION_LENGTH:
                    issues.append(f"Rejet trop court pour {struct}")
                    score -= 0.1
                for pattern in self.FALLBACK_PATTERNS:
                    if re.search(pattern, rejection_text.lower()):
                        issues.append(f"Rejet fallback pour {struct}: '{pattern}'")
                        score -= 0.2

        score = max(0.0, score)
        is_valid = score >= 0.5 and len([i for i in issues if "fallback" in i.lower()]) == 0

        return JustificationResult(
            is_valid=is_valid,
            issues=issues,
            score=score
        )

    def validate_concept_rationale(
        self,
        concept_name: str,
        rationale: str
    ) -> Tuple[bool, str]:
        """
        Valide la justification d'un concept.

        Returns:
            (is_valid, error_or_empty)
        """
        if not rationale or len(rationale) < 10:
            return False, "Rationale manquant ou trop court"

        # Vérifier patterns fallback
        for pattern in self.FALLBACK_PATTERNS:
            if re.search(pattern, rationale.lower()):
                return False, f"Rationale fallback: {pattern}"

        return True, ""
