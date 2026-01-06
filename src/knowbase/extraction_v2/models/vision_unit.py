"""
VisionUnit pour Extraction V2.

Unité de décision pour le Vision Gating.
1 unit = 1 décision (page PDF ou slide PPTX).

Spécification: VISION_GATING_V4_CLASS_SCHEMA.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from knowbase.extraction_v2.models.elements import (
    BoundingBox,
    TextBlock,
    VisualElement,
    TableData,
)


@dataclass
class VisionUnit:
    """
    Unité de décision pour le Vision Gating.

    1 unit = 1 décision (page PDF ou slide PPTX).

    Contient toutes les informations nécessaires pour:
    - Calculer les 5 signaux du Vision Gating v4
    - Décider si Vision est nécessaire
    - Fusionner les résultats Docling + Vision

    Attributs:
        id: Identifiant unique (ex: "PDF_PAGE_6", "PPTX_SLIDE_12")
        format: Format du document ("PDF", "PPTX", "DOCX", "XLSX")
        index: Index de la page/slide (0-based)
        dimensions: Dimensions (width, height) en points ou pixels

        blocks: Blocs de texte extraits par Docling
        tables: Tableaux structurés extraits par Docling
        visual_elements: Éléments visuels détectés

        notes: Notes de slide (PPTX uniquement)
        has_notes: Indique si la slide a des notes

        raw_docling_output: Sortie brute Docling (pour debug/audit)
    """
    # Identifiant et contexte
    id: str  # "PDF_PAGE_6", "PPTX_SLIDE_12"
    format: str  # "PDF", "PPTX", "DOCX", "XLSX"
    index: int  # page_index ou slide_index (0-based)
    dimensions: Tuple[float, float]  # (width, height)

    # Contenu extrait par Docling
    blocks: List[TextBlock] = field(default_factory=list)
    tables: List[TableData] = field(default_factory=list)
    visual_elements: List[VisualElement] = field(default_factory=list)

    # Métadonnées PPTX
    notes: str = ""
    has_notes: bool = False

    # Titre de la page/slide (si détecté)
    title: Optional[str] = None

    # Sortie brute Docling (pour debug)
    raw_docling_output: Optional[Dict[str, Any]] = None

    @property
    def page_area(self) -> float:
        """Surface totale de la page en unités carrées."""
        return self.dimensions[0] * self.dimensions[1]

    @property
    def width(self) -> float:
        """Largeur de la page."""
        return self.dimensions[0]

    @property
    def height(self) -> float:
        """Hauteur de la page."""
        return self.dimensions[1]

    @property
    def text_blocks_count(self) -> int:
        """Nombre de blocs de texte."""
        return len(self.blocks)

    @property
    def short_blocks_count(self) -> int:
        """Nombre de blocs courts (< 200 chars)."""
        return sum(1 for b in self.blocks if b.is_short)

    @property
    def long_blocks_count(self) -> int:
        """Nombre de blocs longs (>= 200 chars)."""
        return sum(1 for b in self.blocks if not b.is_short)

    @property
    def total_text_length(self) -> int:
        """Longueur totale du texte."""
        return sum(b.char_count for b in self.blocks)

    @property
    def avg_block_length(self) -> float:
        """Longueur moyenne des blocs."""
        if not self.blocks:
            return 0.0
        return self.total_text_length / len(self.blocks)

    @property
    def images_count(self) -> int:
        """Nombre d'images raster."""
        return sum(1 for e in self.visual_elements if e.is_image)

    @property
    def vectors_count(self) -> int:
        """Nombre de dessins vectoriels."""
        return sum(1 for e in self.visual_elements if e.is_vector)

    @property
    def connectors_count(self) -> int:
        """Nombre de connecteurs."""
        return sum(1 for e in self.visual_elements if e.is_connector)

    @property
    def tables_count(self) -> int:
        """Nombre de tableaux structurés."""
        return len(self.tables)

    @property
    def has_structured_tables(self) -> bool:
        """Indique si des tableaux structurés existent."""
        return any(t.is_structured for t in self.tables)

    @property
    def largest_image_ratio(self) -> float:
        """
        Ratio de la plus grande image par rapport à la page.
        Utilisé pour le signal RIS.
        """
        images = [e for e in self.visual_elements if e.is_image]
        if not images:
            return 0.0

        max_area = max(e.bbox.area for e in images)
        # Si bbox normalisée, area est déjà le ratio
        # Sinon, normaliser par la surface de la page
        if images[0].bbox.normalized:
            return max_area
        return max_area / self.page_area if self.page_area > 0 else 0.0

    @property
    def vector_density(self) -> float:
        """
        Densité des dessins vectoriels (surface totale / surface page).
        Utilisé pour le signal VDS.
        """
        vectors = [e for e in self.visual_elements if e.is_vector]
        if not vectors:
            return 0.0

        total_area = sum(e.bbox.area for e in vectors)
        if vectors[0].bbox.normalized:
            return min(total_area, 1.0)
        return min(total_area / self.page_area, 1.0) if self.page_area > 0 else 0.0

    @property
    def full_text(self) -> str:
        """
        Texte complet de la page (concaténation des blocs).
        Pour usage simple, préférer la linéarisation avec marqueurs.
        """
        return "\n\n".join(b.text for b in self.blocks)

    def get_blocks_with_bbox(self) -> List[TextBlock]:
        """Retourne uniquement les blocs avec bounding box."""
        return [b for b in self.blocks if b.bbox is not None]

    def get_text_dispersion(self) -> float:
        """
        Calcule la dispersion spatiale du texte.
        Utilisé pour le signal SDS.

        Retourne la variance normalisée des positions des centres des blocs.
        """
        blocks_with_bbox = self.get_blocks_with_bbox()
        if len(blocks_with_bbox) < 2:
            return 0.0

        # Collecter les centres
        centers_x = [b.bbox.center[0] for b in blocks_with_bbox]
        centers_y = [b.bbox.center[1] for b in blocks_with_bbox]

        # Calculer la variance
        mean_x = sum(centers_x) / len(centers_x)
        mean_y = sum(centers_y) / len(centers_y)

        var_x = sum((x - mean_x) ** 2 for x in centers_x) / len(centers_x)
        var_y = sum((y - mean_y) ** 2 for y in centers_y) / len(centers_y)

        # Variance totale normalisée
        # Pour une bbox normalisée, la variance max théorique est 0.25 (0.5^2)
        total_variance = (var_x + var_y) / 2
        normalized_variance = min(total_variance / 0.25, 1.0)

        return normalized_variance

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "id": self.id,
            "format": self.format,
            "index": self.index,
            "dimensions": list(self.dimensions),
            "blocks": [b.to_dict() for b in self.blocks],
            "tables": [t.to_dict() for t in self.tables],
            "visual_elements": [e.to_dict() for e in self.visual_elements],
            "notes": self.notes,
            "has_notes": self.has_notes,
            "title": self.title,
            # Statistiques calculées
            "stats": {
                "text_blocks_count": self.text_blocks_count,
                "short_blocks_count": self.short_blocks_count,
                "total_text_length": self.total_text_length,
                "images_count": self.images_count,
                "vectors_count": self.vectors_count,
                "connectors_count": self.connectors_count,
                "tables_count": self.tables_count,
                "largest_image_ratio": self.largest_image_ratio,
                "vector_density": self.vector_density,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionUnit":
        """Désérialise depuis un dictionnaire."""
        return cls(
            id=data["id"],
            format=data["format"],
            index=data["index"],
            dimensions=tuple(data["dimensions"]),
            blocks=[TextBlock.from_dict(b) for b in data.get("blocks", [])],
            tables=[TableData.from_dict(t) for t in data.get("tables", [])],
            visual_elements=[
                VisualElement.from_dict(e) for e in data.get("visual_elements", [])
            ],
            notes=data.get("notes", ""),
            has_notes=data.get("has_notes", False),
            title=data.get("title"),
        )

    def __repr__(self) -> str:
        return (
            f"VisionUnit({self.id}: {self.text_blocks_count} blocks, "
            f"{self.images_count} images, {self.vectors_count} vectors)"
        )
