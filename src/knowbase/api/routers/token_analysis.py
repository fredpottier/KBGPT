"""
API pour l'analyse des tokens et coûts LLM
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from knowbase.api.dependencies import get_current_user, get_tenant_id, require_admin
from knowbase.common.token_tracker import get_token_tracker

router = APIRouter(prefix="/tokens", tags=["Token Analysis"])


class DeckCostEstimate(BaseModel):
    """Estimation du coût d'un deck."""
    model: str
    num_slides: int
    deck_summary_cost: float
    slides_analysis_cost: float
    total_cost: float
    cost_per_slide: float
    total_tokens: int


class TokenStats(BaseModel):
    """Statistiques des tokens."""
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float


@router.get("/stats")
def get_token_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Obtient les statistiques globales des tokens.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    tracker = get_token_tracker()
    stats_by_model = tracker.get_stats_by_model()

    return {
        "stats_by_model": stats_by_model,
        "total_cost": tracker.get_total_cost(),
        "total_usage_count": len(tracker.usage_history)
    }


@router.get("/estimate-deck")
def estimate_deck_cost(
    num_slides: int = Query(..., description="Nombre de slides dans le deck"),
    model: str = Query("gpt-4o", description="Modèle LLM à utiliser"),
    avg_input_tokens: int = Query(2000, description="Tokens d'input moyen par slide"),
    avg_output_tokens: int = Query(1500, description="Tokens d'output moyen par slide"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> DeckCostEstimate:
    """
    Estime le coût d'traitement d'un deck complet.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    if num_slides <= 0:
        raise HTTPException(status_code=400, detail="Le nombre de slides doit être positif")

    tracker = get_token_tracker()
    estimate = tracker.estimate_deck_cost(num_slides, avg_input_tokens, avg_output_tokens, model)

    if "error" in estimate:
        raise HTTPException(status_code=400, detail=estimate["error"])

    return DeckCostEstimate(**estimate)


@router.get("/compare-providers")
def compare_providers_cost(
    input_tokens: int = Query(..., description="Tokens d'input"),
    output_tokens: int = Query(..., description="Tokens d'output"),
    base_model: str = Query("gpt-4o", description="Modèle de base pour comparaison"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Compare les coûts entre différents providers.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    from knowbase.common.token_tracker import TokenUsage
    from datetime import datetime

    tracker = get_token_tracker()

    # Créer un usage fictif pour la comparaison
    usage = TokenUsage(
        model=base_model,
        task_type="comparison",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        timestamp=datetime.now()
    )

    comparisons = tracker.compare_providers(usage)

    # Calculer les économies potentielles
    base_cost = comparisons.get(base_model, 0)
    cheapest_model = min(comparisons.keys(), key=lambda k: comparisons[k])
    cheapest_cost = comparisons[cheapest_model]

    savings = base_cost - cheapest_cost
    savings_percent = (savings / base_cost * 100) if base_cost > 0 else 0

    return {
        "comparisons": comparisons,
        "base_model": base_model,
        "base_cost": base_cost,
        "cheapest_model": cheapest_model,
        "cheapest_cost": cheapest_cost,
        "potential_savings": savings,
        "savings_percent": savings_percent,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens
    }


@router.get("/cost-by-task")
def get_cost_by_task_type(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Analyse des coûts par type de tâche.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    tracker = get_token_tracker()

    # Grouper par task_type
    task_stats = {}
    for usage in tracker.usage_history:
        if usage.task_type not in task_stats:
            task_stats[usage.task_type] = {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost": 0.0,
                "models_used": set()
            }

        task_stats[usage.task_type]["total_calls"] += 1
        task_stats[usage.task_type]["total_input_tokens"] += usage.input_tokens
        task_stats[usage.task_type]["total_output_tokens"] += usage.output_tokens
        task_stats[usage.task_type]["total_cost"] += tracker.calculate_cost(usage)
        task_stats[usage.task_type]["models_used"].add(usage.model)

    # Convertir les sets en listes pour JSON
    for task_type in task_stats:
        task_stats[task_type]["models_used"] = list(task_stats[task_type]["models_used"])

        # Calculer le coût moyen par appel
        if task_stats[task_type]["total_calls"] > 0:
            task_stats[task_type]["avg_cost_per_call"] = (
                task_stats[task_type]["total_cost"] / task_stats[task_type]["total_calls"]
            )

    return task_stats


@router.get("/pricing")
def get_model_pricing(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Retourne les tarifs actuels des modèles.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    tracker = get_token_tracker()

    pricing_info = {}
    for model_name, pricing in tracker.MODEL_PRICING.items():
        pricing_info[model_name] = {
            "provider": pricing.provider,
            "input_price_per_1k": pricing.input_price_per_1k,
            "output_price_per_1k": pricing.output_price_per_1k,
            "total_1k_tokens_cost": pricing.input_price_per_1k + pricing.output_price_per_1k
        }

    return pricing_info


@router.post("/reset")
def reset_token_tracking(
    admin: dict = Depends(require_admin),
):
    """
    Reset les données de tracking (pour tests).

    **Sécurité**: Requiert authentification JWT avec rôle 'admin'.
    """
    tracker = get_token_tracker()
    tracker.usage_history.clear()

    return {"message": "Token tracking data cleared"}


@router.get("/sagemaker-savings")
def estimate_sagemaker_savings(
    num_slides: int = Query(..., description="Nombre de slides dans le deck"),
    current_model: str = Query("gpt-4o", description="Modèle actuellement utilisé"),
    avg_input_tokens: int = Query(2000, description="Tokens d'input moyen par slide"),
    avg_output_tokens: int = Query(1500, description="Tokens d'output moyen par slide"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Compare les coûts actuels vs migration SageMaker pour un deck.

    **Sécurité**: Requiert authentification JWT (tous rôles).
    """
    tracker = get_token_tracker()

    # Estimation coût actuel
    current_estimate = tracker.estimate_deck_cost(num_slides, avg_input_tokens, avg_output_tokens, current_model)

    if "error" in current_estimate:
        raise HTTPException(status_code=400, detail=current_estimate["error"])

    # Mapping des modèles SageMaker équivalents selon la tâche
    sagemaker_alternatives = {
        "gpt-4o": "llama3.1:70b",
        "gpt-4o-mini": "qwen2.5:7b",
        "claude-3.5-sonnet": "llama3.1:70b",
        "claude-3-haiku": "qwen2.5:7b"
    }

    sagemaker_model = sagemaker_alternatives.get(current_model, "llama3.1:70b")
    sagemaker_estimate = tracker.estimate_deck_cost(num_slides, avg_input_tokens, avg_output_tokens, sagemaker_model)

    if "error" in sagemaker_estimate:
        raise HTTPException(status_code=400, detail=sagemaker_estimate["error"])

    # Calcul des économies
    cost_savings = current_estimate["total_cost"] - sagemaker_estimate["total_cost"]
    savings_percent = (cost_savings / current_estimate["total_cost"] * 100) if current_estimate["total_cost"] > 0 else 0

    # Coût mensuel si traitement 20 decks/mois
    monthly_current = current_estimate["total_cost"] * 20
    monthly_sagemaker = sagemaker_estimate["total_cost"] * 20
    monthly_savings = monthly_current - monthly_sagemaker

    return {
        "current_model": {
            "name": current_model,
            "total_cost": current_estimate["total_cost"],
            "cost_per_slide": current_estimate["cost_per_slide"]
        },
        "sagemaker_alternative": {
            "name": sagemaker_model,
            "total_cost": sagemaker_estimate["total_cost"],
            "cost_per_slide": sagemaker_estimate["cost_per_slide"]
        },
        "savings": {
            "per_deck": cost_savings,
            "percentage": round(savings_percent, 2),
            "monthly_20_decks": monthly_savings,
            "annual_240_decks": monthly_savings * 12
        },
        "break_even_analysis": {
            "estimated_instance_cost_per_hour": 2.03 if "70b" in sagemaker_model else 0.23,
            "processing_time_per_deck_minutes": 20,
            "decks_per_month_to_break_even": max(1, int(monthly_savings / (2.03 * 20 / 60))) if monthly_savings > 0 else "N/A"
        },
        "recommendations": {
            "use_sagemaker": savings_percent > 50,
            "reason": f"Économies de {round(savings_percent)}% par deck" if savings_percent > 0 else "Pas d'économie significative"
        }
    }