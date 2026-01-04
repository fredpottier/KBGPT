"""
StructuredMerger - Fusionne Docling + Vision sans écrasement.

Règle d'or: Vision n'écrase JAMAIS Docling.

Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 9

Implémentation complète en Phase 5.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

from knowbase.extraction_v2.models import (
    VisionUnit,
    VisionExtraction,
    GatingDecision,
)
from knowbase.extraction_v2.models.elements import TextBlock, TableData

logger = logging.getLogger(__name__)


@dataclass
class MergeProvenance:
    """Provenance des données fusionnées."""
    docling_version: str = "unknown"
    vision_model: Optional[str] = None
    gating_score: Optional[float] = None
    merge_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "docling_version": self.docling_version,
            "vision_model": self.vision_model,
            "gating_score": self.gating_score,
            "merge_timestamp": self.merge_timestamp,
        }


@dataclass
class MergedPageOutput:
    """
    Résultat du merge pour une page.

    Socle (Docling) + Enrichissement (Vision, attaché pas fusionné).
    """
    page_index: int

    # Socle (Docling)
    base_blocks: List[TextBlock] = field(default_factory=list)
    base_tables: List[TableData] = field(default_factory=list)

    # Enrichissement Vision (attaché, pas fusionné)
    vision_enrichment: Optional[VisionExtraction] = None

    # Décision de gating
    gating_decision: Optional[GatingDecision] = None

    # Provenance
    provenance: MergeProvenance = field(default_factory=MergeProvenance)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "page_index": self.page_index,
            "base_blocks": [b.to_dict() for b in self.base_blocks],
            "base_tables": [t.to_dict() for t in self.base_tables],
            "provenance": self.provenance.to_dict(),
        }
        if self.vision_enrichment:
            result["vision_enrichment"] = self.vision_enrichment.to_dict()
        if self.gating_decision:
            result["gating_decision"] = self.gating_decision.to_dict()
        return result


class StructuredMerger:
    """
    Fusionne Docling + Vision sans écrasement.

    Stratégie:
    1. Docling fournit le SOCLE (blocs texte, tables structurées)
    2. Vision fournit l'ENRICHISSEMENT (éléments visuels, relations)
    3. L'enrichissement est ATTACHÉ au socle, jamais fusionné

    Règle d'or: Vision n'écrase JAMAIS Docling.

    Attachement Vision → Base:
    1. Par page_index / slide_index (obligatoire)
    2. Par bbox overlap (optionnel, pour précision)
    3. Marquage explicite source: "docling" | "vision"

    Usage:
        >>> merger = StructuredMerger()
        >>> merged = merger.merge_page(unit, vision_extraction, gating_decision)
        >>> print(merged.base_blocks)  # Docling
        >>> print(merged.vision_enrichment)  # Vision (attaché)

    Note: Implémentation complète en Phase 5.
    """

    def __init__(self):
        """Initialise le merger."""
        logger.info("[StructuredMerger] Created")

    def merge_page(
        self,
        unit: VisionUnit,
        vision_extraction: Optional[VisionExtraction] = None,
        gating_decision: Optional[GatingDecision] = None,
    ) -> MergedPageOutput:
        """
        Fusionne une page Docling avec son enrichissement Vision.

        Args:
            unit: VisionUnit (sortie Docling)
            vision_extraction: Résultat Vision (optionnel)
            gating_decision: Décision de gating (optionnel)

        Returns:
            MergedPageOutput avec socle + enrichissement

        Raises:
            NotImplementedError: Implémentation en Phase 5
        """
        raise NotImplementedError(
            "StructuredMerger.merge_page() sera implémenté en Phase 5."
        )

    def merge_document(
        self,
        units: List[VisionUnit],
        vision_extractions: Dict[int, VisionExtraction],
        gating_decisions: List[GatingDecision],
    ) -> List[MergedPageOutput]:
        """
        Fusionne un document complet.

        Args:
            units: Liste de VisionUnits (Docling)
            vision_extractions: Dict {page_index: VisionExtraction}
            gating_decisions: Liste de décisions de gating

        Returns:
            Liste de MergedPageOutputs

        Raises:
            NotImplementedError: Implémentation en Phase 5
        """
        raise NotImplementedError(
            "StructuredMerger.merge_document() sera implémenté en Phase 5."
        )


__all__ = [
    "MergeProvenance",
    "MergedPageOutput",
    "StructuredMerger",
]
