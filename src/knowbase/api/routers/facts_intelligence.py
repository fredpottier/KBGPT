"""
Router API Intelligence Automatisée - Phase 3
Endpoints pour fonctionnalités IA de gouvernance
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from pydantic import BaseModel

from knowbase.api.schemas.facts_governance import (
    FactCreate, ConflictDetail, FactStatus
)
from knowbase.api.services.facts_intelligence import FactsIntelligenceService
from knowbase.api.services.facts_governance_service import FactsGovernanceService
from knowbase.api.middleware.user_context import get_user_context

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/facts/intelligence",
    tags=["Facts Intelligence"],
    responses={404: {"description": "Not found"}}
)


# Schémas de requête/réponse
class ConfidenceScoreRequest(BaseModel):
    """Requête de calcul de confidence"""
    fact: FactCreate
    include_context: bool = True


class ConfidenceScoreResponse(BaseModel):
    """Réponse avec score de confidence calculé"""
    confidence: float
    reasoning: str
    factors: dict
    recommendations: list[str]


class PatternsRequest(BaseModel):
    """Requête de détection de patterns"""
    detection_type: str = "all"  # "all", "patterns", "anomalies"
    limit: int = 100


class PatternsResponse(BaseModel):
    """Réponse avec patterns détectés"""
    patterns: list[dict]
    anomalies: list[dict]
    insights: list[str]


class MetricsResponse(BaseModel):
    """Réponse avec métriques de gouvernance"""
    coverage: float
    velocity: float
    quality_score: float
    approval_rate: float
    avg_time_to_approval: float
    top_contributors: list[dict]
    trend: str


def get_intelligence_service() -> FactsIntelligenceService:
    """Dependency injection pour le service Intelligence"""
    return FactsIntelligenceService()


def get_governance_service() -> FactsGovernanceService:
    """Dependency injection pour le service Governance"""
    return FactsGovernanceService()


@router.post("/confidence-score", response_model=ConfidenceScoreResponse)
async def calculate_confidence(
    request_data: ConfidenceScoreRequest,
    request: Request,
    intelligence_service: FactsIntelligenceService = Depends(get_intelligence_service),
    governance_service: FactsGovernanceService = Depends(get_governance_service)
):
    """
    Calcule un score de confidence automatique via LLM

    Analyse la fiabilité d'un fait proposé en utilisant:
    - Intelligence artificielle (LLM)
    - Contexte des facts existants similaires
    - Analyse multi-factorielle (clarté, cohérence, source, spécificité)

    **Retour**:
    - Score de confidence (0.0 à 1.0)
    - Raisonnement détaillé
    - Facteurs contributifs
    - Recommandations d'amélioration

    **Use cases**:
    - Validation automatique pré-review
    - Scoring batch de facts importés
    - Aide à la décision pour experts
    """
    try:
        context = get_user_context(request)
        await governance_service.set_group(context.get("group_id", "corporate"))

        # Récupérer contexte si demandé
        context_facts = None
        if request_data.include_context:
            # Chercher facts similaires (même sujet ou prédicat)
            from knowbase.api.schemas.facts_governance import FactFilters
            filters = FactFilters(
                subject=request_data.fact.subject,
                limit=5
            )
            similar_response = await governance_service.list_facts(filters)
            context_facts = similar_response.facts

        # Calculer le score
        analysis = await intelligence_service.calculate_confidence_score(
            fact=request_data.fact,
            context_facts=context_facts
        )

        return ConfidenceScoreResponse(**analysis)

    except Exception as e:
        logger.error(f"Erreur calcul confidence: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur calcul confidence: {str(e)}")


@router.post("/suggest-resolution/{fact_uuid}")
async def suggest_conflict_resolution(
    fact_uuid: str,
    request: Request,
    intelligence_service: FactsIntelligenceService = Depends(get_intelligence_service),
    governance_service: FactsGovernanceService = Depends(get_governance_service)
):
    """
    Génère des suggestions IA pour résoudre un conflit

    Analyse le conflit et propose des stratégies de résolution:
    - Priorisation basée sur sources
    - Validation temporelle
    - Consultation d'experts recommandés
    - Fusion de facts contradictoires

    **Workflow**:
    1. Récupération du fact et ses conflits
    2. Analyse par LLM du contexte
    3. Génération de 3-5 suggestions actionnables

    **Permissions**: Utilisateurs avec rôle expert ou admin
    """
    try:
        context = get_user_context(request)
        await governance_service.set_group(context.get("group_id", "corporate"))

        # Récupérer le fact
        fact = await governance_service.get_fact(fact_uuid)
        if not fact:
            raise HTTPException(status_code=404, detail=f"Fact {fact_uuid} introuvable")

        # Vérifier s'il y a des conflits
        from knowbase.api.schemas.facts_governance import FactCreate
        fact_create = FactCreate(
            subject=fact.subject,
            predicate=fact.predicate,
            object=fact.object,
            confidence=fact.confidence,
            source=fact.source,
            tags=fact.tags,
            metadata=fact.metadata
        )

        conflicts = await governance_service.detect_conflicts(fact_create)

        if not conflicts:
            return {
                "fact_uuid": fact_uuid,
                "has_conflicts": False,
                "suggestions": ["Aucun conflit détecté - fact peut être approuvé"]
            }

        # Générer suggestions pour chaque conflit
        all_suggestions = []
        for conflict in conflicts:
            suggestions = await intelligence_service.suggest_conflict_resolutions(conflict)
            all_suggestions.extend(suggestions)

        # Dédupliquer
        unique_suggestions = list(set(all_suggestions))

        return {
            "fact_uuid": fact_uuid,
            "has_conflicts": True,
            "conflicts_count": len(conflicts),
            "suggestions": unique_suggestions[:10]  # Top 10
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur suggestions résolution: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur suggestions: {str(e)}")


@router.post("/detect-patterns", response_model=PatternsResponse)
async def detect_patterns(
    request_data: PatternsRequest,
    request: Request,
    intelligence_service: FactsIntelligenceService = Depends(get_intelligence_service),
    governance_service: FactsGovernanceService = Depends(get_governance_service)
):
    """
    Détecte des patterns et anomalies dans les facts

    **Patterns détectés**:
    - Pics d'activité temporelle
    - Sujets/prédicats fréquents
    - Concentrations thématiques

    **Anomalies détectées**:
    - Facts à confiance anormalement basse/haute
    - Création en masse suspecte
    - Déséquilibres dans les statuts

    **Use cases**:
    - Dashboard exécutif
    - Détection fraude/erreurs
    - Optimisation processus gouvernance
    - Identification besoins formation

    **Permissions**: Tous utilisateurs (données filtrées par groupe)
    """
    try:
        context = get_user_context(request)
        await governance_service.set_group(context.get("group_id", "corporate"))

        # Récupérer les facts pour analyse
        from knowbase.api.schemas.facts_governance import FactFilters
        filters = FactFilters(limit=request_data.limit)
        facts_response = await governance_service.list_facts(filters)

        if not facts_response.facts:
            return PatternsResponse(
                patterns=[],
                anomalies=[],
                insights=["Aucune donnée disponible pour analyse"]
            )

        # Détecter patterns et anomalies
        analysis = await intelligence_service.detect_patterns_and_anomalies(
            facts=facts_response.facts,
            detection_type=request_data.detection_type
        )

        return PatternsResponse(**analysis)

    except Exception as e:
        logger.error(f"Erreur détection patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur détection patterns: {str(e)}")


@router.get("/metrics", response_model=MetricsResponse)
async def get_governance_metrics(
    request: Request,
    time_window_days: int = Query(30, ge=1, le=365, description="Fenêtre temporelle (jours)"),
    intelligence_service: FactsIntelligenceService = Depends(get_intelligence_service),
    governance_service: FactsGovernanceService = Depends(get_governance_service)
):
    """
    Calcule des métriques avancées de gouvernance

    **Métriques incluses**:
    - **Coverage**: % de facts approuvés dans la base
    - **Velocity**: Nombre de facts créés par jour (fenêtre récente)
    - **Quality Score**: Moyenne des confidences des facts approuvés
    - **Approval Rate**: % de facts approuvés vs rejetés
    - **Avg Time to Approval**: Temps moyen d'approbation (heures)
    - **Top Contributors**: Utilisateurs les plus actifs
    - **Trend**: Tendance (improving/stable/declining)

    **Use cases**:
    - KPIs exécutifs
    - Rapports de performance
    - Identification goulots d'étranglement
    - Benchmarking équipes

    **Permissions**: Tous utilisateurs (données filtrées par groupe)
    """
    try:
        context = get_user_context(request)
        await governance_service.set_group(context.get("group_id", "corporate"))

        # Récupérer tous les facts pour la fenêtre temporelle
        from knowbase.api.schemas.facts_governance import FactFilters
        filters = FactFilters(limit=1000)  # Limiter pour performance
        facts_response = await governance_service.list_facts(filters)

        if not facts_response.facts:
            return MetricsResponse(
                coverage=0.0,
                velocity=0.0,
                quality_score=0.0,
                approval_rate=0.0,
                avg_time_to_approval=0.0,
                top_contributors=[],
                trend="stable"
            )

        # Calculer les métriques
        metrics = await intelligence_service.calculate_governance_metrics(
            facts=facts_response.facts,
            time_window_days=time_window_days
        )

        return MetricsResponse(**metrics)

    except Exception as e:
        logger.error(f"Erreur calcul métriques: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur calcul métriques: {str(e)}")


@router.get("/alerts")
async def get_governance_alerts(
    request: Request,
    severity: Optional[str] = Query(None, description="Filtrer par sévérité"),
    intelligence_service: FactsIntelligenceService = Depends(get_intelligence_service),
    governance_service: FactsGovernanceService = Depends(get_governance_service)
):
    """
    Récupère les alertes automatiques de gouvernance

    **Alertes générées**:
    - Conflits critiques non résolus depuis >7 jours
    - Facts proposés anciens (>30 jours) non validés
    - Pic anormal de rejets
    - Baisse significative du quality score
    - Contributeur avec taux rejet >50%

    **Sévérités**:
    - `critical`: Action immédiate requise
    - `high`: Attention rapide nécessaire
    - `medium`: À traiter sous 1 semaine
    - `low`: Informatif

    **Permissions**: Utilisateurs avec rôle expert ou admin
    """
    try:
        context = get_user_context(request)
        await governance_service.set_group(context.get("group_id", "corporate"))

        alerts = []

        # Récupérer les facts pour analyse
        from knowbase.api.schemas.facts_governance import FactFilters
        filters = FactFilters(limit=500)
        facts_response = await governance_service.list_facts(filters)

        if not facts_response.facts:
            return {"alerts": [], "total": 0}

        # Alerte: Facts proposés anciens
        from datetime import datetime, timedelta
        cutoff_old = datetime.utcnow() - timedelta(days=30)

        old_proposed = [
            f for f in facts_response.facts
            if f.status == FactStatus.PROPOSED and
            f.created_at < cutoff_old
        ]

        if old_proposed:
            alerts.append({
                "type": "old_pending_facts",
                "severity": "high",
                "title": f"{len(old_proposed)} fact(s) en attente depuis >30 jours",
                "description": "Ces facts nécessitent une validation rapide",
                "fact_uuids": [f.uuid for f in old_proposed[:20]],
                "action": "Réviser et approuver/rejeter ces facts"
            })

        # Alerte: Taux d'approbation faible
        total_processed = len([f for f in facts_response.facts if f.status in [FactStatus.APPROVED, FactStatus.REJECTED]])
        approved = len([f for f in facts_response.facts if f.status == FactStatus.APPROVED])

        if total_processed > 10:
            approval_rate = approved / total_processed
            if approval_rate < 0.5:
                alerts.append({
                    "type": "low_approval_rate",
                    "severity": "medium",
                    "title": f"Taux d'approbation faible: {approval_rate*100:.1f}%",
                    "description": "Plus de la moitié des facts sont rejetés",
                    "action": "Améliorer qualité des soumissions ou critères de validation"
                })

        # Alerte: Conflits non résolus
        conflicts_response = await governance_service.get_conflicts()
        if conflicts_response.total_conflicts > 10:
            alerts.append({
                "type": "high_conflicts_count",
                "severity": "critical",
                "title": f"{conflicts_response.total_conflicts} conflits actifs",
                "description": "Nombre élevé de conflits nécessitant résolution",
                "action": "Prioriser la résolution des conflits critiques"
            })

        # Filtrer par sévérité si demandé
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]

        return {
            "alerts": alerts,
            "total": len(alerts),
            "by_severity": {
                "critical": len([a for a in alerts if a["severity"] == "critical"]),
                "high": len([a for a in alerts if a["severity"] == "high"]),
                "medium": len([a for a in alerts if a["severity"] == "medium"]),
                "low": len([a for a in alerts if a["severity"] == "low"])
            }
        }

    except Exception as e:
        logger.error(f"Erreur récupération alertes: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur récupération alertes: {str(e)}")