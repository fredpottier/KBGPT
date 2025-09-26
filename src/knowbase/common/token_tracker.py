"""
Module de tracking des tokens et calculs de coûts LLM
Permet de calculer les coûts selon les modèles utilisés et comparer avec Bedrock
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Utilisation des tokens pour un appel LLM."""
    model: str
    task_type: str
    input_tokens: int
    output_tokens: int
    timestamp: datetime
    context: str = ""  # slide_X, deck_summary, etc.

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelPricing:
    """Tarification d'un modèle LLM."""
    name: str
    input_price_per_1k: float  # $ per 1K tokens
    output_price_per_1k: float  # $ per 1K tokens
    provider: str


class TokenTracker:
    """Tracker centralisé des tokens et coûts."""

    # Tarifs actuels (à jour septembre 2024)
    MODEL_PRICING = {
        # OpenAI
        "gpt-4o": ModelPricing("gpt-4o", 0.005, 0.015, "openai"),
        "gpt-4o-mini": ModelPricing("gpt-4o-mini", 0.000150, 0.000600, "openai"),
        "gpt-4": ModelPricing("gpt-4", 0.03, 0.06, "openai"),

        # Anthropic
        "claude-3.5-sonnet": ModelPricing("claude-3.5-sonnet", 0.003, 0.015, "anthropic"),
        "claude-3-haiku": ModelPricing("claude-3-haiku", 0.00025, 0.00125, "anthropic"),
        "claude-3-opus": ModelPricing("claude-3-opus", 0.015, 0.075, "anthropic"),

        # Bedrock (pour comparaison)
        "bedrock-claude-3.5-sonnet": ModelPricing("bedrock-claude-3.5-sonnet", 0.003, 0.015, "bedrock"),
        "bedrock-claude-3-haiku": ModelPricing("bedrock-claude-3-haiku", 0.00025, 0.00125, "bedrock"),

        # SageMaker (tarification basée sur instance + coût de compute)
        # Tarifs estimés selon instance AWS + consommation
        "llama3.1:70b": ModelPricing("llama3.1:70b", 0.0012, 0.0012, "sagemaker"),  # ml.g5.12xlarge
        "qwen2.5:32b": ModelPricing("qwen2.5:32b", 0.0004, 0.0004, "sagemaker"),   # ml.g5.4xlarge
        "qwen2.5:7b": ModelPricing("qwen2.5:7b", 0.0001, 0.0001, "sagemaker"),     # ml.g5.xlarge
        "llava:34b": ModelPricing("llava:34b", 0.0004, 0.0004, "sagemaker"),       # ml.g5.4xlarge (vision)
        "phi3:3.8b": ModelPricing("phi3:3.8b", 0.00005, 0.00005, "sagemaker"),     # ml.m5.xlarge (CPU)
    }

    def __init__(self, log_file: Optional[Path] = None):
        self.usage_history: List[TokenUsage] = []
        self.log_file = log_file

    def add_usage(
        self,
        model: str,
        task_type: str,
        input_tokens: int,
        output_tokens: int,
        context: str = ""
    ) -> None:
        """Ajoute une utilisation de tokens."""
        usage = TokenUsage(
            model=model,
            task_type=task_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=datetime.now(),
            context=context
        )

        self.usage_history.append(usage)

        # Log pour debug
        cost = self.calculate_cost(usage)
        logger.info(
            f"[TOKEN_TRACKER] {model} ({task_type}) - "
            f"In: {input_tokens}, Out: {output_tokens}, "
            f"Cost: ${cost:.4f} - {context}"
        )

        # Sauvegarde optionnelle
        if self.log_file:
            self._save_to_file(usage)

    def calculate_cost(self, usage: TokenUsage) -> float:
        """Calcule le coût d'une utilisation."""
        pricing = self.MODEL_PRICING.get(usage.model)
        if not pricing:
            logger.warning(f"Pricing non trouvé pour {usage.model}")
            return 0.0

        input_cost = (usage.input_tokens / 1000) * pricing.input_price_per_1k
        output_cost = (usage.output_tokens / 1000) * pricing.output_price_per_1k

        return input_cost + output_cost

    def get_total_cost(
        self,
        task_type: Optional[str] = None,
        context_filter: Optional[str] = None
    ) -> float:
        """Calcule le coût total selon des filtres."""
        filtered_usage = self.usage_history

        if task_type:
            filtered_usage = [u for u in filtered_usage if u.task_type == task_type]

        if context_filter:
            filtered_usage = [u for u in filtered_usage if context_filter in u.context]

        return sum(self.calculate_cost(usage) for usage in filtered_usage)

    def get_stats_by_model(self) -> Dict[str, Dict[str, float]]:
        """Statistiques par modèle."""
        stats = {}

        for usage in self.usage_history:
            if usage.model not in stats:
                stats[usage.model] = {
                    "total_calls": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost": 0.0
                }

            stats[usage.model]["total_calls"] += 1
            stats[usage.model]["total_input_tokens"] += usage.input_tokens
            stats[usage.model]["total_output_tokens"] += usage.output_tokens
            stats[usage.model]["total_cost"] += self.calculate_cost(usage)

        return stats

    def estimate_deck_cost(
        self,
        num_slides: int,
        avg_input_tokens: int = 2000,  # Estimation moyenne par slide
        avg_output_tokens: int = 1500,  # Estimation moyenne par slide
        model: str = "gpt-4o"
    ) -> Dict[str, float]:
        """Estime le coût d'un deck complet."""
        pricing = self.MODEL_PRICING.get(model)
        if not pricing:
            return {"error": f"Pricing non trouvé pour {model}"}

        # Coût deck summary (1 appel)
        deck_summary_input = num_slides * 100  # ~100 tokens par slide pour le résumé
        deck_summary_output = 500
        deck_cost = (
            (deck_summary_input / 1000) * pricing.input_price_per_1k +
            (deck_summary_output / 1000) * pricing.output_price_per_1k
        )

        # Coût analyse slides
        slides_input_total = num_slides * avg_input_tokens
        slides_output_total = num_slides * avg_output_tokens
        slides_cost = (
            (slides_input_total / 1000) * pricing.input_price_per_1k +
            (slides_output_total / 1000) * pricing.output_price_per_1k
        )

        total_cost = deck_cost + slides_cost

        return {
            "model": model,
            "num_slides": num_slides,
            "deck_summary_cost": deck_cost,
            "slides_analysis_cost": slides_cost,
            "total_cost": total_cost,
            "cost_per_slide": total_cost / num_slides,
            "total_tokens": deck_summary_input + deck_summary_output + slides_input_total + slides_output_total
        }

    def compare_providers(self, usage: TokenUsage) -> Dict[str, float]:
        """Compare les coûts entre providers pour une utilisation."""
        comparisons = {}

        # Trouver des modèles équivalents
        equivalent_models = {
            "gpt-4o": ["claude-3.5-sonnet", "bedrock-claude-3.5-sonnet", "llama3.1:70b"],
            "gpt-4o-mini": ["claude-3-haiku", "bedrock-claude-3-haiku", "qwen2.5:7b", "phi3:3.8b"],
            "claude-3.5-sonnet": ["gpt-4o", "bedrock-claude-3.5-sonnet", "llama3.1:70b"],
            "claude-3-haiku": ["gpt-4o-mini", "bedrock-claude-3-haiku", "qwen2.5:7b"],
            # SageMaker equivalences
            "llama3.1:70b": ["gpt-4o", "claude-3.5-sonnet"],
            "qwen2.5:32b": ["gpt-4o", "claude-3.5-sonnet"],
            "qwen2.5:7b": ["gpt-4o-mini", "claude-3-haiku"],
            "llava:34b": ["gpt-4o"],  # Vision model
            "phi3:3.8b": ["gpt-4o-mini", "claude-3-haiku"],
        }

        base_cost = self.calculate_cost(usage)
        comparisons[usage.model] = base_cost

        for equivalent_model in equivalent_models.get(usage.model, []):
            if equivalent_model in self.MODEL_PRICING:
                equivalent_usage = TokenUsage(
                    model=equivalent_model,
                    task_type=usage.task_type,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    timestamp=usage.timestamp,
                    context=usage.context
                )
                comparisons[equivalent_model] = self.calculate_cost(equivalent_usage)

        return comparisons

    def _save_to_file(self, usage: TokenUsage) -> None:
        """Sauvegarde dans un fichier de log."""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                data = {
                    "timestamp": usage.timestamp.isoformat(),
                    "model": usage.model,
                    "task_type": usage.task_type,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "cost": self.calculate_cost(usage),
                    "context": usage.context
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Erreur sauvegarde token tracking: {e}")


# Instance globale
_token_tracker: Optional[TokenTracker] = None


def get_token_tracker() -> TokenTracker:
    """Obtient l'instance singleton du token tracker."""
    global _token_tracker
    if _token_tracker is None:
        from knowbase.config.settings import get_settings
        settings = get_settings()
        log_file = settings.logs_dir / "token_usage.jsonl"
        _token_tracker = TokenTracker(log_file)
    return _token_tracker


def track_tokens(
    model: str,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
    context: str = ""
) -> None:
    """Fonction utilitaire pour tracker des tokens."""
    tracker = get_token_tracker()
    tracker.add_usage(model, task_type, input_tokens, output_tokens, context)