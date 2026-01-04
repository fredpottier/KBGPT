"""
ExtractionPipelineV2 - Pipeline principal d'extraction documentaire.

Orchestre l'ensemble du flux:
1. Extraction via Docling (unifie tous formats)
2. Vision Gating V4 (decision par page/slide)
3. Vision Path (si necessaire)
4. Structured Merge
5. Linearisation vers full_text

Specification: OSMOSIS_EXTRACTION_V2_DECISIONS.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime
import logging
import hashlib
import asyncio
import os
import time

from knowbase.extraction_v2.models import (
    ExtractionResult,
    VisionUnit,
    GatingDecision,
    VisionDomainContext,
    ExtractionAction,
    DocumentStructure,
    PageOutput,
    PageIndex,
    VisionExtraction,
    get_vision_domain_context,
)
from knowbase.extraction_v2.extractors.docling_extractor import DoclingExtractor
from knowbase.extraction_v2.gating.engine import GatingEngine
from knowbase.extraction_v2.gating.weights import DEFAULT_GATING_WEIGHTS, GATING_THRESHOLDS
from knowbase.extraction_v2.vision.analyzer import VisionAnalyzer
from knowbase.extraction_v2.merge.merger import StructuredMerger, MergedPageOutput
from knowbase.extraction_v2.merge.linearizer import Linearizer
from knowbase.extraction_v2.cache.versioned_cache import VersionedCache

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration du pipeline d'extraction V2."""

    # Activation des composants
    enable_vision: bool = True
    enable_gating: bool = True

    # Seuils de gating
    vision_required_threshold: float = 0.60
    vision_recommended_threshold: float = 0.40

    # Budget Vision (nombre max de pages avec Vision)
    vision_budget: Optional[int] = None

    # Tenant pour DomainContext
    tenant_id: str = "default"

    # Options de cache
    use_cache: bool = True
    cache_version: str = "v2"

    # Options Vision
    vision_model: str = "gpt-4o"
    vision_temperature: float = 0.0

    # Inclure les pages RECOMMENDED dans Vision (ou seulement REQUIRED)
    include_recommended_in_vision: bool = True

    # Concurrence Vision (nombre d'appels GPT-4o simultanés)
    # Default: MAX_WORKERS env var ou 30
    max_concurrent_vision: int = None  # None = auto-detect from env

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire."""
        return {
            "enable_vision": self.enable_vision,
            "enable_gating": self.enable_gating,
            "vision_required_threshold": self.vision_required_threshold,
            "vision_recommended_threshold": self.vision_recommended_threshold,
            "vision_budget": self.vision_budget,
            "tenant_id": self.tenant_id,
            "use_cache": self.use_cache,
            "cache_version": self.cache_version,
            "vision_model": self.vision_model,
            "include_recommended_in_vision": self.include_recommended_in_vision,
            "max_concurrent_vision": self.max_concurrent_vision,
        }


@dataclass
class PipelineMetrics:
    """Metriques d'execution du pipeline."""
    total_pages: int = 0
    vision_required_pages: int = 0
    vision_recommended_pages: int = 0
    vision_processed_pages: int = 0
    extraction_time_ms: float = 0
    gating_time_ms: float = 0
    vision_time_ms: float = 0
    total_time_ms: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pages": self.total_pages,
            "vision_required_pages": self.vision_required_pages,
            "vision_recommended_pages": self.vision_recommended_pages,
            "vision_processed_pages": self.vision_processed_pages,
            "extraction_time_ms": round(self.extraction_time_ms, 2),
            "gating_time_ms": round(self.gating_time_ms, 2),
            "vision_time_ms": round(self.vision_time_ms, 2),
            "total_time_ms": round(self.total_time_ms, 2),
        }


class ExtractionPipelineV2:
    """
    Pipeline principal d'extraction documentaire V2.

    Architecture:
    - Docling comme extracteur unifie (PDF, DOCX, PPTX, XLSX)
    - Vision Gating V4 avec 5 signaux (RIS, VDS, TFS, SDS, VTS)
    - Vision Path avec Domain Context injectable
    - Sortie bi-couche: full_text (OSMOSE) + structure (audit/futur)

    Usage:
        >>> pipeline = ExtractionPipelineV2()
        >>> result = await pipeline.process_document("/path/to/doc.pdf")
        >>> print(result.full_text)  # Pour OSMOSE
        >>> print(result.structure)  # Structure complete
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """
        Initialise le pipeline.

        Args:
            config: Configuration du pipeline (optionnel)
        """
        self.config = config or PipelineConfig()
        self._initialized = False

        # Composants (initialises dans initialize())
        self._extractor: Optional[DoclingExtractor] = None
        self._gating_engine: Optional[GatingEngine] = None
        self._vision_analyzer: Optional[VisionAnalyzer] = None
        self._merger: Optional[StructuredMerger] = None
        self._linearizer: Optional[Linearizer] = None

        # Cache V2 (évite de refaire les appels Vision)
        self._cache: Optional[VersionedCache] = None
        if self.config.use_cache:
            self._cache = VersionedCache(
                cache_dir="/data/extraction_cache",
                version=self.config.cache_version,
            )

        logger.info(
            f"[ExtractionPipelineV2] Created with config: "
            f"tenant={self.config.tenant_id}, "
            f"vision={self.config.enable_vision}, "
            f"gating={self.config.enable_gating}"
        )

    async def initialize(self) -> None:
        """
        Initialise les composants du pipeline.

        Appele automatiquement lors du premier traitement.
        """
        if self._initialized:
            return

        start = time.time()

        # 1. Initialiser DoclingExtractor
        self._extractor = DoclingExtractor(
            ocr_enabled=True,
            table_mode="accurate",
        )
        await self._extractor.initialize()

        # 2. Initialiser GatingEngine
        thresholds = {
            "VISION_REQUIRED": self.config.vision_required_threshold,
            "VISION_RECOMMENDED": self.config.vision_recommended_threshold,
        }
        self._gating_engine = GatingEngine(
            weights=DEFAULT_GATING_WEIGHTS.copy(),
            thresholds=thresholds,
        )

        # 3. Initialiser VisionAnalyzer
        if self.config.enable_vision:
            self._vision_analyzer = VisionAnalyzer(
                model=self.config.vision_model,
                temperature=self.config.vision_temperature,
            )
            await self._vision_analyzer.initialize()

        # 4. Initialiser Merger et Linearizer
        self._merger = StructuredMerger(
            vision_model=self.config.vision_model,
        )
        self._linearizer = Linearizer(
            include_vision=self.config.enable_vision,
            include_tables=True,
        )

        self._initialized = True
        elapsed = (time.time() - start) * 1000

        logger.info(
            f"[ExtractionPipelineV2] Components initialized in {elapsed:.0f}ms"
        )

    async def process_document(
        self,
        file_path: str,
        document_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> ExtractionResult:
        """
        Traite un document et retourne le resultat d'extraction.

        Args:
            file_path: Chemin vers le document
            document_id: ID du document (genere si non fourni)
            tenant_id: Tenant pour DomainContext (override config)

        Returns:
            ExtractionResult avec full_text et structure
        """
        total_start = time.time()
        metrics = PipelineMetrics()

        # Initialiser si necessaire
        if not self._initialized:
            await self.initialize()

        # Generer document_id si non fourni
        if not document_id:
            document_id = self._generate_document_id(file_path)

        # Tenant effectif
        effective_tenant = tenant_id or self.config.tenant_id

        # === CACHE CHECK ===
        if self._cache:
            cached_result = self._cache.get(document_id, file_path)
            if cached_result:
                logger.info(
                    f"[ExtractionPipelineV2] Cache HIT: {document_id}, "
                    f"skipping extraction (saved Vision calls!)"
                )
                return cached_result

        # Obtenir le Domain Context
        domain_context = get_vision_domain_context(effective_tenant)

        logger.info(
            f"[ExtractionPipelineV2] Processing: {file_path}, "
            f"doc_id={document_id}, tenant={effective_tenant}"
        )

        # === ETAPE 1: Extraction Docling ===
        extraction_start = time.time()
        units = await self._extractor.extract_to_units(file_path)
        metrics.extraction_time_ms = (time.time() - extraction_start) * 1000
        metrics.total_pages = len(units)

        logger.info(
            f"[ExtractionPipelineV2] Extracted {len(units)} pages in "
            f"{metrics.extraction_time_ms:.0f}ms"
        )

        # === ETAPE 2: Vision Gating ===
        gating_start = time.time()
        if self.config.enable_gating:
            gating_decisions = self._gating_engine.gate_document(units, domain_context)
        else:
            # Pas de gating = toutes les pages NO_VISION
            gating_decisions = [
                GatingDecision(
                    index=u.index,
                    unit_id=u.id,
                    action=ExtractionAction.NONE,
                    vision_need_score=0.0,
                )
                for u in units
            ]
        metrics.gating_time_ms = (time.time() - gating_start) * 1000

        # Compter les decisions
        for d in gating_decisions:
            if d.action == ExtractionAction.VISION_REQUIRED:
                metrics.vision_required_pages += 1
            elif d.action == ExtractionAction.VISION_RECOMMENDED:
                metrics.vision_recommended_pages += 1

        logger.info(
            f"[ExtractionPipelineV2] Gating complete in {metrics.gating_time_ms:.0f}ms: "
            f"REQUIRED={metrics.vision_required_pages}, "
            f"RECOMMENDED={metrics.vision_recommended_pages}"
        )

        # === ETAPE 3: Vision Path ===
        vision_extractions: Dict[int, VisionExtraction] = {}

        if self.config.enable_vision and self._vision_analyzer:
            vision_start = time.time()

            # Determiner quelles pages envoyer a Vision
            vision_indices = self._gating_engine.get_vision_candidates(
                gating_decisions,
                include_recommended=self.config.include_recommended_in_vision,
            )

            # Appliquer le budget si configure
            if self.config.vision_budget and len(vision_indices) > self.config.vision_budget:
                # Prioriser REQUIRED, puis RECOMMENDED par VNS
                vision_indices = self._prioritize_vision_candidates(
                    vision_indices,
                    gating_decisions,
                    self.config.vision_budget,
                )

            # Traiter les pages Vision EN PARALLELE
            # Concurrence configurable via MAX_WORKERS env var (default: 30)
            max_concurrent = self.config.max_concurrent_vision
            if max_concurrent is None:
                max_concurrent = int(os.getenv("MAX_WORKERS", "30"))

            # Réduire la concurrence pour les très gros documents (>400 pages)
            if len(vision_indices) > 400:
                max_concurrent = min(max_concurrent, 5)
                logger.info(f"[ExtractionPipelineV2] Large document: reducing concurrency to {max_concurrent}")

            semaphore = asyncio.Semaphore(max_concurrent)

            logger.info(
                f"[ExtractionPipelineV2] Starting parallel Vision processing: "
                f"{len(vision_indices)} pages, max_concurrent={max_concurrent}"
            )

            async def process_page(page_idx: int) -> tuple:
                """Traite une page avec semaphore pour limiter la concurrence."""
                async with semaphore:
                    unit = units[page_idx]
                    local_snippets = self._build_local_snippets(unit)

                    try:
                        extraction = await self._vision_analyzer.analyze_page(
                            file_path=file_path,
                            page_index=page_idx,
                            domain_context=domain_context,
                            local_snippets=local_snippets,
                        )
                        return (page_idx, extraction, None)
                    except Exception as e:
                        logger.warning(f"[ExtractionPipelineV2] Vision failed for page {page_idx}: {e}")
                        return (page_idx, None, e)

            # Lancer tous les appels en parallèle
            tasks = [process_page(idx) for idx in vision_indices]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collecter les résultats
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"[ExtractionPipelineV2] Vision task exception: {result}")
                    continue

                page_idx, extraction, error = result
                if extraction is not None:
                    vision_extractions[page_idx] = extraction
                    metrics.vision_processed_pages += 1

            metrics.vision_time_ms = (time.time() - vision_start) * 1000

            logger.info(
                f"[ExtractionPipelineV2] Vision complete in {metrics.vision_time_ms:.0f}ms: "
                f"{metrics.vision_processed_pages}/{len(vision_indices)} pages processed (parallel)"
            )

        # === ETAPE 4: Merge ===
        merged_pages = self._merger.merge_document(
            units=units,
            vision_extractions=vision_extractions,
            gating_decisions=gating_decisions,
        )

        # === ETAPE 5: Linearisation ===
        full_text, page_index = self._linearizer.linearize(merged_pages)

        # === Construction du resultat ===
        structure = self._build_structure(merged_pages, gating_decisions)

        # Detecter le type de fichier
        file_type = Path(file_path).suffix.lower().lstrip(".")

        # Collecter les vision_results des pages qui ont eu Vision
        vision_results = [
            merged_pages[idx].vision_enrichment
            for idx in vision_indices
            if merged_pages[idx].vision_enrichment is not None
        ]

        result = ExtractionResult(
            document_id=document_id,
            source_path=file_path,
            file_type=file_type,
            full_text=full_text,
            structure=structure,
            page_index=page_index,
            extraction_timestamp=datetime.now().isoformat(),
            domain_context_name=effective_tenant,
            gating_decisions=gating_decisions,
            vision_results=vision_results,
            stats={
                "tenant_id": effective_tenant,
                "config": self.config.to_dict(),
                "metrics": metrics.to_dict(),
            },
        )

        metrics.total_time_ms = (time.time() - total_start) * 1000

        # === CACHE SAVE ===
        if self._cache:
            self._cache.set(document_id, file_path, result)

        logger.info(
            f"[ExtractionPipelineV2] Complete: {document_id}, "
            f"{len(full_text)} chars, {metrics.total_time_ms:.0f}ms total"
        )

        return result

    async def process_units(
        self,
        units: List[VisionUnit],
        tenant_id: Optional[str] = None,
    ) -> List[GatingDecision]:
        """
        Traite une liste de VisionUnits et retourne les decisions de gating.

        Args:
            units: Liste de VisionUnits
            tenant_id: Tenant pour DomainContext

        Returns:
            Liste de GatingDecisions
        """
        if not self._initialized:
            await self.initialize()

        effective_tenant = tenant_id or self.config.tenant_id
        domain_context = get_vision_domain_context(effective_tenant)

        return self._gating_engine.gate_document(units, domain_context)

    def _generate_document_id(self, file_path: str) -> str:
        """Genere un ID unique pour le document basé sur le contenu."""
        path = Path(file_path)
        # Extraire le nom de base (sans suffixes aléatoires type _abc123)
        name = path.stem
        # Retirer les suffixes hex (6+ chars) ajoutés par le watcher
        import re
        name = re.sub(r'_[a-f0-9]{6,}$', '', name)

        # Hash du CONTENU du fichier (pas du chemin) pour que le même fichier
        # ait toujours le même ID, même s'il est copié avec un nom différent
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        content_hash = sha256.hexdigest()[:8]

        return f"{name}_{content_hash}"

    def _build_local_snippets(self, unit: VisionUnit) -> str:
        """Construit les snippets locaux pour Vision."""
        snippets = []

        if unit.title:
            snippets.append(f"Title: {unit.title}")

        for block in unit.blocks[:10]:
            if block.text and len(block.text) > 5:
                snippets.append(block.text[:200])

        return "\n".join(snippets)

    def _prioritize_vision_candidates(
        self,
        candidates: List[int],
        decisions: List[GatingDecision],
        budget: int,
    ) -> List[int]:
        """Priorise les candidats Vision selon le budget."""
        # Indexer par page
        decisions_by_idx = {d.index: d for d in decisions}

        # Separer REQUIRED et RECOMMENDED
        required = []
        recommended = []

        for idx in candidates:
            d = decisions_by_idx.get(idx)
            if d:
                if d.action == ExtractionAction.VISION_REQUIRED:
                    required.append((idx, d.vision_need_score))
                else:
                    recommended.append((idx, d.vision_need_score))

        # Trier par score decroissant
        required.sort(key=lambda x: x[1], reverse=True)
        recommended.sort(key=lambda x: x[1], reverse=True)

        # Prendre d'abord les REQUIRED, puis les RECOMMENDED
        result = [idx for idx, _ in required]

        remaining = budget - len(result)
        if remaining > 0:
            result.extend([idx for idx, _ in recommended[:remaining]])

        return result[:budget]

    def _build_structure(
        self,
        merged_pages: List[MergedPageOutput],
        gating_decisions: List[GatingDecision],
    ) -> DocumentStructure:
        """Construit la structure du document."""
        pages = []

        decisions_by_idx = {d.index: d for d in gating_decisions}

        for merged_page in merged_pages:
            gating = decisions_by_idx.get(merged_page.page_index)

            page_output = PageOutput(
                index=merged_page.page_index,
                text_markdown=merged_page.text_content,
                gating=gating,
                vision=merged_page.vision_enrichment,
            )
            pages.append(page_output)

        return DocumentStructure(pages=pages)


# === Fonction utilitaire pour usage simple ===

async def extract_document(
    file_path: str,
    tenant_id: str = "default",
    enable_vision: bool = True,
) -> ExtractionResult:
    """
    Fonction utilitaire pour extraire un document.

    Usage simple:
        >>> result = await extract_document("/path/to/doc.pdf")
        >>> print(result.full_text)

    Args:
        file_path: Chemin vers le document
        tenant_id: Tenant pour DomainContext
        enable_vision: Activer Vision (defaut: True)

    Returns:
        ExtractionResult
    """
    config = PipelineConfig(
        tenant_id=tenant_id,
        enable_vision=enable_vision,
    )
    pipeline = ExtractionPipelineV2(config)
    return await pipeline.process_document(file_path)


__all__ = [
    "PipelineConfig",
    "PipelineMetrics",
    "ExtractionPipelineV2",
    "extract_document",
]
