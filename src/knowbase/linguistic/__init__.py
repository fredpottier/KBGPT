"""
OSMOSE Linguistic Layer - Pass 0.5

Couche linguistique dédiée à la coréférence (anaphora resolution).

Cette couche :
- Ne modifie JAMAIS le texte source
- Persiste uniquement des liens entre spans textuels (MentionSpan, CorefLink)
- Est consommée par les passes sémantiques et d'extraction (Pass 1 / Pass 2+)
- Applique une politique conservative + abstention (aucun "best guess")

Architecture:
- coref_models.py    : Modèles de données (MentionSpan, CoreferenceChain, CorefDecision)
- coref_engine.py    : Interface ICorefEngine + implémentations (spaCy, Coreferee, rules)
- coref_gating.py    : Politique de gating (conservative + abstention)
- coref_persist.py   : Persistance Neo4j de la CorefGraph

Invariants Layer-level (L1-L5):
- L1: Evidence-preserving (span exact avec offsets)
- L2: No generated evidence (substitutions = runtime only)
- L3: Closed-world disambiguation (LLM ne choisit que parmi candidats locaux)
- L4: Abstention-first (ambiguïté, longue portée, bridging → ABSTAIN)
- L5: Linguistic-only (COREFERS_TO n'implique aucune relation conceptuelle)

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10
"""

# Models - Import lazy pour éviter les dépendances circulaires
from knowbase.linguistic.coref_models import (
    MentionSpan,
    MentionType,
    CoreferenceChain,
    CorefDecision,
    DecisionType,
    ReasonCode,
    CorefLink,
    CorefScope,
    CoreferenceCluster,
    CorefGraphResult,
)

# Gating - Politique conservative
from knowbase.linguistic.coref_gating import (
    CorefGatingPolicy,
    GatingResult,
    GatingCandidate,
    create_gating_policy,
)

# Engine - Interface et implémentations
from knowbase.linguistic.coref_engine import (
    ICorefEngine,
    RuleBasedEngine,
    SpacyCorefEngine,
    CorefereeEngine,
    get_engine_for_language,
    get_available_engines,
)

# Persistence - Neo4j
from knowbase.linguistic.coref_persist import CorefPersistence

# Named↔Named Gating (ADR_COREF_NAMED_NAMED_VALIDATION)
from knowbase.linguistic.coref_named_gating import (
    GatingDecision,
    NamedGatingResult,
    NamedNamedGatingPolicy,
    create_named_gating_policy,
)

# Cache pour décisions coréférence
from knowbase.linguistic.coref_cache import (
    CachedCorefDecision,
    CorefCache,
    get_coref_cache,
)

# LLM Arbiter pour zone grise
from knowbase.linguistic.coref_llm_arbiter import (
    CorefLLMDecision,
    CorefPair,
    CorefLLMArbiter,
    create_coref_arbiter,
)

__all__ = [
    # Models
    "MentionSpan",
    "MentionType",
    "CoreferenceChain",
    "CorefDecision",
    "DecisionType",
    "ReasonCode",
    "CorefLink",
    "CorefScope",
    "CoreferenceCluster",
    "CorefGraphResult",
    # Gating
    "CorefGatingPolicy",
    "GatingResult",
    "GatingCandidate",
    "create_gating_policy",
    # Engine
    "ICorefEngine",
    "RuleBasedEngine",
    "SpacyCorefEngine",
    "CorefereeEngine",
    "get_engine_for_language",
    "get_available_engines",
    # Persistence
    "CorefPersistence",
    # Named↔Named Gating
    "GatingDecision",
    "NamedGatingResult",
    "NamedNamedGatingPolicy",
    "create_named_gating_policy",
    # Cache
    "CachedCorefDecision",
    "CorefCache",
    "get_coref_cache",
    # LLM Arbiter
    "CorefLLMDecision",
    "CorefPair",
    "CorefLLMArbiter",
    "create_coref_arbiter",
]
