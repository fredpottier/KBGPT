"""
Hybrid Anchor Model - Pass 1 Concept Extractor

Extraction de concepts avec quotes exactes pour création d'anchors.
Remplace le pipeline concept-focused chunks par des anchors traçables.

Architecture:
1. EXTRACT_CONCEPTS: LLM extrait concepts + quotes exactes
2. ANCHOR_RESOLUTION: Fuzzy matching pour positions exactes
3. Création ProtoConcepts avec anchors validés

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import logging
import json
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.semantic.anchor_resolver import (
    create_anchor_with_fuzzy_match,
    batch_resolve_anchors,
    check_high_signal,
)
from knowbase.api.schemas.concepts import (
    Anchor,
    AnchorRole,
    ProtoConcept,
)
from knowbase.semantic.extraction.prompts import get_hybrid_anchor_extract_prompt
from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Résultat d'extraction Pass 1."""

    proto_concepts: List[ProtoConcept] = field(default_factory=list)
    rejected_concepts: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class HybridAnchorExtractor:
    """
    Extracteur de concepts pour le Hybrid Anchor Model (Pass 1).

    Pipeline:
    1. Segmentation du texte (déjà fait en amont)
    2. EXTRACT_CONCEPTS: LLM extrait concepts + quotes
    3. ANCHOR_RESOLUTION: Fuzzy matching pour positions
    4. Création ProtoConcepts avec anchors

    Invariant: Un concept sans anchor valide est rejeté.
    """

    def __init__(
        self,
        llm_router=None,
        tenant_id: str = "default"
    ):
        """
        Initialise l'extracteur.

        Args:
            llm_router: LLMRouter instance (optionnel, utilise singleton)
            tenant_id: ID tenant pour configuration
        """
        self.llm_router = llm_router or get_llm_router()
        self.tenant_id = tenant_id

        # Charger configuration
        self.anchor_config = get_hybrid_anchor_config("anchor_config", tenant_id) or {}

        logger.info(
            f"[OSMOSE:HybridAnchorExtractor] Initialized "
            f"(tenant={tenant_id}, min_fuzzy={self.anchor_config.get('min_fuzzy_score', 85)})"
        )

    async def extract_from_segment(
        self,
        segment_text: str,
        segment_id: str,
        document_id: str,
        document_context: str = "",
        section_id: Optional[str] = None,
        char_offset: int = 0
    ) -> ExtractionResult:
        """
        Extrait les concepts d'un segment avec anchors.

        Pipeline Pass 1:
        1. EXTRACT_CONCEPTS: Appel LLM pour concepts + quotes
        2. ANCHOR_RESOLUTION: Fuzzy matching pour chaque quote

        Args:
            segment_text: Texte du segment
            segment_id: ID unique du segment
            document_id: ID du document parent
            document_context: Contexte global du document
            section_id: ID de la section (optionnel)
            char_offset: Offset du segment dans le document complet
                         (2024-12-30: Fix mapping anchors → chunks)

        Returns:
            ExtractionResult avec ProtoConcepts et stats
        """
        result = ExtractionResult()
        result.stats["segment_id"] = segment_id
        result.stats["segment_chars"] = len(segment_text)

        # Phase A: EXTRACT_CONCEPTS
        logger.info(
            f"[OSMOSE:EXTRACT_CONCEPTS] Segment {segment_id} "
            f"({len(segment_text)} chars)"
        )

        try:
            concepts_raw = await self._extract_concepts_llm(
                segment_text, document_context
            )
            result.stats["concepts_extracted"] = len(concepts_raw)

        except Exception as e:
            logger.error(
                f"[OSMOSE:EXTRACT_CONCEPTS] Failed for segment {segment_id}: {e}"
            )
            result.stats["error"] = str(e)
            return result

        if not concepts_raw:
            logger.info(
                f"[OSMOSE:EXTRACT_CONCEPTS] No concepts in segment {segment_id}"
            )
            return result

        # Phase B: ANCHOR_RESOLUTION
        logger.info(
            f"[OSMOSE:ANCHOR_RESOLUTION] Resolving {len(concepts_raw)} concepts"
        )

        for concept_data in concepts_raw:
            proto_concept = self._resolve_anchor_and_create_proto(
                concept_data=concept_data,
                segment_text=segment_text,
                segment_id=segment_id,
                document_id=document_id,
                section_id=section_id,
                char_offset=char_offset
            )

            if proto_concept:
                result.proto_concepts.append(proto_concept)
            else:
                result.rejected_concepts.append({
                    **concept_data,
                    "rejection_reason": "Anchor resolution failed"
                })

        # Stats finales
        result.stats["proto_concepts_created"] = len(result.proto_concepts)
        result.stats["concepts_rejected"] = len(result.rejected_concepts)

        logger.info(
            f"[OSMOSE:ANCHOR_RESOLUTION] {segment_id}: "
            f"{len(result.proto_concepts)} valid, {len(result.rejected_concepts)} rejected"
        )

        return result

    async def _extract_concepts_llm(
        self,
        text: str,
        document_context: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Appelle LLM pour extraire concepts avec quotes exactes.

        Args:
            text: Texte du segment
            document_context: Contexte document

        Returns:
            Liste de dicts avec label, definition, quote, role, type_heuristic
        """
        # Construire prompt
        prompts = get_hybrid_anchor_extract_prompt(text, document_context)

        try:
            response_text = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": prompts["system_prompt"]},
                    {"role": "user", "content": prompts["user_prompt"]}
                ],
                temperature=0.1,  # Basse température pour quotes exactes
                response_format={"type": "json_object"}
            )

            # Parser JSON
            return self._parse_extraction_response(response_text)

        except Exception as e:
            logger.error(f"[OSMOSE:EXTRACT_CONCEPTS] LLM call failed: {e}")
            raise

    def _parse_extraction_response(
        self,
        response_text: str
    ) -> List[Dict[str, Any]]:
        """
        Parse la réponse LLM d'extraction.

        Args:
            response_text: Réponse brute du LLM

        Returns:
            Liste de concepts parsés
        """
        try:
            # Chercher JSON dans la réponse
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning("[OSMOSE:EXTRACT_CONCEPTS] No JSON in response")
                return []

            data = json.loads(json_match.group(0))
            concepts = data.get("concepts", [])

            # Valider structure minimale
            valid_concepts = []
            for c in concepts:
                if all(k in c for k in ["label", "quote"]):
                    valid_concepts.append({
                        "label": c["label"],
                        "definition": c.get("definition", ""),
                        "quote": c["quote"],
                        "role": c.get("role", "context"),
                        "type_heuristic": c.get("type_heuristic", "abstract")
                    })
                else:
                    logger.debug(
                        f"[OSMOSE:EXTRACT_CONCEPTS] Skipping invalid concept: {c}"
                    )

            return valid_concepts

        except json.JSONDecodeError as e:
            logger.error(f"[OSMOSE:EXTRACT_CONCEPTS] JSON parse error: {e}")
            return []

    def _resolve_anchor_and_create_proto(
        self,
        concept_data: Dict[str, Any],
        segment_text: str,
        segment_id: str,
        document_id: str,
        section_id: Optional[str] = None,
        char_offset: int = 0
    ) -> Optional[ProtoConcept]:
        """
        Résout l'anchor et crée un ProtoConcept.

        Invariant: Retourne None si anchor non trouvé (concept rejeté).

        Args:
            concept_data: Données du concept extrait
            segment_text: Texte source du segment
            segment_id: ID du segment (utilisé comme chunk_id provisoire)
            document_id: ID du document
            section_id: ID de la section
            char_offset: Offset du segment dans le document complet
                         (2024-12-30: Fix mapping anchors → chunks)

        Returns:
            ProtoConcept ou None si anchor invalide
        """
        # Créer ID unique
        proto_id = f"pc_{uuid.uuid4().hex[:12]}"

        # Résoudre anchor via fuzzy matching
        anchor = create_anchor_with_fuzzy_match(
            concept_id=proto_id,
            chunk_id=segment_id,  # Sera remappé vers chunk réel plus tard
            llm_quote=concept_data["quote"],
            source_text=segment_text,
            role=concept_data.get("role", "context"),
            section_id=section_id,
            tenant_id=self.tenant_id
        )

        # Invariant d'Architecture: pas d'anchor = pas de concept
        if anchor is None:
            logger.debug(
                f"[OSMOSE:ANCHOR_RESOLUTION] Rejected concept '{concept_data['label']}': "
                "no valid anchor"
            )
            return None

        # 2024-12-30: Ajuster positions de l'anchor pour être globales au document
        # Les positions retournées par create_anchor_with_fuzzy_match sont relatives au segment
        if char_offset > 0:
            anchor.char_start += char_offset
            anchor.char_end += char_offset

        # Créer ProtoConcept
        proto_concept = ProtoConcept(
            id=proto_id,
            label=concept_data["label"],
            definition=concept_data.get("definition", ""),
            type_heuristic=concept_data.get("type_heuristic", "abstract"),
            document_id=document_id,
            section_id=section_id,
            embedding=None,  # Calculé après en batch
            anchors=[anchor],
            tenant_id=self.tenant_id
        )

        return proto_concept

    async def extract_batch(
        self,
        segments: List[Dict[str, Any]],
        document_id: str,
        document_context: str = "",
        max_concurrent: int = 5
    ) -> ExtractionResult:
        """
        Extrait les concepts de plusieurs segments en parallèle.

        Args:
            segments: Liste de dicts avec 'text', 'segment_id', 'section_id'
            document_id: ID du document
            document_context: Contexte global
            max_concurrent: Concurrence max

        Returns:
            ExtractionResult agrégé
        """
        import asyncio

        result = ExtractionResult()
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_segment(segment: Dict[str, Any]):
            async with semaphore:
                return await self.extract_from_segment(
                    segment_text=segment["text"],
                    segment_id=segment["segment_id"],
                    document_id=document_id,
                    document_context=document_context,
                    section_id=segment.get("section_id"),
                    # 2024-12-30: Propager char_offset pour positions globales des anchors
                    char_offset=segment.get("char_offset", 0)
                )

        # Traiter en parallèle
        tasks = [process_segment(seg) for seg in segments]
        segment_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Agréger résultats
        for seg_result in segment_results:
            if isinstance(seg_result, Exception):
                logger.error(f"[OSMOSE:HybridAnchorExtractor] Segment error: {seg_result}")
                continue

            result.proto_concepts.extend(seg_result.proto_concepts)
            result.rejected_concepts.extend(seg_result.rejected_concepts)

        result.stats = {
            "total_segments": len(segments),
            "total_proto_concepts": len(result.proto_concepts),
            "total_rejected": len(result.rejected_concepts)
        }

        logger.info(
            f"[OSMOSE:HybridAnchorExtractor] Batch complete: "
            f"{len(result.proto_concepts)} concepts from {len(segments)} segments"
        )

        return result


# =============================================================================
# Factory Pattern
# =============================================================================

_extractor_instance: Optional[HybridAnchorExtractor] = None


def get_hybrid_anchor_extractor(
    tenant_id: str = "default"
) -> HybridAnchorExtractor:
    """
    Récupère l'instance singleton de l'extracteur.

    Args:
        tenant_id: ID tenant

    Returns:
        HybridAnchorExtractor instance
    """
    global _extractor_instance

    if _extractor_instance is None:
        _extractor_instance = HybridAnchorExtractor(tenant_id=tenant_id)

    return _extractor_instance
