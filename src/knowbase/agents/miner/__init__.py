"""
🤖 OSMOSE Agentique - Pattern Miner

Agent spécialisé pour détection patterns cross-segments.

Responsabilités:
- Détection patterns récurrents entre segments
- Cross-document concept linking
- Hierarchy inference (parent-child relations)
- Named Entity disambiguation

Phase 1.5 V1.1
"""

from .miner import PatternMiner

__all__ = ["PatternMiner"]
