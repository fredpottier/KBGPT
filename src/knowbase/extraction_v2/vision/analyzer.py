"""
VisionAnalyzer - Analyse d'images via GPT-4o Vision.

Extrait les elements structurels et relations depuis les diagrammes.

Specification: VISION_PROMPT_CANONICAL.md
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import logging
import json
import base64
import io

from knowbase.extraction_v2.models import (
    VisionExtraction,
    VisionElement,
    VisionRelation,
    VisionAmbiguity,
    VisionUncertainty,
    VisionDomainContext,
)
from knowbase.extraction_v2.vision.prompts import (
    VISION_SYSTEM_PROMPT,
    get_vision_messages,
)

logger = logging.getLogger(__name__)


# Types d'images supportes
SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "webp"}


class VisionAnalyzer:
    """
    Analyseur d'images via GPT-4o Vision.

    Extrait les elements structurels (boxes, labels, arrows)
    et les relations visuelles depuis les diagrammes.

    Principes:
    - Vision OBSERVE et DECRIT, ne raisonne pas
    - Toute relation doit avoir une evidence visuelle
    - Les ambiguites sont declarees, jamais resolues implicitement
    - Sortie JSON stricte conforme au schema

    Usage:
        >>> analyzer = VisionAnalyzer()
        >>> extraction = await analyzer.analyze_image(
        ...     image_bytes,
        ...     domain_context=sap_context,
        ...     local_snippets="Title: Architecture Overview"
        ... )
        >>> print(extraction.elements)
        >>> print(extraction.relations)
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        """
        Initialise l'analyseur Vision.

        Args:
            model: Modele Vision a utiliser (gpt-4o, gpt-4o-mini)
            temperature: Temperature pour la generation
            max_tokens: Nombre max de tokens en sortie
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None
        self._initialized = False

        logger.info(
            f"[VisionAnalyzer] Initialized with model={model}, "
            f"temperature={temperature}"
        )

    async def initialize(self) -> None:
        """
        Initialise le client OpenAI.

        Appele automatiquement lors du premier appel.
        """
        if self._initialized:
            return

        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI()
            self._initialized = True
            logger.info("[VisionAnalyzer] OpenAI client initialized")
        except ImportError as e:
            logger.error(f"[VisionAnalyzer] Failed to import OpenAI: {e}")
            raise ImportError(
                "openai n'est pas installe. Installer avec: pip install openai>=1.0.0"
            ) from e

    async def analyze_image(
        self,
        image_bytes: bytes,
        domain_context: Optional[VisionDomainContext] = None,
        local_snippets: str = "",
        page_index: Optional[int] = None,
        image_format: str = "png",
    ) -> VisionExtraction:
        """
        Analyse une image avec Vision LLM.

        Args:
            image_bytes: Image en bytes (PNG, JPEG, etc.)
            domain_context: Contexte metier pour guider l'interpretation
            local_snippets: Texte local extrait de la meme page
            page_index: Index de la page source
            image_format: Format de l'image (png, jpeg, etc.)

        Returns:
            VisionExtraction avec elements et relations
        """
        # Initialiser si necessaire
        if not self._initialized:
            await self.initialize()

        # Encoder l'image en base64
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        # Construire les messages
        messages = get_vision_messages(
            domain_context=domain_context,
            local_snippets=local_snippets,
            image_base64=image_base64,
        )

        # Ajuster le MIME type selon le format
        mime_type = f"image/{image_format}"
        if image_format in ("jpg", "jpeg"):
            mime_type = "image/jpeg"
        messages[1]["content"][0]["image_url"]["url"] = f"data:{mime_type};base64,{image_base64}"

        logger.debug(f"[VisionAnalyzer] Calling {self.model} with {len(image_bytes)} bytes")

        try:
            # Appel API Vision
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )

            # Extraire la reponse
            content = response.choices[0].message.content

            # Parser le JSON
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"[VisionAnalyzer] JSON parse error: {e}")
                logger.debug(f"[VisionAnalyzer] Raw content: {content[:500]}")
                # Retourner une extraction vide avec erreur
                return VisionExtraction(
                    kind="parse_error",
                    elements=[],
                    relations=[],
                    page_index=page_index,
                    confidence=0.0,
                    uncertainties=[
                        VisionUncertainty(
                            item="json_parsing",
                            reason=f"Failed to parse LLM response: {str(e)}",
                        )
                    ],
                )

            # Convertir en VisionExtraction
            extraction = self._parse_vision_response(result, page_index)

            logger.info(
                f"[VisionAnalyzer] Extracted {len(extraction.elements)} elements, "
                f"{len(extraction.relations)} relations from page {page_index}"
            )

            return extraction

        except Exception as e:
            logger.error(f"[VisionAnalyzer] API call failed: {e}")
            return VisionExtraction(
                kind="api_error",
                elements=[],
                relations=[],
                page_index=page_index,
                confidence=0.0,
                uncertainties=[
                    VisionUncertainty(
                        item="api_call",
                        reason=f"Vision API call failed: {str(e)}",
                    )
                ],
            )

    def _parse_vision_response(
        self,
        response: Dict[str, Any],
        page_index: Optional[int] = None,
    ) -> VisionExtraction:
        """
        Parse la reponse JSON du LLM en VisionExtraction.

        Args:
            response: Reponse JSON du LLM
            page_index: Index de la page source

        Returns:
            VisionExtraction
        """
        # Diagram type
        kind = response.get("diagram_type", "unknown")

        # Elements
        elements = []
        for elem_data in response.get("elements", []):
            elem = VisionElement(
                id=elem_data.get("id", f"elem_{len(elements)}"),
                type=elem_data.get("type", "other"),
                text=elem_data.get("text", ""),
                confidence=elem_data.get("confidence", 0.5),
            )
            elements.append(elem)

        # Relations
        relations = []
        for rel_data in response.get("relations", []):
            rel = VisionRelation(
                source_id=rel_data.get("source_id", ""),
                target_id=rel_data.get("target_id", ""),
                type=rel_data.get("relation_type", "other"),
                evidence=rel_data.get("evidence", ""),
                confidence=rel_data.get("confidence", 0.5),
            )
            relations.append(rel)

        # Ambiguites
        ambiguities = []
        for amb_data in response.get("ambiguities", []):
            amb = VisionAmbiguity(
                term=amb_data.get("term", ""),
                possible_interpretations=amb_data.get("possible_interpretations", []),
                reason=amb_data.get("reason", ""),
            )
            ambiguities.append(amb)

        # Incertitudes
        uncertainties = []
        for unc_data in response.get("uncertainties", []):
            unc = VisionUncertainty(
                item=unc_data.get("item", ""),
                reason=unc_data.get("reason", ""),
            )
            uncertainties.append(unc)

        # Calculer la confiance moyenne
        if elements:
            avg_confidence = sum(e.confidence for e in elements) / len(elements)
        else:
            avg_confidence = 0.0

        return VisionExtraction(
            kind=kind,
            elements=elements,
            relations=relations,
            page_index=page_index,
            confidence=round(avg_confidence, 2),
            ambiguities=ambiguities,
            uncertainties=uncertainties,
        )

    async def analyze_page(
        self,
        file_path: str,
        page_index: int,
        domain_context: Optional[VisionDomainContext] = None,
        local_snippets: str = "",
        resolution: int = 150,
    ) -> VisionExtraction:
        """
        Analyse une page/slide d'un document.

        Args:
            file_path: Chemin vers le document
            page_index: Index de la page a analyser
            domain_context: Contexte metier
            local_snippets: Texte local
            resolution: Resolution pour le rendu (DPI pour PDF)

        Returns:
            VisionExtraction
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        # Rendre la page en image
        if ext == ".pdf":
            image_bytes = await self._render_pdf_page(file_path, page_index, resolution)
            image_format = "png"
        elif ext == ".pptx":
            image_bytes = await self._render_pptx_slide(file_path, page_index, resolution)
            image_format = "png"
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            # L'image est deja le fichier
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            image_format = ext.lstrip(".")
        else:
            logger.warning(f"[VisionAnalyzer] Unsupported format: {ext}")
            return VisionExtraction(
                kind="unsupported_format",
                elements=[],
                relations=[],
                page_index=page_index,
                confidence=0.0,
                uncertainties=[
                    VisionUncertainty(
                        item="format",
                        reason=f"Unsupported document format: {ext}",
                    )
                ],
            )

        if not image_bytes:
            return VisionExtraction(
                kind="render_error",
                elements=[],
                relations=[],
                page_index=page_index,
                confidence=0.0,
                uncertainties=[
                    VisionUncertainty(
                        item="render",
                        reason=f"Failed to render page {page_index}",
                    )
                ],
            )

        # Analyser l'image
        return await self.analyze_image(
            image_bytes=image_bytes,
            domain_context=domain_context,
            local_snippets=local_snippets,
            page_index=page_index,
            image_format=image_format,
        )

    async def _render_pdf_page(
        self,
        file_path: str,
        page_index: int,
        resolution: int = 150,
    ) -> Optional[bytes]:
        """
        Rend une page PDF en image PNG.

        Args:
            file_path: Chemin vers le PDF
            page_index: Index de la page
            resolution: Resolution en DPI

        Returns:
            Image en bytes (PNG) ou None si erreur
        """
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            if page_index >= len(doc):
                logger.warning(f"[VisionAnalyzer] Page {page_index} hors limites")
                doc.close()
                return None

            page = doc[page_index]

            # Calculer le zoom
            zoom = resolution / 72.0
            matrix = fitz.Matrix(zoom, zoom)

            # Rendre en pixmap
            pix = page.get_pixmap(matrix=matrix)

            # Convertir en PNG bytes
            png_bytes = pix.tobytes("png")

            doc.close()

            logger.debug(
                f"[VisionAnalyzer] Rendered PDF page {page_index} "
                f"({pix.width}x{pix.height})"
            )

            return png_bytes

        except ImportError:
            logger.error("[VisionAnalyzer] PyMuPDF non installe")
            return None
        except Exception as e:
            logger.error(f"[VisionAnalyzer] PDF render error: {e}")
            return None

    async def _render_pptx_slide(
        self,
        file_path: str,
        slide_index: int,
        resolution: int = 150,
    ) -> Optional[bytes]:
        """
        Rend une slide PPTX en image PNG.

        Note: Utilise une approche simplifiee basee sur python-pptx + PIL.
        Pour un rendu plus fidele, utiliser un service externe ou LibreOffice.

        Args:
            file_path: Chemin vers le PPTX
            slide_index: Index de la slide
            resolution: Resolution cible

        Returns:
            Image en bytes (PNG) ou None si erreur
        """
        try:
            from pptx import Presentation
            from PIL import Image

            prs = Presentation(file_path)

            if slide_index >= len(prs.slides):
                logger.warning(f"[VisionAnalyzer] Slide {slide_index} hors limites")
                return None

            # Pour PPTX, on essaie d'utiliser une image exportee si disponible
            # Sinon on cree une image placeholder avec les dimensions
            slide_width = prs.slide_width
            slide_height = prs.slide_height

            # Convertir EMU en pixels (914400 EMU = 1 inch)
            width_px = int(slide_width / 914400 * resolution)
            height_px = int(slide_height / 914400 * resolution)

            # Creer une image placeholder blanche
            # Note: Pour un vrai rendu, il faudrait utiliser un service externe
            # comme LibreOffice ou un convertisseur PPTX->PNG
            img = Image.new("RGB", (width_px, height_px), color=(255, 255, 255))

            # Ajouter un texte indicatif
            try:
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(img)
                text = f"PPTX Slide {slide_index}\n(Actual rendering requires external service)"
                draw.text((10, 10), text, fill=(128, 128, 128))
            except Exception:
                pass

            # Convertir en bytes
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)

            logger.debug(
                f"[VisionAnalyzer] Created PPTX placeholder for slide {slide_index} "
                f"({width_px}x{height_px})"
            )

            return buffer.read()

        except ImportError:
            logger.error("[VisionAnalyzer] python-pptx ou PIL non installe")
            return None
        except Exception as e:
            logger.error(f"[VisionAnalyzer] PPTX render error: {e}")
            return None

    async def render_page_image(
        self,
        file_path: str,
        page_index: int,
        resolution: int = 150,
    ) -> Optional[bytes]:
        """
        Rend une page/slide en image PNG.

        Méthode publique pour usage externe (VisionSemanticReader).

        Args:
            file_path: Chemin vers le document (PDF, PPTX, ou image)
            page_index: Index de la page/slide
            resolution: Resolution en DPI

        Returns:
            Image en bytes (PNG/JPEG) ou None si erreur
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            return await self._render_pdf_page(file_path, page_index, resolution)
        elif ext == ".pptx":
            return await self._render_pptx_slide(file_path, page_index, resolution)
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            # L'image est le fichier lui-même
            try:
                with open(file_path, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"[VisionAnalyzer] Image read error: {e}")
                return None
        else:
            logger.warning(f"[VisionAnalyzer] Unsupported format for rendering: {ext}")
            return None

    async def analyze_unit(
        self,
        unit,
        image_bytes: Optional[bytes] = None,
        domain_context: Optional[VisionDomainContext] = None,
    ) -> VisionExtraction:
        """
        Analyse une VisionUnit.

        Args:
            unit: VisionUnit a analyser
            image_bytes: Image pre-rendue (optionnel)
            domain_context: Contexte metier

        Returns:
            VisionExtraction
        """
        # Construire les local snippets depuis les blocs
        snippets = []
        if unit.title:
            snippets.append(f"Title: {unit.title}")

        for block in unit.blocks[:10]:  # Limiter a 10 blocs
            if block.text and len(block.text) > 5:
                snippets.append(block.text[:200])

        local_snippets = "\n".join(snippets)

        # Si image fournie, l'utiliser
        if image_bytes:
            return await self.analyze_image(
                image_bytes=image_bytes,
                domain_context=domain_context,
                local_snippets=local_snippets,
                page_index=unit.index,
            )

        # Sinon, retourner une extraction vide
        return VisionExtraction(
            kind="no_image",
            elements=[],
            relations=[],
            page_index=unit.index,
            confidence=0.0,
            uncertainties=[
                VisionUncertainty(
                    item="image",
                    reason="No image provided for analysis",
                )
            ],
        )


__all__ = ["VisionAnalyzer"]
