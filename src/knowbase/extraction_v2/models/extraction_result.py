"""
ExtractionResult pour Extraction V2.

Interface de sortie V2 vers OSMOSE.
Sortie bi-couche: full_text (compatible OSMOSE) + structure (pour futur/audit).

Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 1
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime

from knowbase.extraction_v2.models.gating import GatingDecision
from knowbase.extraction_v2.models.vision_output import VisionExtraction

# Import conditionnel pour eviter import circulaire
# DocContextFrame est importe dynamiquement dans from_dict()
TYPE_CHECKING = False
try:
    from typing import TYPE_CHECKING
except ImportError:
    pass

if TYPE_CHECKING:
    from knowbase.extraction_v2.context.models import DocContextFrame


@dataclass
class PageIndex:
    """
    Index de provenance pour mapper texte → page/slide.

    Permet de retracer l'origine de chaque portion de texte
    dans le full_text linéarisé.
    """
    # Index de la page/slide
    page_index: int

    # Offset de début dans full_text (caractères)
    start_offset: int

    # Offset de fin dans full_text (caractères)
    end_offset: int

    # Type de page (optionnel)
    page_type: Optional[str] = None  # "content", "title_slide", "diagram", etc.

    # Titre de la page (si disponible)
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "page_index": self.page_index,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "page_type": self.page_type,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageIndex":
        """Désérialise depuis un dictionnaire."""
        return cls(
            page_index=data["page_index"],
            start_offset=data["start_offset"],
            end_offset=data["end_offset"],
            page_type=data.get("page_type"),
            title=data.get("title"),
        )


@dataclass
class PageOutput:
    """
    Sortie pour une page/slide individuelle.

    Contient la structure complète + les résultats de gating et vision.
    """
    # Index de la page
    index: int

    # Texte markdown de la page
    text_markdown: str

    # Structure JSON complète (Docling output)
    text_json: Dict[str, Any] = field(default_factory=dict)

    # Décision de gating
    gating: Optional[GatingDecision] = None

    # Résultat Vision (si Vision a été exécutée)
    vision: Optional[VisionExtraction] = None

    # Texte Vision linéarisé pour OSMOSE (si Vision a été exécutée)
    vision_text: Optional[str] = None

    # Flags de qualité
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        result = {
            "index": self.index,
            "text_markdown": self.text_markdown,
            "text_json": self.text_json,
            "quality_flags": self.quality_flags,
        }
        if self.gating:
            result["gating"] = self.gating.to_dict()
        if self.vision:
            result["vision"] = self.vision.to_dict()
        if self.vision_text:
            result["vision_text"] = self.vision_text
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageOutput":
        """Désérialise depuis un dictionnaire."""
        gating = None
        if "gating" in data and data["gating"]:
            gating = GatingDecision.from_dict(data["gating"])

        vision = None
        if "vision" in data and data["vision"]:
            vision = VisionExtraction.from_dict(data["vision"])

        return cls(
            index=data["index"],
            text_markdown=data["text_markdown"],
            text_json=data.get("text_json", {}),
            gating=gating,
            vision=vision,
            vision_text=data.get("vision_text"),
            quality_flags=data.get("quality_flags", []),
        )


@dataclass
class DocumentStructure:
    """
    Structure complète du document.

    Préservée pour usage futur, audit, et UI.
    """
    # Pages/slides avec structure complète
    pages: List[PageOutput] = field(default_factory=list)

    # Métadonnées du document
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Statistiques
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "pages": [p.to_dict() for p in self.pages],
            "metadata": self.metadata,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentStructure":
        """Désérialise depuis un dictionnaire."""
        return cls(
            pages=[PageOutput.from_dict(p) for p in data.get("pages", [])],
            metadata=data.get("metadata", {}),
            stats=data.get("stats", {}),
        )


@dataclass
class ExtractionResult:
    """
    Interface de sortie V2 vers OSMOSE.

    Sortie bi-couche:
    - full_text: Texte linéarisé avec marqueurs structurels (pour OSMOSE)
    - structure: Structure complète préservée (pour futur, audit, UI)

    Marqueurs dans full_text:
    - [PAGE n | TYPE=xxx] : Début de page
    - [TITLE level=n] : Titre
    - [PARAGRAPH] : Paragraphe
    - [TABLE_START id=x]...[TABLE_END] : Table en Markdown
    - [VISUAL_ENRICHMENT id=x confidence=y]...[END_VISUAL_ENRICHMENT] : Vision

    Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md
    """

    # === Couche compatibilité (obligatoire) - consommée par OSMOSE ===
    full_text: str  # Texte linéarisé avec marqueurs structurels

    # === Couche structure enrichie (pour futur, audit, UI) ===
    structure: DocumentStructure  # Structure complète préservée

    # === Index de provenance ===
    page_index: List[PageIndex]  # Mapping offsets texte → pages/slides

    # === Métadonnées du document ===
    document_id: str
    source_path: str
    file_type: str  # "pdf", "pptx", "docx", "xlsx"

    # === Contexte d'extraction ===
    domain_context_name: str = "default"
    extraction_timestamp: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    # === Décisions de gating (pour audit) ===
    gating_decisions: List[GatingDecision] = field(default_factory=list)

    # === Résultats Vision (pour ceux qui ont eu Vision) ===
    vision_results: List[VisionExtraction] = field(default_factory=list)

    # === Contexte documentaire (ADR_ASSERTION_AWARE_KG) ===
    # Contient les marqueurs de version/edition et la classification du document
    doc_context: Optional[Any] = None  # Type: DocContextFrame (import dynamique)

    # === Statistiques globales ===
    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calcule les statistiques si non fournies."""
        if not self.stats:
            self.stats = self._compute_stats()

    def _compute_stats(self) -> Dict[str, Any]:
        """Calcule les statistiques du résultat."""
        total_pages = len(self.structure.pages)
        pages_with_vision = sum(
            1 for p in self.structure.pages if p.vision is not None
        )
        vision_required = sum(
            1 for d in self.gating_decisions
            if d.action.value == "vision_required"
        )
        vision_recommended = sum(
            1 for d in self.gating_decisions
            if d.action.value == "vision_recommended"
        )

        return {
            "total_pages": total_pages,
            "pages_with_vision": pages_with_vision,
            "vision_required_count": vision_required,
            "vision_recommended_count": vision_recommended,
            "full_text_length": len(self.full_text),
            "file_type": self.file_type,
        }

    @property
    def total_pages(self) -> int:
        """Nombre total de pages."""
        return len(self.structure.pages)

    @property
    def pages_with_vision(self) -> int:
        """Nombre de pages ayant reçu Vision."""
        return sum(1 for p in self.structure.pages if p.vision is not None)

    def get_page_at_offset(self, offset: int) -> Optional[int]:
        """
        Retourne l'index de page pour un offset dans full_text.

        Args:
            offset: Position dans full_text

        Returns:
            Index de la page ou None si hors limites
        """
        for pi in self.page_index:
            if pi.start_offset <= offset < pi.end_offset:
                return pi.page_index
        return None

    def to_dict(self) -> Dict[str, Any]:
        """
        Sérialise en dictionnaire.

        Format compatible avec le cache versionné.
        """
        result = {
            "document_id": self.document_id,
            "source_path": self.source_path,
            "file_type": self.file_type,
            "domain_context_name": self.domain_context_name,
            "extraction_timestamp": self.extraction_timestamp,
            "full_text": self.full_text,
            "structure": self.structure.to_dict(),
            "page_index": [pi.to_dict() for pi in self.page_index],
            "gating_decisions": [gd.to_dict() for gd in self.gating_decisions],
            "vision_results": [vr.to_dict() for vr in self.vision_results],
            "stats": self.stats,
        }
        # Ajouter doc_context si present
        if self.doc_context is not None:
            result["doc_context"] = self.doc_context.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionResult":
        """Désérialise depuis un dictionnaire."""
        # Import dynamique pour eviter import circulaire
        doc_context = None
        if "doc_context" in data and data["doc_context"]:
            from knowbase.extraction_v2.context.models import DocContextFrame
            doc_context = DocContextFrame.from_dict(data["doc_context"])

        return cls(
            document_id=data["document_id"],
            source_path=data["source_path"],
            file_type=data["file_type"],
            domain_context_name=data.get("domain_context_name", "default"),
            extraction_timestamp=data.get(
                "extraction_timestamp",
                datetime.utcnow().isoformat()
            ),
            full_text=data["full_text"],
            structure=DocumentStructure.from_dict(data["structure"]),
            page_index=[PageIndex.from_dict(pi) for pi in data.get("page_index", [])],
            gating_decisions=[
                GatingDecision.from_dict(gd)
                for gd in data.get("gating_decisions", [])
            ],
            vision_results=[
                VisionExtraction.from_dict(vr)
                for vr in data.get("vision_results", [])
            ],
            doc_context=doc_context,
            stats=data.get("stats", {}),
        )

    def __repr__(self) -> str:
        return (
            f"ExtractionResult({self.document_id}: {self.total_pages} pages, "
            f"{self.pages_with_vision} with vision, "
            f"{len(self.full_text)} chars)"
        )
