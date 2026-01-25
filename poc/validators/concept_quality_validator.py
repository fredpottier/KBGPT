"""
Validateur de Qualité Conceptuelle - Anti-Bruit

Filtre les "concepts" qui sont en réalité du bruit lexical.
Ex: "Lizard", "February", "Where", "Euro"
"""

from typing import List, Tuple, Set
from dataclasses import dataclass
import re


@dataclass
class ConceptQualityResult:
    """Résultat de validation qualité concept"""
    is_valid: bool
    reason: str
    quality_score: float  # 0-1


class ConceptQualityValidator:
    """
    Valide la qualité sémantique des concepts extraits.

    Un concept valide doit:
    - Ne pas être un mot générique (stopword étendu)
    - Ne pas être un mot temporel (mois, jours)
    - Ne pas être un mot de liaison
    - Avoir une signification conceptuelle
    """

    # Mots à rejeter systématiquement (bruit lexical)
    NOISE_WORDS: Set[str] = {
        # Temporels
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",

        # Mots de liaison / génériques
        "where", "when", "what", "which", "who", "how", "why",
        "here", "there", "this", "that", "these", "those",
        "and", "but", "or", "nor", "for", "yet", "so",

        # Trop génériques
        "version", "document", "section", "page", "figure", "table",
        "example", "note", "chapter", "appendix", "annex",
        "introduction", "conclusion", "summary", "overview",
        "item", "point", "part", "element", "component",

        # Numériques / Mesures
        "number", "value", "amount", "total", "count",
        "percent", "percentage", "ratio", "rate",

        # Animaux/Objets incongrus (bruit OCR ou métaphores)
        "lizard", "animal", "bird", "fish",

        # Géographiques génériques
        "euro", "europe", "america", "asia", "africa",
        "country", "region", "area", "zone",

        # Actions trop génériques
        "use", "make", "take", "give", "get", "set",
        "function", "process", "method", "approach",
    }

    # Patterns de concepts valides (indicateurs positifs)
    VALID_CONCEPT_PATTERNS = [
        r"^[A-Z][a-z]+\s+[A-Z][a-z]+",  # Deux mots capitalisés
        r"^[A-Z]{2,}$",  # Acronyme (GDPR, DPO, etc.)
        r"^[A-Z][a-z]+\s+[A-Z][a-z]+\s+[A-Z][a-z]+",  # Trois mots
        r"protection|compliance|regulation|management|security",
        r"controller|processor|officer|authority",
        r"assessment|evaluation|monitoring|verification",
    ]

    # Longueur minimale pour un concept
    MIN_CONCEPT_LENGTH = 3
    MAX_SINGLE_WORD_AS_CONCEPT = False  # Mots seuls rarement valides

    def validate_concept(
        self,
        concept_name: str,
        role: str = "STANDARD"
    ) -> ConceptQualityResult:
        """
        Valide un concept unique.

        Args:
            concept_name: Nom du concept
            role: Rôle (CENTRAL, CONTEXTUAL, STANDARD)

        Returns:
            ConceptQualityResult
        """
        name_lower = concept_name.lower().strip()
        name_words = name_lower.split()

        # 1. Vérifier longueur minimale
        if len(concept_name) < self.MIN_CONCEPT_LENGTH:
            return ConceptQualityResult(
                is_valid=False,
                reason=f"Concept trop court ({len(concept_name)} < {self.MIN_CONCEPT_LENGTH})",
                quality_score=0.0
            )

        # 2. Vérifier si c'est un mot de bruit
        if name_lower in self.NOISE_WORDS:
            return ConceptQualityResult(
                is_valid=False,
                reason=f"Mot de bruit détecté: '{concept_name}'",
                quality_score=0.0
            )

        # 3. Vérifier chaque mot composant
        for word in name_words:
            if word.lower() in self.NOISE_WORDS:
                # Un mot de bruit dans un concept composé = warning, pas rejet
                if len(name_words) == 1:
                    return ConceptQualityResult(
                        is_valid=False,
                        reason=f"Mot unique de bruit: '{word}'",
                        quality_score=0.1
                    )

        # 4. Mot unique non-acronyme = suspect
        if len(name_words) == 1 and not re.match(r'^[A-Z]{2,}$', concept_name):
            # Exception pour certains termes métier reconnus
            valid_single_words = {
                "gdpr", "rgpd", "processor", "controller", "breach", "consent",
                "security", "privacy", "compliance", "audit", "risk"
            }
            if name_lower not in valid_single_words:
                return ConceptQualityResult(
                    is_valid=False,
                    reason=f"Mot unique non-acronyme suspect: '{concept_name}'",
                    quality_score=0.3
                )

        # 5. Vérifier patterns positifs
        quality_score = 0.5
        for pattern in self.VALID_CONCEPT_PATTERNS:
            if re.search(pattern, concept_name, re.IGNORECASE):
                quality_score += 0.1

        quality_score = min(1.0, quality_score)

        return ConceptQualityResult(
            is_valid=True,
            reason="",
            quality_score=quality_score
        )

    def filter_concepts(
        self,
        concepts: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """
        Filtre une liste de concepts.

        Returns:
            (valid_concepts, rejected_concepts)
        """
        valid = []
        rejected = []

        for concept in concepts:
            name = concept.get("name", "")
            role = concept.get("role", "STANDARD")

            result = self.validate_concept(name, role)

            if result.is_valid:
                valid.append(concept)
            else:
                concept["rejection_reason"] = result.reason
                rejected.append(concept)

        return valid, rejected

    def compute_noise_ratio(self, concepts: List[dict]) -> float:
        """
        Calcule le ratio de bruit dans les concepts.

        Returns:
            Ratio 0-1 (0 = pas de bruit, 1 = tout est bruit)
        """
        if not concepts:
            return 0.0

        noise_count = 0
        for concept in concepts:
            result = self.validate_concept(concept.get("name", ""))
            if not result.is_valid:
                noise_count += 1

        return noise_count / len(concepts)
