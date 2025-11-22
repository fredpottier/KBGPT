"""
🌊 OSMOSE Semantic Intelligence - Fusion Rules (Abstract Base Class)

Phase 1.8.1d: Interface pour règles de fusion de concepts.

Design Pattern: Strategy Pattern
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

from knowbase.semantic.models import Concept
from .models import FusionResult


class FusionRule(ABC):
    """
    Règle de fusion abstraite.

    Les règles concrètes héritent de cette classe et implémentent:
    - should_apply(): Détermine si règle doit s'appliquer
    - apply(): Applique la règle de fusion

    Design Pattern: Strategy Pattern
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise la règle de fusion.

        Args:
            config: Configuration règle (depuis YAML)
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Nom unique de la règle.

        Returns:
            str: Nom de la règle (ex: "main_entities_merge")
        """
        pass

    @property
    def priority(self) -> int:
        """
        Priorité de la règle (ordre d'application).

        Returns:
            int: Priorité (1 = haute, 99 = basse)
        """
        return self.config.get("priority", 99)

    @property
    def enabled(self) -> bool:
        """
        Règle activée ?

        Returns:
            bool: True si règle activée
        """
        return self.config.get("enabled", True)

    @abstractmethod
    def should_apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> bool:
        """
        Détermine si règle doit s'appliquer.

        Args:
            concepts: Liste concepts candidats
            context: Contexte document/segment (optionnel)
                - total_slides: Nombre total de slides
                - document_type: Type document (PPTX, PDF, etc.)
                - language: Langue document

        Returns:
            bool: True si règle applicable aux concepts fournis
        """
        pass

    @abstractmethod
    async def apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> FusionResult:
        """
        Applique règle de fusion.

        Args:
            concepts: Concepts à fusionner
            context: Contexte additionnel (optionnel)

        Returns:
            FusionResult: Résultat avec concepts fusionnés/préservés

        Raises:
            Exception: Si erreur durant application règle
        """
        pass

    def _log_application(
        self,
        concepts: List[Concept],
        result: FusionResult,
        duration_ms: float
    ):
        """
        Log application de la règle.

        Args:
            concepts: Concepts d'entrée
            result: Résultat de l'application
            duration_ms: Durée d'exécution (ms)
        """
        self.logger.info(
            f"[OSMOSE:Fusion:{self.name}] Applied to {len(concepts)} concepts → "
            f"{len(result.merged_concepts)} merged, {len(result.preserved_concepts)} preserved "
            f"({duration_ms:.1f}ms)"
        )

        if result.relationships:
            self.logger.debug(
                f"[OSMOSE:Fusion:{self.name}] Created {len(result.relationships)} relationships"
            )
