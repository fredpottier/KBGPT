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
from knowbase.extraction_v2.context.doc_context_extractor import (
    DocContextExtractor,
    get_doc_context_extractor,
)
from knowbase.extraction_v2.context.models import DocumentContext
from knowbase.extraction_v2.extractors.docling_extractor import DoclingExtractor
from knowbase.extraction_v2.gating.engine import GatingEngine
from knowbase.structural import (
    StructuralGraphBuilder,
    StructuralGraphBuildResult,
    is_structural_graph_enabled,
)
from knowbase.extraction_v2.gating.weights import DEFAULT_GATING_WEIGHTS, GATING_THRESHOLDS
from knowbase.extraction_v2.vision.analyzer import VisionAnalyzer
from knowbase.extraction_v2.merge.merger import StructuredMerger, MergedPageOutput
from knowbase.extraction_v2.merge.linearizer import Linearizer
from knowbase.extraction_v2.cache.versioned_cache import VersionedCache
from knowbase.extraction_v2.tables.table_summarizer import TableSummarizer

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration du pipeline d'extraction V2."""

    # Activation des composants
    enable_vision: bool = True
    enable_gating: bool = True
    enable_doc_context: bool = True  # Extraction contexte documentaire (ADR_ASSERTION_AWARE_KG)
    enable_table_summaries: bool = True  # QW-1: Résumé LLM des tables pour améliorer RAG
    enable_structural_graph: bool = False  # Option C: Structural Graph depuis DoclingDocument

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

    # Options DocContext (ADR_ASSERTION_AWARE_KG)
    doc_context_use_llm: bool = True  # Utiliser LLM pour validation

    # Options Structural Graph (Option C)
    structural_graph_max_chunk_size: int = 3000  # Taille max chunks narratifs
    structural_graph_persist_neo4j: bool = True  # Persister dans Neo4j

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire."""
        return {
            "enable_vision": self.enable_vision,
            "enable_gating": self.enable_gating,
            "enable_doc_context": self.enable_doc_context,
            "enable_table_summaries": self.enable_table_summaries,
            "enable_structural_graph": self.enable_structural_graph,
            "vision_required_threshold": self.vision_required_threshold,
            "vision_recommended_threshold": self.vision_recommended_threshold,
            "vision_budget": self.vision_budget,
            "tenant_id": self.tenant_id,
            "use_cache": self.use_cache,
            "cache_version": self.cache_version,
            "vision_model": self.vision_model,
            "include_recommended_in_vision": self.include_recommended_in_vision,
            "max_concurrent_vision": self.max_concurrent_vision,
            "doc_context_use_llm": self.doc_context_use_llm,
            "structural_graph_max_chunk_size": self.structural_graph_max_chunk_size,
            "structural_graph_persist_neo4j": self.structural_graph_persist_neo4j,
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
    doc_context_time_ms: float = 0  # Temps extraction contexte
    table_summary_time_ms: float = 0  # QW-1: Temps résumé tables
    tables_summarized: int = 0  # QW-1: Nombre tables résumées
    structural_graph_time_ms: float = 0  # Option C: Temps construction graph
    structural_graph_items: int = 0  # Option C: Nombre DocItems créés
    structural_graph_chunks: int = 0  # Option C: Nombre TypeAwareChunks créés
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
            "doc_context_time_ms": round(self.doc_context_time_ms, 2),
            "table_summary_time_ms": round(self.table_summary_time_ms, 2),
            "tables_summarized": self.tables_summarized,
            "structural_graph_time_ms": round(self.structural_graph_time_ms, 2),
            "structural_graph_items": self.structural_graph_items,
            "structural_graph_chunks": self.structural_graph_chunks,
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
        self._doc_context_extractor: Optional[DocContextExtractor] = None
        self._table_summarizer: Optional[TableSummarizer] = None
        self._structural_graph_builder: Optional[StructuralGraphBuilder] = None

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

        # 5. Initialiser DocContextExtractor (ADR_ASSERTION_AWARE_KG)
        if self.config.enable_doc_context:
            self._doc_context_extractor = DocContextExtractor(
                use_llm=self.config.doc_context_use_llm,
            )

        # 6. Initialiser TableSummarizer (QW-1)
        if self.config.enable_table_summaries:
            self._table_summarizer = TableSummarizer(
                min_cells=4,   # Tables avec au moins 4 cellules
                max_cells=500, # Tronquer les très grandes tables
            )

        # 7. Initialiser StructuralGraphBuilder (Option C)
        if self.config.enable_structural_graph or is_structural_graph_enabled():
            self._structural_graph_builder = StructuralGraphBuilder(
                max_chunk_size=self.config.structural_graph_max_chunk_size,
                persist_artifacts=True,
            )
            logger.info("[ExtractionPipelineV2] StructuralGraphBuilder enabled")

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
                # Vérifier si le cache a un doc_context (ADR_ASSERTION_AWARE_KG)
                if cached_result.doc_context is None and self.config.enable_doc_context and self._doc_context_extractor:
                    # Cache ancien sans DocContext - extraire à la volée
                    logger.info(
                        f"[ExtractionPipelineV2] Cache HIT but missing DocContext: {document_id}, "
                        f"extracting context..."
                    )
                    try:
                        # Reconstruire pages_text depuis la structure cachee
                        # Chaque page a son text_markdown preserve
                        pages_text = [
                            page.text_markdown
                            for page in cached_result.structure.pages
                        ]

                        # Fallback si structure vide (anciens caches)
                        if not pages_text:
                            logger.warning(
                                f"[ExtractionPipelineV2] No page structure in cache, "
                                f"using full_text as single page"
                            )
                            pages_text = [cached_result.full_text]

                        doc_context = await self._doc_context_extractor.extract(
                            document_id=document_id,
                            filename=Path(file_path).name,
                            pages_text=pages_text,
                        )

                        # Mettre à jour le résultat avec le doc_context
                        cached_result.doc_context = doc_context

                        # Mettre à jour le cache
                        self._cache.set(document_id, file_path, cached_result)

                        logger.info(
                            f"[ExtractionPipelineV2] DocContext extracted for cached doc: "
                            f"{doc_context.doc_scope.value}, "
                            f"markers={doc_context.strong_markers + doc_context.weak_markers}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[ExtractionPipelineV2] DocContext extraction failed for cached doc: {e}"
                        )
                else:
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
        docling_document = None  # Pour Option C Structural Graph

        # Si Structural Graph activé, récupérer aussi le DoclingDocument brut
        if self._structural_graph_builder:
            units, docling_document = await self._extractor.extract_to_units_with_docling(file_path)
        else:
            units = await self._extractor.extract_to_units(file_path)

        metrics.extraction_time_ms = (time.time() - extraction_start) * 1000
        metrics.total_pages = len(units)

        logger.info(
            f"[ExtractionPipelineV2] Extracted {len(units)} pages in "
            f"{metrics.extraction_time_ms:.0f}ms"
            f"{' (with DoclingDocument for StructuralGraph)' if docling_document else ''}"
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

        # === ETAPE 4.5: Table Summaries (QW-1) ===
        if self.config.enable_table_summaries and self._table_summarizer:
            table_start = time.time()
            try:
                # Collecter toutes les tables des pages
                all_tables = []
                for page in merged_pages:
                    all_tables.extend(page.base_tables)

                if all_tables:
                    # Résumer en batch
                    summary_results = await self._table_summarizer.summarize_batch(
                        tables=all_tables,
                        max_concurrent=5,
                    )

                    # Appliquer les résumés aux TableData originales
                    for result in summary_results:
                        if result.success:
                            # Trouver la table et mettre à jour son summary
                            for page in merged_pages:
                                for table in page.base_tables:
                                    if table.table_id == result.table_id:
                                        table.summary = result.summary
                                        metrics.tables_summarized += 1
                                        break

                    metrics.table_summary_time_ms = (time.time() - table_start) * 1000

                    logger.info(
                        f"[ExtractionPipelineV2] Table summaries: {metrics.tables_summarized}/{len(all_tables)} "
                        f"tables summarized in {metrics.table_summary_time_ms:.0f}ms"
                    )
            except Exception as e:
                logger.warning(
                    f"[ExtractionPipelineV2] Table summary failed: {e}, continuing without summaries"
                )

        # === ETAPE 5: Linearisation ===
        full_text, page_index = self._linearizer.linearize(merged_pages)

        # === ETAPE 6: DocContext Extraction (ADR_ASSERTION_AWARE_KG) ===
        # Deux phases:
        # 6a. Générer DocumentContext (structure_hint, entity_hints) via generate_document_summary()
        # 6b. Extraire DocContextFrame avec filtrage via decide_marker()
        doc_context = None
        document_context_constraints: Optional[DocumentContext] = None

        if self.config.enable_doc_context and self._doc_context_extractor:
            doc_context_start = time.time()
            try:
                # Extraire le texte des pages pour le miner
                pages_text = [mp.text_content for mp in merged_pages]

                # === ETAPE 6a: Générer DocumentContext (ADR Document Context Markers) ===
                # Contient structure_hint, entity_hints pour filtrer les faux positifs
                try:
                    from knowbase.ingestion.osmose_enrichment import generate_document_summary
                    from knowbase.common.llm_router import get_llm_router

                    llm_router = get_llm_router()
                    _, _, document_context_constraints = await generate_document_summary(
                        document_id=document_id,
                        full_text=full_text,
                        llm_router=llm_router,
                    )

                    logger.info(
                        f"[ExtractionPipelineV2] DocumentContext generated: "
                        f"numbered_sections={document_context_constraints.structure_hint.has_numbered_sections}, "
                        f"entities={len(document_context_constraints.entity_hints)}"
                    )
                except Exception as ctx_err:
                    logger.warning(
                        f"[ExtractionPipelineV2] DocumentContext generation failed: {ctx_err}, "
                        f"continuing without context filtering"
                    )
                    document_context_constraints = None

                # === ETAPE 6b: Extraire DocContextFrame avec filtrage ===
                doc_context = await self._doc_context_extractor.extract(
                    document_id=document_id,
                    filename=Path(file_path).name,
                    pages_text=pages_text,
                    document_context=document_context_constraints,  # ADR: passer les contraintes
                )

                # Stocker le DocumentContext dans le DocContextFrame pour usage ultérieur
                if document_context_constraints is not None:
                    doc_context.document_context = document_context_constraints

                metrics.doc_context_time_ms = (time.time() - doc_context_start) * 1000

                logger.info(
                    f"[ExtractionPipelineV2] DocContext: {doc_context.doc_scope.value}, "
                    f"markers={doc_context.strong_markers + doc_context.weak_markers}, "
                    f"time={metrics.doc_context_time_ms:.0f}ms"
                )
            except Exception as e:
                logger.warning(
                    f"[ExtractionPipelineV2] DocContext extraction failed: {e}, "
                    f"continuing without context"
                )

        # === ETAPE 7: Structural Graph (Option C) ===
        structural_graph_result: Optional[StructuralGraphBuildResult] = None

        if self._structural_graph_builder and docling_document:
            structural_graph_start = time.time()
            try:
                structural_graph_result = self._structural_graph_builder.build_from_docling(
                    docling_document=docling_document,
                    tenant_id=effective_tenant,
                    doc_id=document_id,
                    source_uri=file_path,
                    pipeline_version="v2",
                )

                metrics.structural_graph_time_ms = (time.time() - structural_graph_start) * 1000
                metrics.structural_graph_items = structural_graph_result.item_count
                metrics.structural_graph_chunks = structural_graph_result.chunk_count

                logger.info(
                    f"[ExtractionPipelineV2] StructuralGraph built: "
                    f"{structural_graph_result.item_count} items, "
                    f"{structural_graph_result.section_count} sections, "
                    f"{structural_graph_result.chunk_count} chunks "
                    f"({structural_graph_result.narrative_chunk_count} narrative), "
                    f"time={metrics.structural_graph_time_ms:.0f}ms"
                )

                # Persister dans Neo4j si activé
                if self.config.structural_graph_persist_neo4j:
                    try:
                        persist_start = time.time()
                        self._structural_graph_builder.persist_to_neo4j_sync(structural_graph_result)
                        persist_time = (time.time() - persist_start) * 1000
                        metrics.structural_graph_time_ms += persist_time
                        logger.info(
                            f"[ExtractionPipelineV2] StructuralGraph persisted to Neo4j "
                            f"in {persist_time:.0f}ms"
                        )
                    except Exception as persist_error:
                        logger.warning(
                            f"[ExtractionPipelineV2] StructuralGraph Neo4j persistence failed: "
                            f"{persist_error}, continuing without persistence"
                        )

            except Exception as e:
                logger.warning(
                    f"[ExtractionPipelineV2] StructuralGraph build failed: {e}, "
                    f"continuing without structural graph"
                )

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

        # Construire les stats avec éventuellement le summary du structural graph
        result_stats = {
            "tenant_id": effective_tenant,
            "config": self.config.to_dict(),
            "metrics": metrics.to_dict(),
        }

        if structural_graph_result:
            # Sérialiser les chunks pour usage downstream (osmose_agentique)
            serialized_chunks = [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "kind": c.kind.value,
                    "page_no": c.page_no,
                    "section_id": c.section_id,
                    "item_ids": c.item_ids,
                    "is_relation_bearing": c.is_relation_bearing,
                    "doc_version_id": c.doc_version_id,
                }
                for c in structural_graph_result.chunks
            ]

            result_stats["structural_graph"] = {
                "item_count": structural_graph_result.item_count,
                "section_count": structural_graph_result.section_count,
                "chunk_count": structural_graph_result.chunk_count,
                "narrative_chunk_count": structural_graph_result.narrative_chunk_count,
                "doc_version_id": structural_graph_result.doc_version.doc_version_id,
                "structure_analysis": structural_graph_result.structure_analysis,
                "chunk_analysis": structural_graph_result.chunk_analysis,
                # Chunks sérialisés pour usage par osmose_agentique
                "chunks": serialized_chunks,
            }

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
            doc_context=doc_context,  # ADR_ASSERTION_AWARE_KG
            stats=result_stats,
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
