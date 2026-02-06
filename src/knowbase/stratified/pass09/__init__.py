"""
OSMOSE Pipeline V2 - Pass 0.9 Global View Construction
======================================================
Ref: doc/ongoing/ADR_PASS09_GLOBAL_VIEW_CONSTRUCTION.md

Construit une vue globale synthétique du document pour Pass 1.1/1.2.

Composants:
- GlobalViewBuilder: Orchestrateur principal
- SectionSummarizer: Résumé LLM par section
- HierarchicalCompressor: Compression en meta-document

Usage:
    from knowbase.stratified.pass09 import GlobalViewBuilder

    builder = GlobalViewBuilder(llm_client=llm_client)
    global_view = builder.build(
        doc_id="doc_123",
        sections=pass0_result.sections,
        chunks=chunks,
        full_text=full_text
    )

    # Utiliser dans Pass 1.1
    subject, themes, _ = document_analyzer.analyze(
        content=global_view.meta_document,
        ...
    )
"""

from knowbase.stratified.pass09.models import (
    SectionSummary,
    GlobalView,
    GlobalViewCoverage,
    Pass09Config,
    Zone,
)
from knowbase.stratified.pass09.global_view_builder import GlobalViewBuilder, build_global_view
from knowbase.stratified.pass09.section_summarizer import SectionSummarizer
from knowbase.stratified.pass09.hierarchical_compressor import HierarchicalCompressor

__all__ = [
    "GlobalViewBuilder",
    "build_global_view",
    "SectionSummarizer",
    "HierarchicalCompressor",
    "SectionSummary",
    "GlobalView",
    "GlobalViewCoverage",
    "Pass09Config",
    "Zone",
]
