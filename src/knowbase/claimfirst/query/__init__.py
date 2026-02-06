# src/knowbase/claimfirst/query/__init__.py
"""
Module de requêtes avec scoping (INV-8) et requêtes temporelles.

Query-time scoping obligatoire pour réponses épistémiquement honnêtes.

Questions temporelles supportées:
A. Since when? - Depuis quand cette capability existe?
B. Still applicable? - Est-ce encore applicable aujourd'hui?
C. Context comparison? - Différences entre contextes A et B?
D. Text validation? - Ce texte est-il conforme au corpus?

INV-18: Disambiguation UI enrichie (sample + facets + entities)
INV-19: ClaimKey candidate pas de "since when" (timeline = validated only)
INV-23: Toute réponse cite explicitement ses claims sources
INV-24: IntentResolver ≥2 candidats sauf exact match lexical
"""

from knowbase.claimfirst.query.scoped_query import (
    ScopedQueryEngine,
    QueryResponse,
    QueryContext,
)
from knowbase.claimfirst.query.intent_resolver import (
    IntentResolver,
    TargetClaimIntent,
    DisambiguationOption,
)
from knowbase.claimfirst.query.latest_selector import (
    LatestSelector,
    LatestPolicy,
)
from knowbase.claimfirst.query.temporal_query_engine import (
    TemporalQueryEngine,
    SinceWhenResult,
    StillApplicableResult,
)
from knowbase.claimfirst.query.text_validator import (
    TextValidator,
    TextValidationResult,
    ValidationStatus,
)
from knowbase.claimfirst.query.uncertainty_signals import (
    UncertaintySignal,
    UncertaintySignalType,
    UncertaintyAnalysis,
)

__all__ = [
    # Scoped query (INV-8)
    "ScopedQueryEngine",
    "QueryResponse",
    "QueryContext",
    # Intent resolution (INV-18, INV-24)
    "IntentResolver",
    "TargetClaimIntent",
    "DisambiguationOption",
    # Latest selection (INV-20)
    "LatestSelector",
    "LatestPolicy",
    # Temporal query (INV-19, INV-23)
    "TemporalQueryEngine",
    "SinceWhenResult",
    "StillApplicableResult",
    # Text validation (INV-23)
    "TextValidator",
    "TextValidationResult",
    "ValidationStatus",
    # Uncertainty
    "UncertaintySignal",
    "UncertaintySignalType",
    "UncertaintyAnalysis",
]
