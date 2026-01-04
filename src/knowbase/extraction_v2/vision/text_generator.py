"""
VisionTextGenerator - Génère le vision_text descriptif pour OSMOSE.

Convertit VisionExtraction en texte balisé pour inclusion dans full_text.

Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 3

Implémentation complète en Phase 4.
"""

from __future__ import annotations
from typing import Optional
import logging

from knowbase.extraction_v2.models import VisionExtraction

logger = logging.getLogger(__name__)


class VisionTextGenerator:
    """
    Génère le vision_text descriptif pour OSMOSE.

    Principe:
    - Vision → description factuelle → texte OSMOSE
    - PAS Vision → interprétation métier → texte "naturel" → OSMOSE

    Le texte généré est factuel, traçable, et balisé.

    Format de sortie:
    ```
    [VISUAL_ENRICHMENT id=vision_6_1 confidence=0.82]
    diagram_type: architecture_diagram

    visible_elements:
    - [E1|box] "SAP Enterprise Cloud Services"
    - [E2|box] "Customer"

    visible_relations (visual only):
    - [E1] -> [E2]
      relation: connected
      evidence: line/arrow

    ambiguities:
    - arrow direction between E1 and E2 is not readable
    [END_VISUAL_ENRICHMENT]
    ```

    Usage:
        >>> generator = VisionTextGenerator()
        >>> vision_text = generator.generate(extraction, page_index=6)
        >>> full_text += vision_text

    Note: Implémentation complète en Phase 4.
    """

    def __init__(self):
        """Initialise le générateur."""
        logger.info("[VisionTextGenerator] Created")

    def generate(
        self,
        extraction: VisionExtraction,
        page_index: int,
        enrichment_id: Optional[str] = None,
    ) -> str:
        """
        Génère le vision_text depuis une VisionExtraction.

        Args:
            extraction: Résultat de l'analyse Vision
            page_index: Index de la page source
            enrichment_id: ID personnalisé (auto-généré si non fourni)

        Returns:
            Texte balisé pour inclusion dans full_text
        """
        # Utilise la méthode to_vision_text de VisionExtraction
        return extraction.to_vision_text(page_index=page_index)

    def generate_empty(self, page_index: int, reason: str = "no_vision") -> str:
        """
        Génère un placeholder pour une page sans Vision.

        Args:
            page_index: Index de la page
            reason: Raison de l'absence de Vision

        Returns:
            Placeholder minimal
        """
        return f"[VISUAL_ENRICHMENT id=vision_{page_index}_skipped reason={reason}]\n(No visual analysis performed)\n[END_VISUAL_ENRICHMENT]"


__all__ = ["VisionTextGenerator"]
