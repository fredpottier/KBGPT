"""
OSMOSE Navigation Layer

Couche de navigation non-sémantique pour le corpus.
ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md

Cette couche permet:
- Navigation corpus-level sans hallucination
- Exploration de contexte
- Émergence de hubs

IMPORTANT: Cette couche est strictement NON-SÉMANTIQUE.
Elle décrit le CORPUS, pas le MONDE.
Le RAG ne doit JAMAIS utiliser ces liens pour le raisonnement.

Author: Claude Code
Date: 2026-01-01
"""

from .types import (
    ContextNodeKind,
    ContextNode,
    DocumentContext,
    SectionContext,
    WindowContext,
    MentionedIn,
    NavigationLayerConfig,
)

from .navigation_layer_builder import (
    NavigationLayerBuilder,
    get_navigation_layer_builder,
)

from .graph_lint import (
    GraphLinter,
    LintResult,
    LintViolation,
    LintRuleId,
    validate_graph,
)

__all__ = [
    # Types
    "ContextNodeKind",
    "ContextNode",
    "DocumentContext",
    "SectionContext",
    "WindowContext",
    "MentionedIn",
    "NavigationLayerConfig",
    # Builder
    "NavigationLayerBuilder",
    "get_navigation_layer_builder",
    # Lint
    "GraphLinter",
    "LintResult",
    "LintViolation",
    "LintRuleId",
    "validate_graph",
]
