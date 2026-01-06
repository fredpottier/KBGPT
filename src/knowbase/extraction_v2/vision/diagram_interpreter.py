"""
DiagramInterpreter - QW-3 ADR_REDUCTO_PARSING_PRIMITIVES.

Extraction structurée de diagrammes avec routing adaptatif LITE/FULL.

Architecture:
- Pass 0: GatingEngine (existant) → décide si Vision nécessaire
- Pass 1: DiagramInterpreter → VISION_LITE ou VISION_FULL selon VNS
- Quality Gate: confidence < 0.7 → fallback prose

Usage:
    >>> interpreter = DiagramInterpreter()
    >>> result = await interpreter.interpret(
    ...     image_bytes=image,
    ...     gating_decision=decision,
    ...     local_snippets="Title: Architecture"
    ... )
    >>> if result.extraction_method == "fallback_prose":
    ...     use_prose_summary(result.semantic_summary)
    ... else:
    ...     use_structured_elements(result.elements)
"""

from __future__ import annotations

import logging
import json
import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from knowbase.extraction_v2.models import (
    VisionExtraction,
    VisionElement,
    VisionRelation,
    VisionUncertainty,
    VisionDomainContext,
    GatingDecision,
    ExtractionAction,
)
from knowbase.extraction_v2.vision.prompts import (
    get_vision_messages,
    get_vision_lite_messages,
)

logger = logging.getLogger(__name__)


class ExtractionMethod(str, Enum):
    """Méthode d'extraction utilisée."""
    SKIP = "skip"              # Pas de contenu visuel significatif
    TEXT_ONLY = "text_only"    # Contenu textuel uniquement, pas de VLM
    VISION_LITE = "vision_lite"  # Extraction rapide (labels uniquement)
    VISION_FULL = "vision_full"  # Extraction complète (éléments + relations)
    FALLBACK_PROSE = "fallback_prose"  # Quality Gate échoué, fallback prose


@dataclass
class InterpretationResult:
    """
    Résultat de l'interprétation de diagramme.

    Étend VisionExtraction avec:
    - extraction_method: méthode utilisée
    - quality_gate_passed: si le Quality Gate a été passé
    - semantic_summary: résumé prose (si FALLBACK_PROSE)
    """
    extraction: VisionExtraction
    extraction_method: ExtractionMethod
    quality_gate_passed: bool
    semantic_summary: str = ""
    routing_reason: str = ""

    # Métriques
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "extraction": self.extraction.to_dict(),
            "extraction_method": self.extraction_method.value,
            "quality_gate_passed": self.quality_gate_passed,
            "semantic_summary": self.semantic_summary,
            "routing_reason": self.routing_reason,
        }


# === Seuils de routing ===
ROUTING_THRESHOLDS = {
    "vision_full_vns": 0.60,    # VNS >= 0.60 → VISION_FULL
    "vision_lite_vns": 0.40,    # VNS >= 0.40 → VISION_LITE
    "quality_gate": 0.70,       # confidence >= 0.70 → pass
}


class DiagramInterpreter:
    """
    Interprète les diagrammes avec routing adaptatif LITE/FULL.

    Architecture Pass 0 + Pass 1:
    - Pass 0 (GatingEngine): Décide VISION_REQUIRED/RECOMMENDED/NONE
    - Pass 1 (DiagramInterpreter): LITE ou FULL selon VNS score
    - Quality Gate: Si confidence < 0.7, fallback vers prose

    Le routing optimise le coût:
    - SKIP: pas d'appel VLM (0 tokens)
    - TEXT_ONLY: pas d'appel VLM, utilise OCR existant
    - VISION_LITE: prompt court, detail=low (~500 tokens)
    - VISION_FULL: prompt complet, detail=high (~2000 tokens)
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        lite_model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        max_tokens_full: int = 4096,
        max_tokens_lite: int = 1024,
        quality_gate_threshold: float = 0.70,
    ):
        """
        Initialise le DiagramInterpreter.

        Args:
            model: Modèle pour VISION_FULL
            lite_model: Modèle pour VISION_LITE (plus rapide/moins cher)
            temperature: Température de génération
            max_tokens_full: Max tokens pour VISION_FULL
            max_tokens_lite: Max tokens pour VISION_LITE
            quality_gate_threshold: Seuil de confiance pour Quality Gate
        """
        self.model = model
        self.lite_model = lite_model
        self.temperature = temperature
        self.max_tokens_full = max_tokens_full
        self.max_tokens_lite = max_tokens_lite
        self.quality_gate_threshold = quality_gate_threshold

        self._client = None
        self._initialized = False

        logger.info(
            f"[DiagramInterpreter] Initialized: full={model}, lite={lite_model}, "
            f"quality_gate={quality_gate_threshold}"
        )

    async def initialize(self) -> None:
        """Initialise le client OpenAI."""
        if self._initialized:
            return

        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI()
            self._initialized = True
            logger.info("[DiagramInterpreter] OpenAI client initialized")
        except ImportError as e:
            raise ImportError(
                "openai n'est pas installé. Installer avec: pip install openai>=1.0.0"
            ) from e

    def route(self, gating_decision: GatingDecision) -> ExtractionMethod:
        """
        Détermine la méthode d'extraction basée sur le GatingDecision.

        Routing Logic:
        - NONE (VNS < 0.40) → SKIP ou TEXT_ONLY
        - VISION_RECOMMENDED (0.40 <= VNS < 0.60) → VISION_LITE
        - VISION_REQUIRED (VNS >= 0.60 ou règle sécurité) → VISION_FULL

        Args:
            gating_decision: Décision du GatingEngine (Pass 0)

        Returns:
            ExtractionMethod à utiliser
        """
        action = gating_decision.action
        vns = gating_decision.vision_need_score

        # NONE → SKIP ou TEXT_ONLY
        if action == ExtractionAction.NONE:
            # Si quand même des signaux texte élevés, utiliser TEXT_ONLY
            if gating_decision.signals and gating_decision.signals.TFS >= 0.3:
                return ExtractionMethod.TEXT_ONLY
            return ExtractionMethod.SKIP

        # VISION_RECOMMENDED → VISION_LITE
        if action == ExtractionAction.VISION_RECOMMENDED:
            return ExtractionMethod.VISION_LITE

        # VISION_REQUIRED → VISION_FULL
        return ExtractionMethod.VISION_FULL

    async def interpret(
        self,
        image_bytes: bytes,
        gating_decision: GatingDecision,
        domain_context: Optional[VisionDomainContext] = None,
        local_snippets: str = "",
        page_index: Optional[int] = None,
        image_format: str = "png",
    ) -> InterpretationResult:
        """
        Interprète un diagramme avec routing adaptatif.

        Args:
            image_bytes: Image en bytes
            gating_decision: Décision Pass 0 du GatingEngine
            domain_context: Contexte métier
            local_snippets: Texte local extrait
            page_index: Index de la page
            image_format: Format de l'image

        Returns:
            InterpretationResult avec extraction et métadonnées
        """
        # Déterminer la méthode de routing
        method = self.route(gating_decision)
        vns = gating_decision.vision_need_score

        logger.info(
            f"[DiagramInterpreter] Routing: {method.value} (VNS={vns:.2f}, "
            f"action={gating_decision.action.value})"
        )

        # SKIP: Pas de contenu visuel significatif
        if method == ExtractionMethod.SKIP:
            return InterpretationResult(
                extraction=VisionExtraction(
                    kind="skipped",
                    elements=[],
                    relations=[],
                    page_index=page_index,
                    confidence=0.0,
                ),
                extraction_method=method,
                quality_gate_passed=False,
                routing_reason=f"VNS too low ({vns:.2f} < 0.40), no visual content",
            )

        # TEXT_ONLY: Utiliser texte OCR existant
        if method == ExtractionMethod.TEXT_ONLY:
            return InterpretationResult(
                extraction=VisionExtraction(
                    kind="text_only",
                    elements=[],
                    relations=[],
                    page_index=page_index,
                    confidence=0.5,
                ),
                extraction_method=method,
                quality_gate_passed=True,
                semantic_summary=local_snippets,
                routing_reason="Text-heavy content, OCR sufficient",
            )

        # Initialiser le client si nécessaire
        if not self._initialized:
            await self.initialize()

        # VISION_LITE ou VISION_FULL
        if method == ExtractionMethod.VISION_LITE:
            extraction = await self._call_vision_lite(
                image_bytes, local_snippets, page_index, image_format
            )
        else:
            extraction = await self._call_vision_full(
                image_bytes, domain_context, local_snippets, page_index, image_format
            )

        # Quality Gate
        quality_gate_passed = extraction.confidence >= self.quality_gate_threshold

        if not quality_gate_passed:
            logger.info(
                f"[DiagramInterpreter] Quality Gate FAILED: "
                f"confidence={extraction.confidence:.2f} < {self.quality_gate_threshold}"
            )
            # Générer un résumé prose comme fallback
            prose_summary = self._generate_prose_fallback(extraction, local_snippets)

            return InterpretationResult(
                extraction=extraction,
                extraction_method=ExtractionMethod.FALLBACK_PROSE,
                quality_gate_passed=False,
                semantic_summary=prose_summary,
                routing_reason=f"Quality Gate failed (confidence={extraction.confidence:.2f})",
            )

        logger.info(
            f"[DiagramInterpreter] Quality Gate PASSED: "
            f"confidence={extraction.confidence:.2f}, "
            f"{len(extraction.elements)} elements, {len(extraction.relations)} relations"
        )

        return InterpretationResult(
            extraction=extraction,
            extraction_method=method,
            quality_gate_passed=True,
            routing_reason=f"Successful {method.value} extraction",
        )

    async def _call_vision_lite(
        self,
        image_bytes: bytes,
        local_snippets: str,
        page_index: Optional[int],
        image_format: str,
    ) -> VisionExtraction:
        """
        Appelle le VLM en mode LITE (extraction rapide).

        Args:
            image_bytes: Image en bytes
            local_snippets: Texte local
            page_index: Index de la page
            image_format: Format de l'image

        Returns:
            VisionExtraction (avec éléments de type label uniquement)
        """
        # Encoder l'image
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        # Construire les messages LITE
        messages = get_vision_lite_messages(
            local_snippets=local_snippets,
            image_base64=image_base64,
        )

        # Ajuster le MIME type
        mime_type = f"image/{image_format}"
        if image_format in ("jpg", "jpeg"):
            mime_type = "image/jpeg"
        messages[1]["content"][0]["image_url"]["url"] = f"data:{mime_type};base64,{image_base64}"

        logger.debug(f"[DiagramInterpreter] Calling LITE with {self.lite_model}")

        try:
            response = await self._client.chat.completions.create(
                model=self.lite_model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens_lite,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"[DiagramInterpreter] LITE JSON parse error: {e}")
                return VisionExtraction(
                    kind="parse_error",
                    elements=[],
                    relations=[],
                    page_index=page_index,
                    confidence=0.0,
                )

            # Parser la réponse LITE (labels uniquement)
            return self._parse_lite_response(result, page_index)

        except Exception as e:
            logger.error(f"[DiagramInterpreter] LITE API call failed: {e}")
            return VisionExtraction(
                kind="api_error",
                elements=[],
                relations=[],
                page_index=page_index,
                confidence=0.0,
                uncertainties=[
                    VisionUncertainty(item="api_call", reason=str(e))
                ],
            )

    async def _call_vision_full(
        self,
        image_bytes: bytes,
        domain_context: Optional[VisionDomainContext],
        local_snippets: str,
        page_index: Optional[int],
        image_format: str,
    ) -> VisionExtraction:
        """
        Appelle le VLM en mode FULL (extraction complète).

        Args:
            image_bytes: Image en bytes
            domain_context: Contexte métier
            local_snippets: Texte local
            page_index: Index de la page
            image_format: Format de l'image

        Returns:
            VisionExtraction complète avec éléments et relations
        """
        # Encoder l'image
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        # Construire les messages FULL
        messages = get_vision_messages(
            domain_context=domain_context,
            local_snippets=local_snippets,
            image_base64=image_base64,
        )

        # Ajuster le MIME type
        mime_type = f"image/{image_format}"
        if image_format in ("jpg", "jpeg"):
            mime_type = "image/jpeg"
        messages[1]["content"][0]["image_url"]["url"] = f"data:{mime_type};base64,{image_base64}"

        logger.debug(f"[DiagramInterpreter] Calling FULL with {self.model}")

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens_full,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"[DiagramInterpreter] FULL JSON parse error: {e}")
                return VisionExtraction(
                    kind="parse_error",
                    elements=[],
                    relations=[],
                    page_index=page_index,
                    confidence=0.0,
                )

            # Parser la réponse FULL
            return VisionExtraction.from_llm_response(result, page_index)

        except Exception as e:
            logger.error(f"[DiagramInterpreter] FULL API call failed: {e}")
            return VisionExtraction(
                kind="api_error",
                elements=[],
                relations=[],
                page_index=page_index,
                confidence=0.0,
                uncertainties=[
                    VisionUncertainty(item="api_call", reason=str(e))
                ],
            )

    def _parse_lite_response(
        self,
        response: Dict[str, Any],
        page_index: Optional[int],
    ) -> VisionExtraction:
        """
        Parse la réponse LITE en VisionExtraction.

        Le format LITE ne contient que des labels, pas de relations.

        Args:
            response: Réponse JSON du LLM
            page_index: Index de la page

        Returns:
            VisionExtraction avec éléments (labels uniquement)
        """
        kind = response.get("diagram_type", "unknown")
        overall_confidence = response.get("overall_confidence", 0.5)

        elements = []
        for label_data in response.get("labels", []):
            elem = VisionElement(
                id=label_data.get("id", f"L{len(elements)}"),
                type=label_data.get("type", "label"),
                text=label_data.get("text", ""),
                confidence=overall_confidence,  # Utiliser confidence globale
            )
            elements.append(elem)

        return VisionExtraction(
            kind=kind,
            elements=elements,
            relations=[],  # LITE n'extrait pas de relations
            page_index=page_index,
            confidence=overall_confidence,
            raw_model_output=response,
        )

    def _generate_prose_fallback(
        self,
        extraction: VisionExtraction,
        local_snippets: str,
    ) -> str:
        """
        Génère un résumé prose comme fallback quand Quality Gate échoue.

        Combine les éléments extraits (même basse confiance) avec le texte local.

        Args:
            extraction: Extraction (basse confiance)
            local_snippets: Texte local

        Returns:
            Résumé prose pour inclusion dans le Knowledge Graph
        """
        parts = []

        # Type de diagramme
        if extraction.kind and extraction.kind not in ("unknown", "parse_error", "api_error"):
            parts.append(f"Diagram type: {extraction.kind}")

        # Labels extraits (même si basse confiance)
        if extraction.elements:
            labels = [e.text for e in extraction.elements if e.text]
            if labels:
                parts.append(f"Visible elements: {', '.join(labels[:10])}")

        # Incertitudes
        if extraction.uncertainties:
            reasons = [u.reason for u in extraction.uncertainties[:3]]
            parts.append(f"Uncertainties: {'; '.join(reasons)}")

        # Texte local comme complément
        if local_snippets:
            parts.append(f"Context: {local_snippets[:200]}")

        return " | ".join(parts) if parts else "Visual content (extraction uncertain)"


# === Factory ===

_interpreter_instance: Optional[DiagramInterpreter] = None


def get_diagram_interpreter() -> DiagramInterpreter:
    """
    Récupère l'instance singleton du DiagramInterpreter.

    Returns:
        DiagramInterpreter instance
    """
    global _interpreter_instance

    if _interpreter_instance is None:
        _interpreter_instance = DiagramInterpreter()
        logger.info("[DiagramInterpreter] Singleton initialized")

    return _interpreter_instance


__all__ = [
    "DiagramInterpreter",
    "InterpretationResult",
    "ExtractionMethod",
    "get_diagram_interpreter",
]
