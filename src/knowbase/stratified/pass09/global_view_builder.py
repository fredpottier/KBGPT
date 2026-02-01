"""
OSMOSE Pipeline V2 - Pass 0.9 Global View Builder
=================================================
Orchestrateur principal pour la construction de la vue globale.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

from knowbase.stratified.pass09.hierarchical_compressor import HierarchicalCompressor
from knowbase.stratified.pass09.models import GlobalView, GlobalViewCoverage, Pass09Config
from knowbase.stratified.pass09.section_summarizer import SectionSummarizer

logger = logging.getLogger(__name__)


class GlobalViewBuilder:
    """
    Orchestrateur pour Pass 0.9 - Global View Construction.

    Construit une vue globale synthétique du document pour Pass 1.1/1.2.

    Usage:
        builder = GlobalViewBuilder(llm_client=llm_client)
        global_view = await builder.build(
            doc_id="doc_123",
            tenant_id="default",
            sections=pass0_result.sections,
            chunks=chunks,
            doc_title="Mon Document"
        )

        # Utiliser dans Pass 1.1
        document_analyzer.analyze(content=global_view.meta_document, ...)
    """

    def __init__(
        self,
        llm_client: Any = None,
        config: Optional[Pass09Config] = None,
    ):
        """
        Initialise le GlobalViewBuilder.

        Args:
            llm_client: Client LLM pour les résumés (optionnel, fallback si absent)
            config: Configuration Pass 0.9
        """
        self.llm_client = llm_client
        self.config = config or Pass09Config()

        self.summarizer = SectionSummarizer(
            llm_client=llm_client,
            config=self.config,
        ) if llm_client else None

        self.compressor = HierarchicalCompressor(config=self.config)

    async def build(
        self,
        doc_id: str,
        tenant_id: str,
        sections: List[Dict],
        chunks: Dict[str, str],
        doc_title: str = "",
        full_text: str = "",
    ) -> GlobalView:
        """
        Construit la vue globale du document.

        Args:
            doc_id: ID du document
            tenant_id: ID du tenant
            sections: Liste des sections (depuis Pass 0)
            chunks: Mapping chunk_id -> texte
            doc_title: Titre du document
            full_text: Texte complet (optionnel, pour fallback)

        Returns:
            GlobalView avec meta_document et section_summaries
        """
        start_time = time.time()
        logger.info(f"[OSMOSE:Pass0.9] Building global view for {doc_id}...")
        logger.info(f"[OSMOSE:Pass0.9] Input: {len(sections)} sections, {len(chunks)} chunks")

        # Extraire les textes par section
        section_texts = self._extract_section_texts(sections, chunks, full_text)
        logger.info(f"[OSMOSE:Pass0.9] Extracted text for {len(section_texts)} sections")

        # Décider si on utilise LLM ou fallback
        if self.summarizer and self.llm_client:
            global_view = await self._build_with_llm(
                doc_id=doc_id,
                tenant_id=tenant_id,
                sections=sections,
                section_texts=section_texts,
                doc_title=doc_title,
            )
        else:
            logger.warning("[OSMOSE:Pass0.9] No LLM client, using fallback mode")
            global_view = self._build_fallback(
                doc_id=doc_id,
                tenant_id=tenant_id,
                sections=sections,
                section_texts=section_texts,
                doc_title=doc_title,
            )

        # Finaliser les métadonnées
        global_view.build_time_seconds = time.time() - start_time

        # Valider
        if global_view.is_valid(self.config):
            logger.info(
                f"[OSMOSE:Pass0.9] Global view built successfully: "
                f"{len(global_view.meta_document)} chars, "
                f"{global_view.coverage.coverage_ratio:.1%} coverage, "
                f"{global_view.build_time_seconds:.1f}s"
            )
        else:
            logger.warning(
                f"[OSMOSE:Pass0.9] Global view validation failed: "
                f"coverage={global_view.coverage.coverage_ratio:.1%}, "
                f"size={len(global_view.meta_document)}"
            )
            global_view.errors.append("Validation failed")

        return global_view

    def build_sync(
        self,
        doc_id: str,
        tenant_id: str,
        sections: List[Dict],
        chunks: Dict[str, str],
        doc_title: str = "",
        full_text: str = "",
    ) -> GlobalView:
        """
        Version synchrone de build() pour compatibilité avec FastAPI.

        Utilise le LLM via l'interface synchrone .generate() (Pass1LLMWrapper)
        qui route vers vLLM/Qwen en burst, GPT-4o-mini sinon.
        Fallback sur troncature si pas de client LLM.
        """
        start_time = time.time()
        logger.info(f"[OSMOSE:Pass0.9] Building global view (sync) for {doc_id}...")
        logger.info(f"[OSMOSE:Pass0.9] Input: {len(sections)} sections, {len(chunks)} chunks")

        # Extraire les textes par section
        section_texts = self._extract_section_texts(sections, chunks, full_text)
        logger.info(f"[OSMOSE:Pass0.9] Extracted text for {len(section_texts)} sections")

        # Utiliser LLM synchrone si disponible (.generate() = Pass1LLMWrapper → LLMRouter)
        if self.summarizer and self.llm_client and hasattr(self.llm_client, "generate"):
            global_view = self._build_with_llm_sync(
                doc_id=doc_id,
                tenant_id=tenant_id,
                sections=sections,
                section_texts=section_texts,
                doc_title=doc_title,
            )
        else:
            logger.warning("[OSMOSE:Pass0.9] No sync LLM client, using fallback mode")
            global_view = self._build_fallback(
                doc_id=doc_id,
                tenant_id=tenant_id,
                sections=sections,
                section_texts=section_texts,
                doc_title=doc_title,
            )

        global_view.build_time_seconds = time.time() - start_time

        if global_view.is_valid(self.config):
            logger.info(
                f"[OSMOSE:Pass0.9] Global view built successfully (sync): "
                f"{len(global_view.meta_document)} chars, "
                f"{global_view.coverage.coverage_ratio:.1%} coverage, "
                f"{global_view.build_time_seconds:.1f}s"
            )
        else:
            logger.warning(
                f"[OSMOSE:Pass0.9] Global view validation failed: "
                f"coverage={global_view.coverage.coverage_ratio:.1%}, "
                f"size={len(global_view.meta_document)}"
            )

        return global_view

    def _build_with_llm_sync(
        self,
        doc_id: str,
        tenant_id: str,
        sections: List[Dict],
        section_texts: Dict[str, str],
        doc_title: str,
    ) -> GlobalView:
        """Construit la vue globale avec résumés LLM synchrones (via LLMRouter)."""

        max_workers = self.config.max_concurrent_summaries
        logger.info(
            f"[OSMOSE:Pass0.9] Summarizing {len(sections)} sections via LLMRouter "
            f"(sync, {max_workers} workers)..."
        )

        section_summaries = {}
        sections_order = []

        # Préparer les tâches
        tasks = []
        for section in sections:
            section_id = section.get("id") or section.get("section_id")
            section_title = section.get("title") or section.get("name", "Sans titre")
            level = section.get("level", 1)
            text = section_texts.get(section_id, "")
            sections_order.append(section_id)
            tasks.append((section_id, section_title, level, text))

        # Exécuter en parallèle via ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self.summarizer.summarize_one_section_sync,
                    section_id=sid,
                    section_title=stitle,
                    level=lvl,
                    text=txt,
                ): sid
                for sid, stitle, lvl, txt in tasks
            }

            for future in as_completed(futures):
                section_id = futures[future]
                try:
                    result = future.result()
                    if result:
                        section_summaries[section_id] = result
                except Exception as e:
                    logger.warning(f"[OSMOSE:Pass0.9] Error summarizing {section_id}: {e}")

        # Stats
        summarizer_stats = self.summarizer.stats
        logger.info(
            f"[OSMOSE:Pass0.9] Summarized {summarizer_stats.get('sections_processed', 0)} sections via LLM "
            f"(skipped: {summarizer_stats.get('sections_skipped', 0)}, "
            f"verbatim: {summarizer_stats.get('sections_verbatim', 0)})"
        )

        # Compresser en meta-document
        meta_document, toc_enhanced, coverage = self.compressor.compress(
            section_summaries=section_summaries,
            sections_order=sections_order,
            doc_title=doc_title,
        )

        return GlobalView(
            tenant_id=tenant_id,
            doc_id=doc_id,
            meta_document=meta_document,
            section_summaries=section_summaries,
            toc_enhanced=toc_enhanced,
            coverage=coverage,
            created_at=datetime.utcnow(),
            llm_model_used="via_llm_router",
            total_llm_calls=summarizer_stats.get("sections_processed", 0),
            total_tokens_used=summarizer_stats.get("total_tokens_in", 0)
            + summarizer_stats.get("total_tokens_out", 0),
            is_fallback=False,
            errors=summarizer_stats.get("errors", []),
        )

    def _extract_section_texts(
        self,
        sections: List[Dict],
        chunks: Dict[str, str],
        full_text: str,
    ) -> Dict[str, str]:
        """
        Extrait le texte de chaque section.

        Stratégie:
        1. Si sections ont `text` direct -> utiliser
        2. Si sections ont `chunk_ids` -> concaténer les chunks
        3. Sinon -> découper full_text par positions
        """
        section_texts = {}

        for section in sections:
            section_id = section.get("id") or section.get("section_id")

            # Cas 1: texte direct
            if section.get("text"):
                section_texts[section_id] = section["text"]
                continue

            # Cas 2: chunk_ids référencés
            chunk_ids = section.get("chunk_ids", [])
            if chunk_ids:
                texts = [chunks.get(cid, "") for cid in chunk_ids]
                section_texts[section_id] = "\n".join(filter(None, texts))
                continue

            # Cas 3: items référencés (DocItems)
            item_ids = section.get("item_ids", [])
            if item_ids and chunks:
                # Les chunks peuvent être indexés par item_id
                texts = [chunks.get(iid, "") for iid in item_ids]
                section_texts[section_id] = "\n".join(filter(None, texts))
                continue

            # Cas 4: positions dans full_text
            start = section.get("start_pos", 0)
            end = section.get("end_pos", 0)
            if full_text and end > start:
                section_texts[section_id] = full_text[start:end]
                continue

            # Cas 5: aucun texte trouvé
            section_texts[section_id] = ""

        return section_texts

    async def _build_with_llm(
        self,
        doc_id: str,
        tenant_id: str,
        sections: List[Dict],
        section_texts: Dict[str, str],
        doc_title: str,
    ) -> GlobalView:
        """Construit la vue globale avec résumés LLM."""

        # Résumer les sections
        section_summaries = await self.summarizer.summarize_sections(
            sections=sections,
            section_texts=section_texts,
        )

        # Construire l'ordre des sections
        sections_order = [
            s.get("id") or s.get("section_id")
            for s in sections
        ]

        # Compresser en meta-document
        meta_document, toc_enhanced, coverage = self.compressor.compress(
            section_summaries=section_summaries,
            sections_order=sections_order,
            doc_title=doc_title,
        )

        # Stats du summarizer
        summarizer_stats = self.summarizer.stats

        return GlobalView(
            tenant_id=tenant_id,
            doc_id=doc_id,
            meta_document=meta_document,
            section_summaries=section_summaries,
            toc_enhanced=toc_enhanced,
            coverage=coverage,
            created_at=datetime.utcnow(),
            llm_model_used="gpt-4o-mini",
            total_llm_calls=summarizer_stats.get("sections_processed", 0),
            total_tokens_used=summarizer_stats.get("total_tokens_in", 0)
            + summarizer_stats.get("total_tokens_out", 0),
            is_fallback=False,
            errors=summarizer_stats.get("errors", []),
        )

    def _build_fallback(
        self,
        doc_id: str,
        tenant_id: str,
        sections: List[Dict],
        section_texts: Dict[str, str],
        doc_title: str,
    ) -> GlobalView:
        """
        Construit la vue globale en mode fallback (sans LLM).

        Stratégie: TOC + premiers N caractères de chaque section.
        """
        from knowbase.stratified.pass09.models import SectionSummary

        logger.info("[OSMOSE:Pass0.9] Building fallback global view (no LLM)...")

        section_summaries = {}
        sections_order = []

        for section in sections:
            section_id = section.get("id") or section.get("section_id")
            section_title = section.get("title") or section.get("name", "Sans titre")
            level = section.get("level", 1)
            text = section_texts.get(section_id, "")

            sections_order.append(section_id)

            # Tronquer le texte
            max_chars = self.config.fallback_chars_per_section
            if len(text) > max_chars:
                truncated = text[:max_chars] + "..."
            else:
                truncated = text

            section_summaries[section_id] = SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=truncated,
                concepts_mentioned=[],
                assertion_types=[],
                key_values=[],
                char_count_original=len(text),
                char_count_summary=len(truncated),
                method="truncated",
            )

        # Compresser
        meta_document, toc_enhanced, coverage = self.compressor.compress(
            section_summaries=section_summaries,
            sections_order=sections_order,
            doc_title=doc_title,
        )

        return GlobalView(
            tenant_id=tenant_id,
            doc_id=doc_id,
            meta_document=meta_document,
            section_summaries=section_summaries,
            toc_enhanced=toc_enhanced,
            coverage=coverage,
            created_at=datetime.utcnow(),
            llm_model_used="",
            total_llm_calls=0,
            total_tokens_used=0,
            is_fallback=True,
            errors=[],
        )


# Convenience function
async def build_global_view(
    doc_id: str,
    tenant_id: str,
    sections: List[Dict],
    chunks: Dict[str, str],
    llm_client: Any = None,
    doc_title: str = "",
    config: Optional[Pass09Config] = None,
) -> GlobalView:
    """
    Fonction utilitaire pour construire une vue globale.

    Usage:
        from knowbase.stratified.pass09 import build_global_view

        global_view = await build_global_view(
            doc_id="doc_123",
            tenant_id="default",
            sections=sections,
            chunks=chunks,
            llm_client=openai_client,
        )
    """
    builder = GlobalViewBuilder(llm_client=llm_client, config=config)
    return await builder.build(
        doc_id=doc_id,
        tenant_id=tenant_id,
        sections=sections,
        chunks=chunks,
        doc_title=doc_title,
    )
