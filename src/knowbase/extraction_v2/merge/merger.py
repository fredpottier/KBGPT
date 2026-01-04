"""
StructuredMerger - Fusionne Docling + Vision sans ecrasement.

Regle d'or: Vision n'ecrase JAMAIS Docling.

Specification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Decision 9
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
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
    """Provenance des donnees fusionnees."""
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
    Resultat du merge pour une page.

    Socle (Docling) + Enrichissement (Vision, attache pas fusionne).
    """
    page_index: int

    # Socle (Docling)
    base_blocks: List[TextBlock] = field(default_factory=list)
    base_tables: List[TableData] = field(default_factory=list)

    # Enrichissement Vision (attache, pas fusionne)
    vision_enrichment: Optional[VisionExtraction] = None

    # Decision de gating
    gating_decision: Optional[GatingDecision] = None

    # Provenance
    provenance: MergeProvenance = field(default_factory=MergeProvenance)

    # Titre de la page (si detecte)
    title: Optional[str] = None

    # Format source (PDF, PPTX, etc.)
    format: str = "unknown"

    @property
    def has_vision(self) -> bool:
        """Verifie si la page a un enrichissement Vision."""
        return self.vision_enrichment is not None

    @property
    def text_content(self) -> str:
        """Retourne le contenu texte brut de la page."""
        return "\n".join(b.text for b in self.base_blocks if b.text)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "page_index": self.page_index,
            "format": self.format,
            "title": self.title,
            "base_blocks": [b.to_dict() for b in self.base_blocks],
            "base_tables": [t.to_dict() for t in self.base_tables],
            "provenance": self.provenance.to_dict(),
            "has_vision": self.has_vision,
        }
        if self.vision_enrichment:
            result["vision_enrichment"] = self.vision_enrichment.to_dict()
        if self.gating_decision:
            result["gating_decision"] = self.gating_decision.to_dict()
        return result


class StructuredMerger:
    """
    Fusionne Docling + Vision sans ecrasement.

    Strategie:
    1. Docling fournit le SOCLE (blocs texte, tables structurees)
    2. Vision fournit l'ENRICHISSEMENT (elements visuels, relations)
    3. L'enrichissement est ATTACHE au socle, jamais fusionne

    Regle d'or: Vision n'ecrase JAMAIS Docling.

    Attachement Vision -> Base:
    1. Par page_index / slide_index (obligatoire)
    2. Par bbox overlap (optionnel, pour precision)
    3. Marquage explicite source: "docling" | "vision"

    Usage:
        >>> merger = StructuredMerger()
        >>> merged = merger.merge_page(unit, vision_extraction, gating_decision)
        >>> print(merged.base_blocks)  # Docling
        >>> print(merged.vision_enrichment)  # Vision (attache)
    """

    def __init__(self, docling_version: str = "2.14.0", vision_model: str = "gpt-4o"):
        """
        Initialise le merger.

        Args:
            docling_version: Version de Docling utilisee
            vision_model: Modele Vision utilise
        """
        self.docling_version = docling_version
        self.vision_model = vision_model
        logger.info(
            f"[StructuredMerger] Created with docling={docling_version}, "
            f"vision={vision_model}"
        )

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
            vision_extraction: Resultat Vision (optionnel)
            gating_decision: Decision de gating (optionnel)

        Returns:
            MergedPageOutput avec socle + enrichissement
        """
        # Creer la provenance
        provenance = MergeProvenance(
            docling_version=self.docling_version,
            vision_model=self.vision_model if vision_extraction else None,
            gating_score=gating_decision.vision_need_score if gating_decision else None,
            merge_timestamp=datetime.now().isoformat(),
        )

        # Copier les blocs de base (Docling = socle)
        base_blocks = list(unit.blocks)
        base_tables = list(unit.tables)

        # Creer le resultat fusionne
        merged = MergedPageOutput(
            page_index=unit.index,
            base_blocks=base_blocks,
            base_tables=base_tables,
            vision_enrichment=vision_extraction,
            gating_decision=gating_decision,
            provenance=provenance,
            title=unit.title,
            format=unit.format,
        )

        logger.debug(
            f"[StructuredMerger] Merged page {unit.index}: "
            f"{len(base_blocks)} blocks, {len(base_tables)} tables, "
            f"vision={'yes' if vision_extraction else 'no'}"
        )

        return merged

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
            gating_decisions: Liste de decisions de gating

        Returns:
            Liste de MergedPageOutputs
        """
        # Indexer les decisions par page
        decisions_by_page = {d.index: d for d in gating_decisions}

        merged_pages = []

        for unit in units:
            # Recuperer l'extraction Vision si disponible
            vision_extraction = vision_extractions.get(unit.index)

            # Recuperer la decision de gating
            gating_decision = decisions_by_page.get(unit.index)

            # Fusionner la page
            merged = self.merge_page(unit, vision_extraction, gating_decision)
            merged_pages.append(merged)

        # Log summary
        pages_with_vision = sum(1 for m in merged_pages if m.has_vision)
        logger.info(
            f"[StructuredMerger] Document merged: {len(merged_pages)} pages, "
            f"{pages_with_vision} with Vision enrichment"
        )

        return merged_pages

    def enrich_with_vision(
        self,
        merged_page: MergedPageOutput,
        vision_extraction: VisionExtraction,
    ) -> MergedPageOutput:
        """
        Enrichit une page deja fusionnee avec Vision.

        Permet d'ajouter Vision apres coup sans re-merger.

        Args:
            merged_page: Page deja fusionnee
            vision_extraction: Extraction Vision a attacher

        Returns:
            MergedPageOutput enrichi
        """
        merged_page.vision_enrichment = vision_extraction
        merged_page.provenance.vision_model = self.vision_model
        merged_page.provenance.merge_timestamp = datetime.now().isoformat()

        logger.debug(
            f"[StructuredMerger] Enriched page {merged_page.page_index} with Vision"
        )

        return merged_page


__all__ = [
    "MergeProvenance",
    "MergedPageOutput",
    "StructuredMerger",
]
