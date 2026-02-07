# src/knowbase/claimfirst/composition/__init__.py
"""
Package composition — Chaînes compositionnelles S/P/O et enrichissement de slots.

Étape 0: ChainDetector — détection déterministe de chaînes intra-doc
Étape 1: SlotEnricher — enrichissement LLM des structured_form manquants
"""

from knowbase.claimfirst.composition.chain_detector import ChainDetector, ChainLink

__all__ = [
    "ChainDetector",
    "ChainLink",
    "SlotEnricher",
    "SlotEnrichmentResult",
]


def __getattr__(name):
    """Lazy imports pour SlotEnricher (dépendances lourdes)."""
    if name in ("SlotEnricher", "SlotEnrichmentResult"):
        from knowbase.claimfirst.composition.slot_enricher import (
            SlotEnricher,
            SlotEnrichmentResult,
        )
        globals()[name] = locals()[name]
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
