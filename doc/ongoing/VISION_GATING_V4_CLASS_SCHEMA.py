"""
Vision Gating v4 - Schéma de classes Python

Proposition de ChatGPT pour l'implémentation de la refonte extraction.
Date: 2026-01-02

Ce fichier sert de référence pour l'implémentation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ---------- Domain Context ----------

@dataclass
class DomainContext:
    """
    Contexte métier pour guider l'interprétation.
    Ne crée JAMAIS d'information, réduit l'espace des interprétations.
    """
    name: str  # e.g., "SAP", "Regulatory", "LifeScience"
    interpretation_rules: List[str] = field(default_factory=list)
    domain_vocabulary: Dict[str, str] = field(default_factory=dict)  # acronym -> explanation
    key_concepts: List[str] = field(default_factory=list)
    business_context: str = ""
    extraction_focus: str = ""


# ---------- Decisions ----------

class ExtractionAction(str, Enum):
    """Décision de gating - aligné avec Vision Gating v4."""
    NONE = "none"                      # NO_VISION
    OCR_ONLY = "ocr_only"              # Extraction texte sans vision
    VISION_REQUIRED = "vision_required"
    VISION_RECOMMENDED = "vision_recommended"  # Ajouté pour V4


# ---------- Vision Gating v4 Signals ----------

@dataclass
class VisionSignals:
    """
    Les 5 signaux du Vision Gating v4.
    Chaque signal est un float entre 0.0 et 1.0.
    """
    RIS: float = 0.0  # Raster Image Signal
    VDS: float = 0.0  # Vector Drawing Signal
    TFS: float = 0.0  # Text Fragmentation Signal
    SDS: float = 0.0  # Spatial Dispersion Signal
    VTS: float = 0.0  # Visual Table Signal


# ---------- Feature models ----------

@dataclass
class BoundingBox:
    """Bounding box normalisée (0..1) ou en pixels."""
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass
class TextBlock:
    """Bloc de texte extrait par Docling."""
    type: str  # "heading", "paragraph", "list_item", etc.
    text: str
    bbox: Optional[BoundingBox] = None
    level: int = 0  # Pour les headings


@dataclass
class VisualElement:
    """Élément visuel détecté par Docling."""
    kind: str  # "raster_image", "vector_drawing", "connector", "table"
    bbox: BoundingBox
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionUnit:
    """
    Unité de décision pour le Vision Gating.
    1 unit = 1 décision (page PDF ou slide PPTX).
    """
    id: str  # "PDF_PAGE_6", "PPTX_SLIDE_12"
    format: str  # "PDF" ou "PPTX"
    index: int  # page_index ou slide_index
    dimensions: Tuple[float, float]  # (width, height)

    blocks: List[TextBlock] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    visual_elements: List[VisualElement] = field(default_factory=list)

    # Métadonnées PPTX
    notes: str = ""
    has_notes: bool = False

    @property
    def page_area(self) -> float:
        return self.dimensions[0] * self.dimensions[1]


@dataclass
class PdfPageFeatures:
    """Features extraites d'une page PDF pour le gating."""
    page_index: int
    drawings_count: int
    images_count: int
    text_blocks_count: int
    small_text_blocks_count: int  # < 200 chars
    long_paragraph_blocks_count: int
    avg_block_len: float
    text_dispersion: float  # Variance spatiale normalisée
    vector_density: float  # Ratio surface drawings / page
    largest_image_ratio: float  # Plus grande image / page
    connector_count: int


@dataclass
class PptxSlideFeatures:
    """Features extraites d'une slide PPTX pour le gating."""
    slide_index: int
    shape_count: int
    connector_count: int
    group_count: int
    text_shape_count: int
    picture_count: int
    chart_count: int
    table_count: int
    avg_text_len_per_shape: float
    small_boxes_ratio: float  # Ratio shapes < 200 chars
    notes_length: int
    largest_picture_ratio: float


@dataclass
class GatingDecision:
    """
    Résultat du Vision Gating v4.
    Toujours explicable avec scores et raisons.
    """
    index: int  # page_index or slide_index
    unit_id: str  # "PDF_PAGE_6", "PPTX_SLIDE_12"
    action: ExtractionAction
    vision_need_score: float  # VNS entre 0.0 et 1.0
    signals: VisionSignals = field(default_factory=VisionSignals)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "decision": self.action.value,
            "vision_need_score": round(self.vision_need_score, 2),
            "signals": {
                "RIS": self.signals.RIS,
                "VDS": self.signals.VDS,
                "TFS": self.signals.TFS,
                "SDS": self.signals.SDS,
                "VTS": self.signals.VTS,
            },
            "reasons": self.reasons
        }


# ---------- Vision extraction schema ----------

@dataclass
class VisionElement:
    """Élément extrait par Vision LLM."""
    id: str
    type: str              # "box", "label", "arrow", "group", "icon"
    text: str = ""
    bbox: Optional[Tuple[float, float, float, float]] = None  # normalized (0..1)


@dataclass
class VisionRelation:
    """Relation extraite par Vision LLM."""
    source_id: str
    target_id: str
    type: str              # "flows_to", "contains", "depends_on", ...
    evidence: str          # "arrow", "grouping", "alignment", "label_near_line"
    confidence: float = 0.0


@dataclass
class VisionUncertainty:
    """Incertitude déclarée par Vision LLM."""
    item: str
    reason: str


@dataclass
class VisionExtraction:
    """Résultat complet de l'extraction Vision."""
    kind: str  # "architecture_diagram", "process_workflow", "chart", ...
    elements: List[VisionElement] = field(default_factory=list)
    relations: List[VisionRelation] = field(default_factory=list)
    uncertainties: List[VisionUncertainty] = field(default_factory=list)
    raw_model_output: Optional[Dict[str, Any]] = None  # for debugging


# ---------- Page/Slide output ----------

@dataclass
class PageOrSlideOutput:
    """Sortie unifiée pour une page/slide."""
    index: int
    text_markdown: str
    text_json: Dict[str, Any]  # docling structured output
    gating: GatingDecision
    vision: Optional[VisionExtraction] = None
    quality_flags: List[str] = field(default_factory=list)


# ---------- Document output ----------

@dataclass
class DocumentOutput:
    """Sortie complète pour un document."""
    document_id: str
    source_path: str
    file_type: str  # "pdf" or "pptx"
    domain_context_name: str
    pages_or_slides: List[PageOrSlideOutput] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


# ---------- Core interfaces ----------

class TextExtractor:
    """Interface pour l'extraction structurelle (Docling)."""

    def extract_pdf(self, pdf_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Extrait le contenu d'un PDF.
        Returns: (markdown, json_struct)
        """
        raise NotImplementedError

    def extract_pptx(self, pptx_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Extrait le contenu d'un PPTX.
        Returns: (markdown, json_struct)
        """
        raise NotImplementedError

    def extract_to_units(self, file_path: str) -> List[VisionUnit]:
        """
        Extrait et retourne une liste de VisionUnit.
        Chaque unit correspond à une page/slide.
        """
        raise NotImplementedError


class GatingEngine:
    """Interface pour le Vision Gating v4."""

    def compute_signals(self, unit: VisionUnit) -> VisionSignals:
        """Calcule les 5 signaux pour une unit."""
        raise NotImplementedError

    def gate(
        self,
        unit: VisionUnit,
        domain_context: Optional[DomainContext] = None
    ) -> GatingDecision:
        """Décide si Vision est nécessaire pour cette unit."""
        raise NotImplementedError

    def gate_pdf(self, pdf_path: str) -> List[GatingDecision]:
        """Gate toutes les pages d'un PDF."""
        raise NotImplementedError

    def gate_pptx(self, pptx_path: str) -> List[GatingDecision]:
        """Gate toutes les slides d'un PPTX."""
        raise NotImplementedError


class VisionAnalyzer:
    """Interface pour l'analyse Vision LLM."""

    def analyze_image(
        self,
        image_bytes: bytes,
        domain_context: DomainContext,
        local_snippets: str,
        schema_version: str = "v1"
    ) -> VisionExtraction:
        """
        Analyse une image avec Vision LLM.
        Injecte le Domain Context pour guider l'interprétation.
        """
        raise NotImplementedError


class DoclingAdapter:
    """Adaptateur pour normaliser la sortie Docling vers VisionUnit."""

    def adapt_pdf_page(
        self,
        docling_output: Dict[str, Any],
        page_index: int
    ) -> VisionUnit:
        """Convertit une page Docling en VisionUnit."""
        raise NotImplementedError

    def adapt_pptx_slide(
        self,
        docling_output: Dict[str, Any],
        slide_index: int
    ) -> VisionUnit:
        """Convertit une slide Docling en VisionUnit."""
        raise NotImplementedError


# ---------- Default weights for Vision Gating v4 ----------

DEFAULT_GATING_WEIGHTS = {
    "RIS": 0.30,
    "VDS": 0.30,
    "TFS": 0.15,
    "SDS": 0.15,
    "VTS": 0.10
}

GATING_THRESHOLDS = {
    "VISION_REQUIRED": 0.60,
    "VISION_RECOMMENDED": 0.40,
}
