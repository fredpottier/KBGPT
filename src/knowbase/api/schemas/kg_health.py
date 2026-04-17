"""
Schemas Pydantic pour l'API KG Health.

Le KG Health Score produit un diagnostic multi-axes de la qualite du Knowledge
Graph sans dependre du corpus de questions. Il expose :
- un score global 0-100
- 4 familles (Provenance, Structure, Distribution, Coherence)
- des metriques normalisees avec seuils calibres
- des actionables (top docs mal extraits, hubs anormaux, etc.)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Metrique unitaire ──────────────────────────────────────────────────


class MetricStatus(BaseModel):
    """Classification qualitative d'une metrique selon les seuils."""

    zone: str = Field(..., description="green | yellow | red")
    label: str = Field(..., description="Libelle humain : Bon / A surveiller / Critique")


class Metric(BaseModel):
    """Une metrique individuelle du Health Score."""

    key: str = Field(..., description="Identifiant technique (ex: claim_facet_linkage)")
    label: str = Field(..., description="Libelle humain affiche dans l'UI")
    description: str = Field(..., description="Phrase explicative de ce que mesure la metrique")
    value: float = Field(..., description="Valeur normalisee [0.0, 1.0]")
    display_value: str = Field(..., description="Valeur formatee pour affichage (ex: '25.4%')")
    raw: Optional[float] = Field(None, description="Valeur brute si differente du display")
    weight: float = Field(..., description="Poids dans le score de la famille [0.0, 1.0]")
    status: MetricStatus
    drilldown_available: bool = Field(False, description="True si un drill-down est expose pour cette metrique")
    drilldown_key: Optional[str] = Field(None, description="Cle a passer a l'endpoint /drilldown")


# ── Famille de metriques ───────────────────────────────────────────────


class FamilyScore(BaseModel):
    """Agregat d'un axe du Health Score (Provenance, Structure, Distribution, Coherence)."""

    name: str = Field(..., description="provenance | structure | distribution | coherence")
    label: str = Field(..., description="Libelle humain de la famille")
    score: float = Field(..., description="Score de la famille [0, 100]")
    status: MetricStatus
    weight: float = Field(..., description="Poids de la famille dans le score global")
    metrics: List[Metric]


# ── Actionables (widgets contextuels bas de page) ──────────────────────


class DocLinkageRow(BaseModel):
    """Ligne du top des documents mal extraits (linkage faible)."""

    doc_id: str
    claims_total: int
    linkage_rate: float = Field(..., description="Taux claim->facet pour ce doc [0, 1]")
    subject_status: str = Field(..., description="resolved | unresolved | MISSING_CONTEXT")


class HubRow(BaseModel):
    """Ligne du top des entites dominantes (candidate hub anomaly)."""

    entity: str
    claims: int
    share_pct: float = Field(..., description="Part sur total claims [0, 100]")


class SingletonStats(BaseModel):
    """Vue agregee des nodes isoles (composante = 1 node)."""

    total_components: int
    singletons: int
    singleton_rate: float = Field(..., description="Part de singletons sur composantes totales")
    giant_component_size: int
    giant_component_pct: float


class ActionablesPanel(BaseModel):
    """Panneau 'actionables' affiche en bas de page pour guider la remediation."""

    worst_docs: List[DocLinkageRow] = Field(default_factory=list, description="Top 10 docs avec linkage le plus faible")
    top_hubs: List[HubRow] = Field(default_factory=list, description="Entites > 5% de part (potentiel hub anomaly)")
    singleton_stats: Optional[SingletonStats] = None
    perspective_status: Optional[str] = Field(None, description="fresh | warning | stale | no_perspectives")
    perspective_new_claims: int = 0


# ── Reponse principale ─────────────────────────────────────────────────


class KGHealthCorpusSummary(BaseModel):
    """Statistiques haut-niveau affichees dans les cards du header."""

    total_claims: int = 0
    total_entities: int = 0
    total_facets: int = 0
    total_documents: int = 0
    total_contradictions: int = 0


class KGHealthScoreResponse(BaseModel):
    """Reponse complete du endpoint /api/kg-health/score."""

    global_score: float = Field(..., description="Score global pondere [0, 100]")
    global_status: MetricStatus
    families: List[FamilyScore]
    summary: KGHealthCorpusSummary
    actionables: ActionablesPanel
    computed_at: datetime
    compute_duration_ms: int = Field(..., description="Temps d'execution total en millisecondes")


# ── Drilldown (top N mauvais acteurs) ──────────────────────────────────


class KGHealthDrilldownResponse(BaseModel):
    """Reponse /api/kg-health/drilldown/{key}."""

    key: str = Field(..., description="Cle du drilldown (ex: worst_docs, top_hubs)")
    title: str
    columns: List[str]
    rows: List[dict] = Field(..., description="Liste de lignes generiques (clefs correspondent aux columns)")
    total_available: int
