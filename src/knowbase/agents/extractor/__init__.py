"""
🤖 OSMOSE Agentique - Extractor Orchestrator

Agent spécialisé pour extraction concepts avec routing intelligent.

Responsabilités:
- Routing NO_LLM/SMALL/BIG basé sur complexité segment
- PrepassAnalyzer: NER spaCy pour estimer densité entities
- Budget-aware: Consomme budgets de façon optimale
- Fallback graceful: BIG → SMALL → NO_LLM si budget insuffisant

Phase 1.5 V1.1
"""

from .orchestrator import ExtractorOrchestrator

__all__ = ["ExtractorOrchestrator"]
