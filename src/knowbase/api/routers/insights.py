"""
🌊 OSMOSE Phase 2.3 - Router API pour les Insights (Découverte de Connaissances)

Endpoints pour l'InferenceEngine - Découverte de connaissances cachées dans le KG.

Types d'insights:
- Transitive Inference: Relations implicites via chaînes
- Bridge Concepts: Concepts connectant des clusters isolés
- Hidden Clusters: Communautés thématiques cachées
- Weak Signals: Concepts émergents sous-représentés
- Structural Holes: Relations manquantes prédites
- Contradictions: Assertions contradictoires
"""

from typing import List, Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from knowbase.semantic.inference import InferenceEngine, InsightType, DiscoveredInsight
from knowbase.api.dependencies import get_tenant_id
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "insights_router.log")

router = APIRouter(prefix="/insights", tags=["insights"])

# Singleton InferenceEngine (lazy initialized)
_inference_engine: Optional[InferenceEngine] = None


def get_inference_engine() -> InferenceEngine:
    """Retourne l'instance InferenceEngine (singleton)."""
    global _inference_engine
    if _inference_engine is None:
        _inference_engine = InferenceEngine()
    return _inference_engine


# =============================================================================
# SCHEMAS
# =============================================================================

class InsightTypeFilter(str, Enum):
    """Types d'insights pour filtrage API."""
    ALL = "all"
    TRANSITIVE = "transitive_inference"
    BRIDGE = "bridge_concept"
    CLUSTER = "hidden_cluster"
    WEAK_SIGNAL = "weak_signal"
    STRUCTURAL_HOLE = "structural_hole"
    CONTRADICTION = "contradiction"


class InsightResponse(BaseModel):
    """Réponse pour un insight découvert."""
    insight_id: str
    insight_type: str
    title: str
    description: str
    concepts_involved: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    evidence_path: List[str] = []
    supporting_documents: List[str] = []
    discovered_at: str

    class Config:
        json_schema_extra = {
            "example": {
                "insight_id": "insight_tran_000001",
                "insight_type": "transitive_inference",
                "title": "Relation REQUIRES transitive découverte",
                "description": "'COVID-19' requires 'Informed Consent' via 'Patients'",
                "concepts_involved": ["COVID-19", "Patients", "Informed Consent"],
                "confidence": 0.85,
                "importance": 0.7,
                "evidence_path": [
                    "COVID-19 → Patients (conf: 0.9)",
                    "Patients → Informed Consent (conf: 0.8)"
                ],
                "supporting_documents": [],
                "discovered_at": "2025-12-18T18:00:00"
            }
        }


class InsightsListResponse(BaseModel):
    """Réponse pour liste d'insights."""
    total: int
    insights: List[InsightResponse]
    insight_types_count: dict


class GraphStatsResponse(BaseModel):
    """Statistiques du graphe pour inférence."""
    tenant_id: str
    nodes: int
    edges: int
    density: float
    networkx_available: bool
    potential_insights: dict


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "",
    response_model=InsightsListResponse,
    summary="Découvrir tous les insights",
    description="""
    🌊 **OSMOSE Phase 2.3 - Découverte de Connaissances Cachées**

    Découvre des insights non triviaux dans le Knowledge Graph:

    - **Transitive Inference**: Relations implicites (A→B→C donc A→C)
    - **Bridge Concepts**: Concepts connectant des clusters
    - **Hidden Clusters**: Communautés thématiques cachées
    - **Weak Signals**: Concepts émergents sous-représentés
    - **Structural Holes**: Relations manquantes prédites
    - **Contradictions**: Assertions contradictoires

    **Différenciation vs RAG simple**:
    Ces insights ne seraient JAMAIS trouvés par une recherche vectorielle classique.
    Ils exploitent la structure du graphe de connaissances.
    """
)
async def discover_insights(
    insight_type: InsightTypeFilter = Query(
        default=InsightTypeFilter.ALL,
        description="Type d'insight à découvrir (all = tous)"
    ),
    max_per_type: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Nombre max d'insights par type"
    ),
    min_confidence: float = Query(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Confiance minimum pour inclusion"
    ),
    tenant_id: str = Depends(get_tenant_id),
):
    """Découvre les insights dans le KG."""
    engine = get_inference_engine()

    try:
        # Déterminer les types à découvrir
        if insight_type == InsightTypeFilter.ALL:
            types_to_discover = [
                InsightType.TRANSITIVE_INFERENCE,
                InsightType.BRIDGE_CONCEPT,
                InsightType.HIDDEN_CLUSTER,
                InsightType.WEAK_SIGNAL,
            ]
        else:
            types_to_discover = [InsightType(insight_type.value)]

        # Découvrir les insights
        insights = await engine.discover_all_insights(
            tenant_id=tenant_id,
            insight_types=types_to_discover,
            max_insights_per_type=max_per_type
        )

        # Filtrer par confiance
        filtered = [i for i in insights if i.confidence >= min_confidence]

        # Compter par type
        type_counts = {}
        for insight in filtered:
            t = insight.insight_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        # Convertir en réponses
        responses = [
            InsightResponse(
                insight_id=i.insight_id,
                insight_type=i.insight_type.value,
                title=i.title,
                description=i.description,
                concepts_involved=i.concepts_involved,
                confidence=i.confidence,
                importance=i.importance,
                evidence_path=i.evidence_path,
                supporting_documents=i.supporting_documents,
                discovered_at=i.discovered_at.isoformat()
            )
            for i in filtered
        ]

        logger.info(
            f"[INSIGHTS] Discovered {len(responses)} insights for tenant={tenant_id}"
        )

        return InsightsListResponse(
            total=len(responses),
            insights=responses,
            insight_types_count=type_counts
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Discovery failed: {e}")
        raise HTTPException(status_code=500, detail=f"Insight discovery failed: {str(e)}")


@router.get(
    "/transitive",
    response_model=InsightsListResponse,
    summary="Découvrir relations transitives",
    description="""
    Découvre les relations transitives implicites dans le KG.

    Exemple: Si A REQUIRES B et B REQUIRES C, alors A REQUIRES C (indirectement).

    **Relations transitives supportées**:
    - REQUIRES (dépendances)
    - PART_OF (hiérarchies)
    - SUBTYPE_OF (taxonomies)
    """
)
async def discover_transitive(
    relation_types: Optional[str] = Query(
        default=None,
        description="Types de relations (comma-separated): REQUIRES,PART_OF,SUBTYPE_OF"
    ),
    max_results: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
):
    """Découvre les relations transitives."""
    engine = get_inference_engine()

    try:
        rel_types = None
        if relation_types:
            rel_types = [r.strip() for r in relation_types.split(",")]

        insights = await engine.discover_transitive_relations(
            tenant_id=tenant_id,
            relation_types=rel_types,
            max_results=max_results
        )

        responses = [
            InsightResponse(
                insight_id=i.insight_id,
                insight_type=i.insight_type.value,
                title=i.title,
                description=i.description,
                concepts_involved=i.concepts_involved,
                confidence=i.confidence,
                importance=i.importance,
                evidence_path=i.evidence_path,
                supporting_documents=i.supporting_documents,
                discovered_at=i.discovered_at.isoformat()
            )
            for i in insights
        ]

        return InsightsListResponse(
            total=len(responses),
            insights=responses,
            insight_types_count={"transitive_inference": len(responses)}
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Transitive discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/bridges",
    response_model=InsightsListResponse,
    summary="Découvrir concepts ponts",
    description="""
    Découvre les concepts "ponts" qui connectent des clusters sinon isolés.

    Utilise Betweenness Centrality: mesure combien de plus courts chemins
    passent par un concept.

    **Use Case**: Identifier les concepts clés qui relient différents domaines.
    """
)
async def discover_bridges(
    min_betweenness: float = Query(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Score betweenness minimum"
    ),
    max_results: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(get_tenant_id),
):
    """Découvre les concepts ponts."""
    engine = get_inference_engine()

    try:
        insights = await engine.discover_bridge_concepts(
            tenant_id=tenant_id,
            min_betweenness=min_betweenness,
            max_results=max_results
        )

        responses = [
            InsightResponse(
                insight_id=i.insight_id,
                insight_type=i.insight_type.value,
                title=i.title,
                description=i.description,
                concepts_involved=i.concepts_involved,
                confidence=i.confidence,
                importance=i.importance,
                evidence_path=i.evidence_path,
                supporting_documents=i.supporting_documents,
                discovered_at=i.discovered_at.isoformat()
            )
            for i in insights
        ]

        return InsightsListResponse(
            total=len(responses),
            insights=responses,
            insight_types_count={"bridge_concept": len(responses)}
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Bridge discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/clusters",
    response_model=InsightsListResponse,
    summary="Découvrir clusters cachés",
    description="""
    Découvre des communautés thématiques cachées dans le KG.

    Utilise l'algorithme de détection de communautés (Louvain-like) pour
    identifier des groupes de concepts fortement interconnectés.

    **Use Case**: Révéler des thèmes émergents non documentés explicitement.
    """
)
async def discover_clusters(
    max_results: int = Query(default=10, ge=1, le=50),
    tenant_id: str = Depends(get_tenant_id),
):
    """Découvre les clusters thématiques cachés."""
    engine = get_inference_engine()

    try:
        insights = await engine.discover_hidden_clusters(
            tenant_id=tenant_id,
            max_results=max_results
        )

        responses = [
            InsightResponse(
                insight_id=i.insight_id,
                insight_type=i.insight_type.value,
                title=i.title,
                description=i.description,
                concepts_involved=i.concepts_involved[:20],  # Limiter pour réponse
                confidence=i.confidence,
                importance=i.importance,
                evidence_path=i.evidence_path,
                supporting_documents=i.supporting_documents,
                discovered_at=i.discovered_at.isoformat()
            )
            for i in insights
        ]

        return InsightsListResponse(
            total=len(responses),
            insights=responses,
            insight_types_count={"hidden_cluster": len(responses)}
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Cluster discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/weak-signals",
    response_model=InsightsListResponse,
    summary="Découvrir signaux faibles",
    description="""
    Découvre des concepts émergents (weak signals).

    **Définition**: Concept avec faible fréquence mais haute connectivité.
    Ces concepts sont potentiellement importants mais sous-documentés.

    **Use Case**: Anticiper des tendances émergentes avant qu'elles ne deviennent mainstream.
    """
)
async def discover_weak_signals(
    max_results: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(get_tenant_id),
):
    """Découvre les signaux faibles."""
    engine = get_inference_engine()

    try:
        insights = await engine.discover_weak_signals(
            tenant_id=tenant_id,
            max_results=max_results
        )

        responses = [
            InsightResponse(
                insight_id=i.insight_id,
                insight_type=i.insight_type.value,
                title=i.title,
                description=i.description,
                concepts_involved=i.concepts_involved,
                confidence=i.confidence,
                importance=i.importance,
                evidence_path=i.evidence_path,
                supporting_documents=i.supporting_documents,
                discovered_at=i.discovered_at.isoformat()
            )
            for i in insights
        ]

        return InsightsListResponse(
            total=len(responses),
            insights=responses,
            insight_types_count={"weak_signal": len(responses)}
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Weak signal discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/structural-holes",
    response_model=InsightsListResponse,
    summary="Découvrir trous structurels",
    description="""
    Découvre des relations manquantes prédites par les patterns du KG.

    Utilise des heuristiques de Link Prediction (Adamic-Adar, Common Neighbors).

    **Use Case**: Suggérer des connexions potentielles entre concepts.
    """
)
async def discover_structural_holes(
    max_results: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(get_tenant_id),
):
    """Découvre les trous structurels."""
    engine = get_inference_engine()

    try:
        insights = await engine.discover_structural_holes(
            tenant_id=tenant_id,
            max_results=max_results
        )

        responses = [
            InsightResponse(
                insight_id=i.insight_id,
                insight_type=i.insight_type.value,
                title=i.title,
                description=i.description,
                concepts_involved=i.concepts_involved,
                confidence=i.confidence,
                importance=i.importance,
                evidence_path=i.evidence_path,
                supporting_documents=i.supporting_documents,
                discovered_at=i.discovered_at.isoformat()
            )
            for i in insights
        ]

        return InsightsListResponse(
            total=len(responses),
            insights=responses,
            insight_types_count={"structural_hole": len(responses)}
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Structural hole discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/stats",
    response_model=GraphStatsResponse,
    summary="Statistiques du graphe",
    description="""
    Retourne des statistiques sur le graphe de connaissances
    et le potentiel d'inférence.
    """
)
async def get_graph_stats(
    tenant_id: str = Depends(get_tenant_id),
):
    """Retourne les statistiques du graphe."""
    engine = get_inference_engine()

    try:
        stats = await engine.get_inference_stats(tenant_id=tenant_id)

        return GraphStatsResponse(
            tenant_id=stats["tenant_id"],
            nodes=stats["graph_stats"]["nodes"],
            edges=stats["graph_stats"]["edges"],
            density=stats["graph_stats"]["density"],
            networkx_available=stats["networkx_available"],
            potential_insights=stats.get("potential_insights", {})
        )

    except Exception as e:
        logger.error(f"[INSIGHTS] Stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/clear-cache",
    summary="Vider le cache du graphe",
    description="Vide le cache NetworkX pour forcer la reconstruction du graphe."
)
async def clear_cache():
    """Vide le cache du graphe NetworkX."""
    engine = get_inference_engine()
    engine.clear_cache()
    return {"status": "ok", "message": "Cache cleared"}
