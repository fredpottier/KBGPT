"""
Éléments de base pour Extraction V2.

BoundingBox: Boîte englobante normalisée ou en pixels.
TextBlock: Bloc de texte extrait par Docling.
VisualElement: Élément visuel détecté par Docling.

Spécification: VISION_GATING_V4_CLASS_SCHEMA.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class BoundingBox:
    """
    Bounding box normalisée (0..1) ou en pixels.

    Coordonnées:
    - x, y: coin supérieur gauche
    - width, height: dimensions

    Convention: origine en haut à gauche de la page.
    """
    x: float
    y: float
    width: float
    height: float

    # Indique si les coordonnées sont normalisées (0..1) ou en pixels
    normalized: bool = True

    @property
    def area(self) -> float:
        """Surface de la bounding box."""
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        """Centre de la bounding box."""
        return (self.x + self.width / 2, self.y + self.height / 2)

    @property
    def x2(self) -> float:
        """Coordonnée x du coin inférieur droit."""
        return self.x + self.width

    @property
    def y2(self) -> float:
        """Coordonnée y du coin inférieur droit."""
        return self.y + self.height

    def overlaps(self, other: "BoundingBox") -> bool:
        """Vérifie si deux bounding boxes se chevauchent."""
        return not (
            self.x2 < other.x or
            other.x2 < self.x or
            self.y2 < other.y or
            other.y2 < self.y
        )

    def overlap_ratio(self, other: "BoundingBox") -> float:
        """
        Calcule le ratio de chevauchement (IoU - Intersection over Union).
        Retourne 0.0 si pas de chevauchement.
        """
        if not self.overlaps(other):
            return 0.0

        # Calcul de l'intersection
        inter_x = max(self.x, other.x)
        inter_y = max(self.y, other.y)
        inter_x2 = min(self.x2, other.x2)
        inter_y2 = min(self.y2, other.y2)

        inter_area = (inter_x2 - inter_x) * (inter_y2 - inter_y)
        union_area = self.area + other.area - inter_area

        if union_area <= 0:
            return 0.0

        return inter_area / union_area

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "normalized": self.normalized,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        """Désérialise depuis un dictionnaire."""
        return cls(
            x=data["x"],
            y=data["y"],
            width=data["width"],
            height=data["height"],
            normalized=data.get("normalized", True),
        )

    def normalize(self, page_width: float, page_height: float) -> "BoundingBox":
        """
        Normalise les coordonnées par rapport aux dimensions de la page.
        Retourne une nouvelle BoundingBox normalisée.
        """
        if self.normalized:
            return self

        return BoundingBox(
            x=self.x / page_width,
            y=self.y / page_height,
            width=self.width / page_width,
            height=self.height / page_height,
            normalized=True,
        )


@dataclass
class TextBlock:
    """
    Bloc de texte extrait par Docling.

    Types de blocs:
    - heading: Titre (niveau 1-6)
    - paragraph: Paragraphe
    - list_item: Élément de liste
    - table_cell: Cellule de tableau
    - caption: Légende
    - footnote: Note de bas de page
    - code: Bloc de code
    - other: Autre
    """
    # Type de bloc
    type: str  # "heading", "paragraph", "list_item", etc.

    # Contenu textuel
    text: str

    # Position (optionnel, peut ne pas être disponible)
    bbox: Optional[BoundingBox] = None

    # Niveau (pour les headings: 1-6)
    level: int = 0

    # Métadonnées additionnelles
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Identifiant unique dans le document
    block_id: Optional[str] = None

    @property
    def char_count(self) -> int:
        """Nombre de caractères dans le bloc."""
        return len(self.text)

    @property
    def word_count(self) -> int:
        """Nombre approximatif de mots."""
        return len(self.text.split())

    @property
    def is_short(self) -> bool:
        """
        Indique si le bloc est court (< 200 caractères).
        Utilisé pour le signal TFS (Text Fragmentation Signal).
        """
        return self.char_count < 200

    @property
    def is_heading(self) -> bool:
        """Indique si le bloc est un titre."""
        return self.type == "heading"

    @property
    def is_paragraph(self) -> bool:
        """Indique si le bloc est un paragraphe."""
        return self.type == "paragraph"

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        result = {
            "type": self.type,
            "text": self.text,
            "level": self.level,
            "metadata": self.metadata,
        }
        if self.bbox:
            result["bbox"] = self.bbox.to_dict()
        if self.block_id:
            result["block_id"] = self.block_id
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextBlock":
        """Désérialise depuis un dictionnaire."""
        bbox = None
        if "bbox" in data and data["bbox"]:
            bbox = BoundingBox.from_dict(data["bbox"])

        return cls(
            type=data["type"],
            text=data["text"],
            bbox=bbox,
            level=data.get("level", 0),
            metadata=data.get("metadata", {}),
            block_id=data.get("block_id"),
        )


@dataclass
class VisualElement:
    """
    Élément visuel détecté par Docling.

    Types d'éléments:
    - raster_image: Image raster (PNG, JPEG, etc.)
    - vector_drawing: Dessin vectoriel (shapes, lignes)
    - connector: Connecteur (flèche, ligne entre shapes)
    - table: Tableau
    - chart: Graphique/diagramme
    - icon: Icône
    - group: Groupe de shapes
    """
    # Type d'élément
    kind: str  # "raster_image", "vector_drawing", "connector", "table", etc.

    # Position
    bbox: BoundingBox

    # Métadonnées spécifiques au type
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Identifiant unique
    element_id: Optional[str] = None

    # Contenu textuel extrait (si applicable)
    text_content: Optional[str] = None

    # Score de confiance de la détection
    confidence: float = 1.0

    @property
    def is_image(self) -> bool:
        """Indique si c'est une image raster."""
        return self.kind == "raster_image"

    @property
    def is_vector(self) -> bool:
        """Indique si c'est un dessin vectoriel."""
        return self.kind in ("vector_drawing", "connector")

    @property
    def is_connector(self) -> bool:
        """Indique si c'est un connecteur (flèche, ligne)."""
        return self.kind == "connector"

    @property
    def is_table(self) -> bool:
        """Indique si c'est un tableau."""
        return self.kind == "table"

    @property
    def area_ratio(self) -> float:
        """
        Ratio de surface par rapport à la page (si bbox normalisée).
        Utilisé pour le signal RIS.
        """
        if self.bbox.normalized:
            return self.bbox.area
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        result = {
            "kind": self.kind,
            "bbox": self.bbox.to_dict(),
            "metadata": self.metadata,
            "confidence": self.confidence,
        }
        if self.element_id:
            result["element_id"] = self.element_id
        if self.text_content:
            result["text_content"] = self.text_content
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualElement":
        """Désérialise depuis un dictionnaire."""
        return cls(
            kind=data["kind"],
            bbox=BoundingBox.from_dict(data["bbox"]),
            metadata=data.get("metadata", {}),
            element_id=data.get("element_id"),
            text_content=data.get("text_content"),
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class TableData:
    """
    Données structurées d'un tableau.

    Préserve la structure complète du tableau
    (pas d'aplatissement en texte).
    """
    # Identifiant unique
    table_id: str

    # Position dans la page
    bbox: Optional[BoundingBox] = None

    # Nombre de lignes et colonnes
    num_rows: int = 0
    num_cols: int = 0

    # Données du tableau (liste de lignes, chaque ligne est une liste de cellules)
    cells: List[List[str]] = field(default_factory=list)

    # Headers détectés
    headers: List[str] = field(default_factory=list)

    # Métadonnées
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Indique si le tableau a été extrait par Docling (structuré)
    # ou s'il nécessite Vision (pseudo-table graphique)
    is_structured: bool = True

    # === QW-1: Résumé en langage naturel (pour améliorer le RAG) ===
    # Généré par TableSummarizer, stocké avec le raw Markdown
    summary: Optional[str] = None

    def to_markdown(self) -> str:
        """Convertit le tableau en Markdown."""
        if not self.cells:
            return ""

        lines = []

        # Headers
        if self.headers:
            lines.append("| " + " | ".join(self.headers) + " |")
            lines.append("|" + "|".join(["---"] * len(self.headers)) + "|")

        # Données
        for row in self.cells:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        result = {
            "table_id": self.table_id,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
            "cells": self.cells,
            "headers": self.headers,
            "metadata": self.metadata,
            "is_structured": self.is_structured,
        }
        if self.bbox:
            result["bbox"] = self.bbox.to_dict()
        if self.summary:
            result["summary"] = self.summary
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TableData":
        """Désérialise depuis un dictionnaire."""
        bbox = None
        if "bbox" in data and data["bbox"]:
            bbox = BoundingBox.from_dict(data["bbox"])

        return cls(
            table_id=data["table_id"],
            bbox=bbox,
            num_rows=data.get("num_rows", 0),
            num_cols=data.get("num_cols", 0),
            cells=data.get("cells", []),
            headers=data.get("headers", []),
            metadata=data.get("metadata", {}),
            is_structured=data.get("is_structured", True),
            summary=data.get("summary"),
        )
