"""
VisionSemanticReader - Lecture sémantique des pages visuelles.

Produit du TEXTE exploitable pour Pass 1 au lieu d'éléments géométriques.

Spec: doc/ongoing/SPEC_VISION_SEMANTIC_INTEGRATION.md

Invariants:
- I1: Jamais de texte vide en sortie
- I4: Traçabilité origine obligatoire (TextOrigin)
- I5: Texte descriptif uniquement, pas d'assertions pré-promues
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from knowbase.structural.models import TextOrigin, VisionFailureReason

logger = logging.getLogger(__name__)

# Version du prompt (pour cache/replay)
PROMPT_VERSION = "v1.0"


@dataclass
class VisionSemanticResult:
    """
    Résultat du Vision Semantic Reader.

    Spec: SPEC_VISION_SEMANTIC_INTEGRATION.md
    """
    page_no: int

    # TEXTE PRINCIPAL (obligatoire, jamais vide - Invariant I1)
    semantic_text: str
    text_origin: TextOrigin

    # Métadonnées audit
    diagram_type: Optional[str] = None
    confidence: float = 0.0
    key_entities: List[str] = field(default_factory=list)

    # Traçabilité (pour cache/replay)
    model: str = "gpt-4o"
    prompt_version: str = PROMPT_VERSION
    image_hash: str = ""

    # Optionnel: hints pour Pass 1 (jamais promues directement - Invariant I5)
    candidate_hints: Optional[List[str]] = None

    # En cas d'échec partiel
    failure_reason: Optional[VisionFailureReason] = None


# Prompt système pour Vision Semantic Reader
VISION_SEMANTIC_SYSTEM_PROMPT = """Tu es un expert en analyse de documents techniques.
Ta tâche : décrire le contenu visuel de manière FACTUELLE et OBSERVABLE.

RÈGLES:
- Décris ce que tu VOIS, pas ce que tu INTERPRÈTES
- 2-8 phrases maximum
- Identifie les entités principales (noms, labels visibles)
- Décris les relations visuelles (flèches, connexions, groupes)
- N'invente RIEN qui n'est pas visible sur l'image

ÉVITE:
- "Ceci représente officiellement..."
- "L'architecture cible est..."
- Toute affirmation normative non visible
- Les suppositions sur ce qui n'est pas clairement visible

FORMAT DE RÉPONSE (JSON):
{
  "diagram_type": "architecture_diagram|flowchart|table|slide|form|other",
  "description": "Description factuelle en 2-8 phrases",
  "key_entities": ["entité1", "entité2", ...],
  "confidence": 0.0-1.0
}
"""

VISION_SEMANTIC_USER_PROMPT = """Analyse cette page de document.

Décris le contenu visuel de manière factuelle :
- Quel type de visuel (diagramme, tableau, schéma, slide, formulaire) ?
- Quelles entités sont visibles (labels, noms, composants) ?
- Quelles relations sont montrées (flèches, liens, hiérarchies) ?

Réponds en JSON comme spécifié."""


class VisionSemanticReader:
    """
    Lecteur sémantique pour pages visuelles.

    Produit du TEXTE exploitable pour Pass 1 au lieu d'éléments géométriques.

    Fallback Strategy (3 tiers):
    1. GPT-4o Vision → texte sémantique
    2. Retry (1x) si timeout/erreur
    3. OCR basique si Vision échoue
    4. Placeholder si tout échoue (jamais vide)

    Usage:
        reader = VisionSemanticReader()
        result = await reader.read_page(image_bytes, page_no=5)
        print(result.semantic_text)  # "Ce diagramme illustre..."
    """

    # Placeholder standard (Invariant I1: jamais vide)
    PLACEHOLDER_TEMPLATE = "[VISUAL_CONTENT: Page {page_no} - interpretation unavailable]"

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout: float = 30.0,
        max_retries: int = 1,
    ):
        """
        Initialise le reader.

        Args:
            model: Modèle Vision (gpt-4o, gpt-4o-mini)
            temperature: Température pour génération
            max_tokens: Max tokens en sortie
            timeout: Timeout en secondes
            max_retries: Nombre de retries si échec
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = None
        self._initialized = False

        logger.info(
            f"[VisionSemanticReader] Initialized model={model}, "
            f"timeout={timeout}s, retries={max_retries}"
        )

    async def initialize(self) -> None:
        """Initialise le client OpenAI."""
        if self._initialized:
            return

        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI()
            self._initialized = True
            logger.info("[VisionSemanticReader] OpenAI client initialized")
        except ImportError as e:
            logger.error(f"[VisionSemanticReader] OpenAI not installed: {e}")
            raise ImportError(
                "openai n'est pas installé. Installer avec: pip install openai>=1.0.0"
            ) from e

    async def read_page(
        self,
        image_bytes: bytes,
        page_no: int,
        image_format: str = "png",
    ) -> VisionSemanticResult:
        """
        Lit une page visuelle et produit du texte sémantique.

        Implémente la fallback strategy 3-tier.

        Args:
            image_bytes: Image de la page en bytes
            page_no: Numéro de page
            image_format: Format image (png, jpeg)

        Returns:
            VisionSemanticResult avec semantic_text (jamais vide)
        """
        # Calculer le hash de l'image (pour cache/replay)
        image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

        # Tier 1: Vision GPT-4o
        result = await self._try_vision(image_bytes, page_no, image_format, image_hash)
        if result.text_origin == TextOrigin.VISION_SEMANTIC:
            return result

        # Tier 2: Retry (si c'était un timeout ou rate limit)
        if result.failure_reason in (
            VisionFailureReason.VISION_TIMEOUT,
            VisionFailureReason.VISION_RATE_LIMIT,
        ):
            logger.info(f"[VisionSemanticReader] Retry for page {page_no}")
            result = await self._try_vision(image_bytes, page_no, image_format, image_hash)
            if result.text_origin == TextOrigin.VISION_SEMANTIC:
                return result

        # Tier 3: OCR basique
        logger.info(f"[VisionSemanticReader] Falling back to OCR for page {page_no}")
        result = await self._try_ocr(image_bytes, page_no, image_hash)
        if result.text_origin == TextOrigin.OCR:
            return result

        # Tier 4: Placeholder (garantit jamais vide)
        logger.warning(f"[VisionSemanticReader] Using placeholder for page {page_no}")
        return VisionSemanticResult(
            page_no=page_no,
            semantic_text=self.PLACEHOLDER_TEMPLATE.format(page_no=page_no),
            text_origin=TextOrigin.PLACEHOLDER,
            confidence=0.0,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            image_hash=image_hash,
            failure_reason=result.failure_reason or VisionFailureReason.IMAGE_UNREADABLE,
        )

    async def _try_vision(
        self,
        image_bytes: bytes,
        page_no: int,
        image_format: str,
        image_hash: str,
    ) -> VisionSemanticResult:
        """Tente l'extraction via Vision GPT-4o."""
        if not self._initialized:
            await self.initialize()

        # Encoder l'image
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = "image/png" if image_format == "png" else "image/jpeg"

        messages = [
            {"role": "system", "content": VISION_SEMANTIC_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_base64}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": VISION_SEMANTIC_USER_PROMPT},
                ],
            },
        ]

        try:
            import asyncio
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                ),
                timeout=self.timeout,
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            # Construire le texte sémantique
            description = result.get("description", "")
            if not description.strip():
                raise ValueError("Empty description from Vision")

            return VisionSemanticResult(
                page_no=page_no,
                semantic_text=description,
                text_origin=TextOrigin.VISION_SEMANTIC,
                diagram_type=result.get("diagram_type"),
                confidence=result.get("confidence", 0.8),
                key_entities=result.get("key_entities", []),
                model=self.model,
                prompt_version=PROMPT_VERSION,
                image_hash=image_hash,
            )

        except asyncio.TimeoutError:
            logger.warning(f"[VisionSemanticReader] Timeout on page {page_no}")
            return VisionSemanticResult(
                page_no=page_no,
                semantic_text="",
                text_origin=TextOrigin.PLACEHOLDER,
                image_hash=image_hash,
                failure_reason=VisionFailureReason.VISION_TIMEOUT,
            )

        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                failure = VisionFailureReason.VISION_RATE_LIMIT
            elif "parse" in error_str or "json" in error_str:
                failure = VisionFailureReason.VISION_PARSE_ERROR
            else:
                failure = VisionFailureReason.VISION_API_ERROR

            logger.warning(f"[VisionSemanticReader] Vision error on page {page_no}: {e}")
            return VisionSemanticResult(
                page_no=page_no,
                semantic_text="",
                text_origin=TextOrigin.PLACEHOLDER,
                image_hash=image_hash,
                failure_reason=failure,
            )

    async def _try_ocr(
        self,
        image_bytes: bytes,
        page_no: int,
        image_hash: str,
    ) -> VisionSemanticResult:
        """Tente l'extraction via OCR basique."""
        try:
            # Essayer pytesseract
            from PIL import Image
            import pytesseract
            import io

            image = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(image)

            if text.strip():
                # Formater le texte OCR
                formatted = self._format_ocr_text(text, page_no)
                return VisionSemanticResult(
                    page_no=page_no,
                    semantic_text=formatted,
                    text_origin=TextOrigin.OCR,
                    confidence=0.5,
                    model="tesseract",
                    prompt_version=PROMPT_VERSION,
                    image_hash=image_hash,
                )

        except ImportError:
            logger.debug("[VisionSemanticReader] pytesseract not available")
        except Exception as e:
            logger.warning(f"[VisionSemanticReader] OCR failed: {e}")

        return VisionSemanticResult(
            page_no=page_no,
            semantic_text="",
            text_origin=TextOrigin.PLACEHOLDER,
            image_hash=image_hash,
            failure_reason=VisionFailureReason.OCR_FAILED,
        )

    def _format_ocr_text(self, raw_text: str, page_no: int) -> str:
        """Formate le texte OCR brut."""
        # Nettoyer le texte
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

        if not lines:
            return f"[OCR: Page {page_no} - no text detected]"

        # Limiter à un nombre raisonnable de lignes
        if len(lines) > 20:
            lines = lines[:20]
            lines.append("...")

        return f"[OCR extraction from page {page_no}]\n" + "\n".join(lines)


# Export
__all__ = [
    "VisionSemanticReader",
    "VisionSemanticResult",
    "PROMPT_VERSION",
]
