"""
OSMOSE Pipeline V2.2 - Pass 1.A: Extraction Locale
===================================================
Extrait les assertions brutes depuis les chunks et calcule les embeddings.

Réutilise ~90% du code V2.1:
- AssertionExtractorV2.extract_assertions() pour l'extraction parallèle
- filter_by_promotion_policy() pour le filtrage
- EmbeddingModelManager.encode() pour les embeddings

Seul ajout: mapping zone_id via chunk_id → section_id → zone.
"""

import logging
import uuid
from typing import Dict, List, Optional, Tuple

import numpy as np

from knowbase.stratified.pass09.models import Zone
from knowbase.stratified.pass1_v22.models import ZonedAssertion

logger = logging.getLogger(__name__)


class LocalAssertionExtractor:
    """
    Pass 1.A — Extraction locale d'assertions + embeddings.

    Transforme les chunks bruts en assertions zonées avec embeddings
    pour le clustering zone-first de Pass 1.B.
    """

    def __init__(
        self,
        llm_client=None,
        allow_fallback: bool = False,
        strict_promotion: bool = False,
        max_workers: int = 8,
    ):
        self.llm_client = llm_client
        self.allow_fallback = allow_fallback
        self.strict_promotion = strict_promotion
        self.max_workers = max_workers

    def extract_and_embed(
        self,
        chunks: Dict[str, str],
        zones: List[Zone],
        chunk_to_section_map: Dict[str, str],
        doc_language: str = "fr",
    ) -> Tuple[List[ZonedAssertion], np.ndarray]:
        """
        Extrait les assertions et calcule leurs embeddings.

        Args:
            chunks: Mapping chunk_id -> texte
            zones: Zones détectées par Pass 0.9
            chunk_to_section_map: Mapping chunk_id -> section_id
            doc_language: Langue du document

        Returns:
            (assertions zonées, embeddings array shape (N, dim))
        """
        logger.info(
            f"[OSMOSE:Pass1:V2.2:1A] Extraction depuis {len(chunks)} chunks, "
            f"{len(zones)} zones, langue={doc_language}"
        )

        # 1. Extraction: réutilise AssertionExtractorV2
        from knowbase.stratified.pass1.assertion_extractor import (
            AssertionExtractorV2,
            RawAssertion,
        )

        extractor = AssertionExtractorV2(
            llm_client=self.llm_client,
            allow_fallback=self.allow_fallback,
            strict_promotion=self.strict_promotion,
            max_workers=self.max_workers,
        )

        raw_assertions: List[RawAssertion] = extractor.extract_assertions(
            chunks=chunks,
            doc_language=doc_language,
        )

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1A] Extracted {len(raw_assertions)} raw assertions"
        )

        if not raw_assertions:
            return [], np.empty((0, 1024))

        # 2. Promotion policy: filtrer NEVER, garder ALWAYS/CONDITIONAL/RARELY
        promotion_result = extractor.filter_by_promotion_policy(raw_assertions)
        promotable = promotion_result.promotable
        logger.info(
            f"[OSMOSE:Pass1:V2.2:1A] Promotion filter: "
            f"{len(promotable)} promotable / {len(raw_assertions)} total "
            f"({len(promotion_result.abstained)} abstained)"
        )

        if not promotable:
            return [], np.empty((0, 1024))

        # 3. Zone mapping: chunk_id → section_id → zone_id
        section_to_zone = self._build_section_to_zone_map(zones)

        zoned_assertions = []
        for idx, raw in enumerate(promotable):
            section_id = chunk_to_section_map.get(raw.chunk_id)
            zone_id = self._resolve_zone_id(
                section_id=section_id,
                section_to_zone=section_to_zone,
                zones=zones,
                page_no=None,  # page_no pas disponible dans RawAssertion
            )

            zoned_assertions.append(
                ZonedAssertion(
                    assertion_id=raw.assertion_id,
                    text=raw.text,
                    type=raw.assertion_type.value if hasattr(raw.assertion_type, "value") else str(raw.assertion_type),
                    chunk_id=raw.chunk_id,
                    zone_id=zone_id,
                    section_id=section_id,
                    page_no=None,
                    confidence=raw.confidence,
                    embedding_index=idx,
                )
            )

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1A] Zoned {len(zoned_assertions)} assertions "
            f"across {len(set(a.zone_id for a in zoned_assertions))} zones"
        )

        # 4. Embeddings
        embeddings = self._compute_embeddings(
            [a.text for a in zoned_assertions]
        )

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1A] Embeddings computed: shape={embeddings.shape}"
        )

        return zoned_assertions, embeddings

    def _build_section_to_zone_map(
        self, zones: List[Zone]
    ) -> Dict[str, str]:
        """Construit un mapping section_id → zone_id."""
        section_to_zone = {}
        for zone in zones:
            for sid in zone.section_ids:
                section_to_zone[sid] = zone.zone_id
        return section_to_zone

    def _resolve_zone_id(
        self,
        section_id: Optional[str],
        section_to_zone: Dict[str, str],
        zones: List[Zone],
        page_no: Optional[int],
    ) -> str:
        """
        Résout le zone_id pour une assertion.

        Stratégie:
        1. section_id → lookup direct
        2. page_no → chercher par page_range
        3. Fallback → première zone
        """
        # Lookup direct
        if section_id and section_id in section_to_zone:
            return section_to_zone[section_id]

        # Fallback par page_no
        if page_no is not None and zones:
            for zone in zones:
                p_min, p_max = zone.page_range
                if p_min <= page_no <= p_max:
                    return zone.zone_id

        # Dernier recours: première zone
        return zones[0].zone_id if zones else "z1"

    def _compute_embeddings(self, texts: List[str]) -> np.ndarray:
        """
        Calcule les embeddings via EmbeddingModelManager.

        Returns:
            np.ndarray de shape (N, dim)
        """
        if not texts:
            return np.empty((0, 1024))

        try:
            from knowbase.common.clients.embeddings import EmbeddingModelManager

            manager = EmbeddingModelManager()
            embeddings = manager.encode(texts)
            return embeddings
        except Exception as e:
            logger.warning(
                f"[OSMOSE:Pass1:V2.2:1A] Embedding computation failed: {e}. "
                "Using random embeddings as fallback."
            )
            # Fallback: embeddings aléatoires normalisés (pour tests)
            rng = np.random.default_rng(42)
            emb = rng.standard_normal((len(texts), 1024)).astype(np.float32)
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return emb / norms
