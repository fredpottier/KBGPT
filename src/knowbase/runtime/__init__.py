"""
OSMOSIS Runtime V1.1 — couche d'exploitation au-dessus du KG V3.3.

Architecture (cf. RUNTIME_EXPLOITATION_ARCHITECTURE.md V1.1) :

    Query
      ↓
    QueryResolver (détecte mode parmi 7 modes V1.1)
      ↓
    EvidencePlanner (sélectionne régime : RAG_LED / KG_LED / HYBRID)
      ↓ + auto-escalation RAG_LED → KG_LED si signaux structurels
    Retrieval (Qdrant + Cypher LOGICAL_RELATION typé + TemporalRetriever)
      ↓
    TrustEvaluator (kg_trust score, 4 seuils)
      ↓
    ResponseComposer (5 sections obligatoires + bloc métier modulable)

Les 7 modes V1.1 :
- LOOKUP_FACTUAL          : "Quel est X ?" — RAG_LED par défaut
- APPLICABILITY_QUERY      : "Quelles règles s'appliquent à X ?" — KG_LED
- SNAPSHOT_TEMPORAL        : "Quelle était la règle au [date] ?" — KG_LED
- DIFF_EVOLUTION           : "Qu'a changé entre [date] et [date] ?" — KG_LED
- CONFLICT_RISK            : "Quelles contradictions sur X ?" — KG_LED
- EXPLORATION_RELATIONAL   : "Quels termes définis dans le corpus ?" — KG_LED
- SYNTHESIS_SUMMARY        : "Résume le doc X" — HYBRID

Les 3 régimes V1.1 (orthogonaux aux modes) :
- RAG_LED  : Qdrant dirige le retrieval, KG annote (lifecycle, supersession)
- KG_LED   : KG dirige (Cypher traversal sur relations typées), RAG fournit passages
- HYBRID   : RAG + KG en parallèle, fusion downstream
"""

from knowbase.runtime.query_resolver import QueryResolver, ResponseMode, ResolvedQuery
from knowbase.runtime.evidence_planner import EvidencePlanner, Regime, RetrievalPlan
from knowbase.runtime.trust_evaluator import TrustEvaluator, TrustLevel, TrustScore
from knowbase.runtime.response_composer import ResponseComposer, ComposedResponse

__all__ = [
    "QueryResolver",
    "ResponseMode",
    "ResolvedQuery",
    "EvidencePlanner",
    "Regime",
    "RetrievalPlan",
    "TrustEvaluator",
    "TrustLevel",
    "TrustScore",
    "ResponseComposer",
    "ComposedResponse",
]
