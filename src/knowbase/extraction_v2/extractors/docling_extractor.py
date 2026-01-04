"""
DoclingExtractor - Extracteur unifié basé sur Docling.

Supporte tous les formats Office: PDF, DOCX, PPTX, XLSX.

Architecture:
- Docling comme moteur d'extraction unique
- Conversion automatique en VisionUnits normalisés
- Support des images raster et dessins vectoriels
- Extraction tables structurées

Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import logging
import base64
import io

from knowbase.extraction_v2.models import VisionUnit
from knowbase.extraction_v2.models.elements import (
    BoundingBox,
    TextBlock,
    VisualElement,
    TableData,
)

logger = logging.getLogger(__name__)

# Formats supportés par Docling
SUPPORTED_FORMATS = {
    "pdf": "PDF",
    "docx": "DOCX",
    "pptx": "PPTX",
    "xlsx": "XLSX",
    "html": "HTML",
    "md": "Markdown",
    "png": "Image",
    "jpg": "Image",
    "jpeg": "Image",
    "tiff": "Image",
    "bmp": "Image",
    "webp": "Image",
}

# Dimensions par défaut (Letter pour PDF, 16:9 pour PPTX)
DEFAULT_DIMENSIONS = {
    "PDF": (612, 792),      # Letter 8.5x11 in points
    "DOCX": (612, 792),     # Letter
    "PPTX": (960, 540),     # 16:9 HD
    "XLSX": (612, 792),     # Letter
    "Image": (1920, 1080),  # HD
}


class DoclingExtractor:
    """
    Extracteur unifié basé sur Docling.

    Supporte:
    - PDF (documents, présentations scannées)
    - DOCX (documents Word)
    - PPTX (présentations PowerPoint)
    - XLSX (tableurs Excel)
    - Images (PNG, JPEG, etc. via OCR)

    Usage:
        >>> extractor = DoclingExtractor()
        >>> await extractor.initialize()
        >>> units = await extractor.extract_to_units("/path/to/doc.pdf")
        >>> for unit in units:
        ...     print(f"Page {unit.index}: {unit.text_blocks_count} blocks")

    Configuration:
        - ocr_enabled: Active l'OCR pour les images/scans
        - table_mode: Mode d'extraction des tables
        - image_resolution_scale: Facteur de résolution pour les images
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_mode: str = "accurate",
        image_resolution_scale: float = 2.0,
    ):
        """
        Initialise l'extracteur Docling.

        Args:
            ocr_enabled: Active l'OCR pour images/scans
            table_mode: Mode extraction tables ("fast" ou "accurate")
            image_resolution_scale: Facteur résolution pour images
        """
        self.ocr_enabled = ocr_enabled
        self.table_mode = table_mode
        self.image_resolution_scale = image_resolution_scale

        self._converter = None
        self._initialized = False

        logger.info(
            f"[DoclingExtractor] Created: ocr={ocr_enabled}, "
            f"table_mode={table_mode}, scale={image_resolution_scale}"
        )

    @property
    def is_available(self) -> bool:
        """Vérifie si Docling est disponible."""
        try:
            import docling
            return True
        except ImportError:
            return False

    async def initialize(self) -> None:
        """
        Initialise le convertisseur Docling.

        Charge les modèles nécessaires (peut prendre du temps au premier appel).

        Raises:
            ImportError: Si Docling n'est pas installé
            RuntimeError: Si l'initialisation échoue
        """
        if self._initialized:
            return

        if not self.is_available:
            raise ImportError(
                "Docling n'est pas installé. "
                "Installer avec: pip install docling>=2.14.0\n"
                "Voir: https://github.com/DS4SD/docling"
            )

        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

            # Configuration du pipeline PDF
            pipeline_options = PdfPipelineOptions(
                do_ocr=self.ocr_enabled,
                do_table_structure=True,
            )

            # Wrapper PdfFormatOption requis par Docling 2.66+
            pdf_format_option = PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )

            # Créer le convertisseur
            self._converter = DocumentConverter(
                allowed_formats=[
                    InputFormat.PDF,
                    InputFormat.DOCX,
                    InputFormat.PPTX,
                    InputFormat.XLSX,
                    InputFormat.HTML,
                    InputFormat.MD,
                    InputFormat.IMAGE,
                ],
                format_options={
                    InputFormat.PDF: pdf_format_option,
                },
            )

            self._initialized = True
            logger.info("[DoclingExtractor] ✅ Docling converter initialized")

        except Exception as e:
            logger.error(f"[DoclingExtractor] ❌ Initialization failed: {e}")
            raise RuntimeError(f"Failed to initialize Docling: {e}") from e

    def _detect_format(self, file_path: str) -> str:
        """
        Détecte le format d'un fichier.

        Args:
            file_path: Chemin du fichier

        Returns:
            Format détecté ("PDF", "PPTX", etc.)

        Raises:
            ValueError: Si format non supporté
        """
        ext = Path(file_path).suffix.lower().lstrip(".")

        if ext not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Format '{ext}' non supporté. "
                f"Formats valides: {list(SUPPORTED_FORMATS.keys())}"
            )

        return SUPPORTED_FORMATS[ext]

    async def extract_to_units(
        self,
        file_path: str,
        include_raw_output: bool = False,
    ) -> List[VisionUnit]:
        """
        Extrait un document et retourne une liste de VisionUnits.

        Chaque VisionUnit correspond à une page/slide.

        Args:
            file_path: Chemin vers le document
            include_raw_output: Inclure la sortie brute Docling pour debug

        Returns:
            Liste de VisionUnits (une par page/slide)

        Raises:
            ImportError: Si Docling n'est pas installé
            FileNotFoundError: Si le fichier n'existe pas
            ValueError: Si format non supporté
        """
        # Vérifier initialisation
        if not self._initialized:
            await self.initialize()

        # Vérifier fichier
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier non trouvé: {file_path}")

        # Détecter format
        doc_format = self._detect_format(file_path)
        logger.info(f"[DoclingExtractor] Processing {doc_format}: {path.name}")

        try:
            # Convertir le document
            result = self._converter.convert(str(path))

            # Extraire les pages en VisionUnits
            units = self._convert_to_units(result, doc_format, include_raw_output)

            logger.info(
                f"[DoclingExtractor] ✅ Extracted {len(units)} pages from {path.name}"
            )
            return units

        except Exception as e:
            logger.error(f"[DoclingExtractor] ❌ Extraction failed: {e}")
            raise

    def _convert_to_units(
        self,
        docling_result: Any,
        doc_format: str,
        include_raw: bool,
    ) -> List[VisionUnit]:
        """
        Convertit le résultat Docling en VisionUnits.

        Args:
            docling_result: Résultat de docling.convert()
            doc_format: Format du document
            include_raw: Inclure sortie brute

        Returns:
            Liste de VisionUnits
        """
        from docling.datamodel.document import DoclingDocument

        doc: DoclingDocument = docling_result.document
        units = []

        # Dimensions par défaut pour ce format
        default_dims = DEFAULT_DIMENSIONS.get(doc_format, (612, 792))

        # Parcourir les pages (Docling 2.66+ utilise un dict avec clés 1-indexed)
        if hasattr(doc, 'pages') and isinstance(doc.pages, dict):
            page_keys = sorted(doc.pages.keys())
        else:
            page_keys = list(range(1, 2))  # Fallback: 1 page

        for page_num in page_keys:
            # Index 0-based pour VisionUnit
            page_idx = page_num - 1 if isinstance(page_num, int) else 0

            # Créer l'ID de l'unité
            unit_id = f"{doc_format}_PAGE_{page_idx}"

            # Dimensions de la page (si disponible)
            dimensions = default_dims
            if hasattr(doc, 'pages') and page_num in doc.pages:
                page = doc.pages[page_num]
                if hasattr(page, 'size'):
                    dimensions = (page.size.width, page.size.height)

            # Extraire les blocs de texte (page_num est 1-indexed comme dans Docling)
            blocks = self._extract_text_blocks(doc, page_num)

            # Extraire les tables
            tables = self._extract_tables(doc, page_num)

            # Extraire les éléments visuels
            visual_elements = self._extract_visual_elements(doc, page_num)

            # Titre de la page (si détecté)
            title = self._detect_title(blocks)

            # Créer la VisionUnit
            unit = VisionUnit(
                id=unit_id,
                format=doc_format,
                index=page_idx,
                dimensions=dimensions,
                blocks=blocks,
                tables=tables,
                visual_elements=visual_elements,
                title=title,
                raw_docling_output=docling_result if include_raw else None,
            )

            units.append(unit)

        return units

    def _extract_text_blocks(
        self,
        doc: Any,
        page_num: int,
    ) -> List[TextBlock]:
        """
        Extrait les blocs de texte d'une page.

        Args:
            doc: Document Docling
            page_num: Numéro de page (1-indexed, comme Docling)

        Returns:
            Liste de TextBlocks
        """
        blocks = []

        # Accéder aux éléments de texte
        if hasattr(doc, 'texts'):
            for text_item in doc.texts:
                # Filtrer par page (page_no est 1-indexed dans Docling)
                if hasattr(text_item, 'prov') and text_item.prov:
                    item_page = text_item.prov[0].page_no if text_item.prov else 0
                    if item_page != page_num:
                        continue

                # Déterminer le type
                block_type = "paragraph"
                level = 0
                if hasattr(text_item, 'label'):
                    label = str(text_item.label).lower()
                    if "heading" in label or "title" in label:
                        block_type = "heading"
                        # Extraire le niveau si disponible
                        import re
                        level_match = re.search(r'\d+', label)
                        level = int(level_match.group()) if level_match else 1
                    elif "list" in label:
                        block_type = "list_item"
                    elif "caption" in label:
                        block_type = "caption"

                # Extraire la bounding box
                bbox = None
                if hasattr(text_item, 'prov') and text_item.prov:
                    prov = text_item.prov[0]
                    if hasattr(prov, 'bbox'):
                        b = prov.bbox
                        bbox = BoundingBox(
                            x=b.l,
                            y=b.t,
                            width=b.r - b.l,
                            height=b.b - b.t,
                            normalized=False,
                        )

                # Créer le bloc
                block = TextBlock(
                    type=block_type,
                    text=str(text_item.text) if hasattr(text_item, 'text') else "",
                    bbox=bbox,
                    level=level,
                    block_id=f"block_{page_num}_{len(blocks)}",
                )
                blocks.append(block)

        return blocks

    def _extract_tables(
        self,
        doc: Any,
        page_num: int,
    ) -> List[TableData]:
        """
        Extrait les tables d'une page.

        Args:
            doc: Document Docling
            page_num: Numéro de page (1-indexed, comme Docling)

        Returns:
            Liste de TableData
        """
        tables = []

        if hasattr(doc, 'tables'):
            for idx, table_item in enumerate(doc.tables):
                # Filtrer par page (page_no est 1-indexed dans Docling)
                if hasattr(table_item, 'prov') and table_item.prov:
                    item_page = table_item.prov[0].page_no if table_item.prov else 0
                    if item_page != page_num:
                        continue

                # Extraire les données du tableau
                cells = []
                headers = []

                if hasattr(table_item, 'data') and hasattr(table_item.data, 'table_cells'):
                    # Organiser par rows
                    rows_dict = {}
                    for cell in table_item.data.table_cells:
                        # Docling 2.66+: row_span peut être int ou range
                        if hasattr(cell, 'row_span'):
                            rs = cell.row_span
                            row_idx = rs.start if hasattr(rs, 'start') else int(rs)
                        else:
                            row_idx = 0
                        if row_idx not in rows_dict:
                            rows_dict[row_idx] = []
                        rows_dict[row_idx].append(str(cell.text))

                    # Convertir en liste de listes
                    for row_idx in sorted(rows_dict.keys()):
                        if row_idx == 0:
                            headers = rows_dict[row_idx]
                        else:
                            cells.append(rows_dict[row_idx])

                # Bounding box
                bbox = None
                if hasattr(table_item, 'prov') and table_item.prov:
                    prov = table_item.prov[0]
                    if hasattr(prov, 'bbox'):
                        b = prov.bbox
                        bbox = BoundingBox(
                            x=b.l,
                            y=b.t,
                            width=b.r - b.l,
                            height=b.b - b.t,
                            normalized=False,
                        )

                table = TableData(
                    table_id=f"table_{page_num}_{idx}",
                    bbox=bbox,
                    num_rows=len(cells) + (1 if headers else 0),
                    num_cols=len(headers) if headers else (len(cells[0]) if cells else 0),
                    cells=cells,
                    headers=headers,
                    is_structured=True,
                )
                tables.append(table)

        return tables

    def _extract_visual_elements(
        self,
        doc: Any,
        page_num: int,
    ) -> List[VisualElement]:
        """
        Extrait les éléments visuels d'une page.

        Args:
            doc: Document Docling
            page_num: Numéro de page (1-indexed, comme Docling)

        Returns:
            Liste de VisualElements
        """
        elements = []

        # Extraire les images/figures
        if hasattr(doc, 'pictures'):
            for idx, pic in enumerate(doc.pictures):
                # Filtrer par page (page_no est 1-indexed dans Docling)
                if hasattr(pic, 'prov') and pic.prov:
                    item_page = pic.prov[0].page_no if pic.prov else 0
                    if item_page != page_num:
                        continue

                # Bounding box
                bbox = BoundingBox(x=0, y=0, width=0.5, height=0.5, normalized=True)
                if hasattr(pic, 'prov') and pic.prov:
                    prov = pic.prov[0]
                    if hasattr(prov, 'bbox'):
                        b = prov.bbox
                        bbox = BoundingBox(
                            x=b.l,
                            y=b.t,
                            width=b.r - b.l,
                            height=b.b - b.t,
                            normalized=False,
                        )

                element = VisualElement(
                    kind="raster_image",
                    bbox=bbox,
                    element_id=f"image_{page_num}_{idx}",
                    metadata={"source": "docling"},
                )
                elements.append(element)

        # Note: Les shapes vectoriels dépendent du format et de la version Docling
        # Fallback VDS sera utilisé si nécessaire (Phase 2.6)

        return elements

    def _detect_title(self, blocks: List[TextBlock]) -> Optional[str]:
        """
        Détecte le titre de la page.

        Args:
            blocks: Blocs de texte de la page

        Returns:
            Titre si trouvé, None sinon
        """
        for block in blocks:
            if block.is_heading and block.level <= 2:
                return block.text[:200]  # Limite à 200 chars
        return None

    async def extract_document(
        self,
        file_path: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Extrait un document et retourne (markdown, json_struct).

        Méthode alternative pour obtenir directement le markdown.

        Args:
            file_path: Chemin vers le document

        Returns:
            Tuple (markdown_text, json_structure)
        """
        if not self._initialized:
            await self.initialize()

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier non trouvé: {file_path}")

        result = self._converter.convert(str(path))

        # Exporter en markdown
        markdown = result.document.export_to_markdown()

        # Exporter en JSON
        json_struct = result.document.export_to_dict()

        return markdown, json_struct

    def get_supported_formats(self) -> List[str]:
        """Retourne la liste des formats supportés."""
        return list(SUPPORTED_FORMATS.keys())

    def is_format_supported(self, file_path: str) -> bool:
        """Vérifie si le format est supporté."""
        try:
            self._detect_format(file_path)
            return True
        except ValueError:
            return False


__all__ = ["DoclingExtractor", "SUPPORTED_FORMATS"]
