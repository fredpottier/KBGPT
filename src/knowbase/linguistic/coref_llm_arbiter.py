"""
OSMOSE Linguistic Layer - LLM Arbiter pour les coréférences Named↔Named

Ce module implémente l'arbitrage LLM pour les paires en zone grise (REVIEW).
Utilise vLLM Qwen sur EC2 via LLMRouter existant.

Principe clé:
- Appelé uniquement pour les paires en REVIEW (zone grise après gating)
- Batch les paires pour économiser les appels
- Supporte l'abstention explicite (LLM ne sait pas)
- Fallback ABSTAIN si LLM indisponible

Ref: doc/ongoing/ADR_COREF_NAMED_NAMED_VALIDATION.md - Section LLM Arbiter
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from knowbase.linguistic.coref_models import ReasonCode, DecisionType
from knowbase.linguistic.coref_named_gating import GatingDecision

logger = logging.getLogger(__name__)


@dataclass
class CorefLLMDecision:
    """Décision de coréférence par le LLM."""
    pair_index: int
    same_entity: bool
    abstain: bool
    confidence: float
    reason: str

    @property
    def gating_decision(self) -> GatingDecision:
        """Convertit en décision de gating."""
        if self.abstain:
            return GatingDecision.REVIEW  # Abstention = pas de décision
        return GatingDecision.ACCEPT if self.same_entity else GatingDecision.REJECT

    @property
    def reason_code(self) -> ReasonCode:
        """Convertit en ReasonCode."""
        if self.abstain:
            return ReasonCode.LLM_ABSTAIN
        return ReasonCode.LLM_VALIDATED if self.same_entity else ReasonCode.LLM_REJECTED


@dataclass
class CorefPair:
    """Paire à évaluer par le LLM."""
    surface_a: str
    surface_b: str
    context_a: str
    context_b: str


class CorefLLMArbiter:
    """
    Arbitre LLM pour les coréférences Named↔Named.

    Utilise vLLM Qwen via LLMRouter existant (mode Burst si actif).
    """

    # Taille maximale du batch
    MAX_BATCH_SIZE = 10

    # Prompt template (agnostique au domaine)
    PROMPT_TEMPLATE = """Tu es un expert en résolution de coréférence linguistique.

{domain_context_section}
Pour chaque paire ci-dessous, détermine si les deux mentions réfèrent à la MÊME entité dans le monde réel.

Paires à évaluer:
{pairs_section}

Réponds UNIQUEMENT en JSON valide (pas de texte avant ou après):
{{
  "decisions": [
    {{
      "pair_index": 1,
      "same_entity": true ou false,
      "abstain": true ou false,
      "confidence": 0.0 à 1.0,
      "reason": "explication courte"
    }}
  ]
}}

RÈGLES IMPORTANTES:
- Deux mentions avec des noms SIMILAIRES peuvent désigner des entités DIFFÉRENTES
- Analyse le contexte pour comprendre ce que chaque mention désigne réellement
- Si tu ne peux pas trancher avec certitude, utilise "abstain": true
- "abstain": true signifie "je ne sais pas" (différent de "same_entity": false qui signifie "ce sont des entités différentes")
- Sois conservateur: en cas de doute sur des produits/technologies, préfère abstain ou false"""

    PAIR_TEMPLATE = """{index}. Mention A: "{surface_a}"
   Contexte A: "{context_a}"
   Mention B: "{surface_b}"
   Contexte B: "{context_b}"
"""

    def __init__(
        self,
        domain_context: Optional[str] = None,
        max_batch_size: int = MAX_BATCH_SIZE,
    ):
        """
        Initialise l'arbitre LLM.

        Args:
            domain_context: Contexte domaine optionnel (hint pour le LLM)
            max_batch_size: Taille max du batch (défaut: 10)
        """
        self.domain_context = domain_context
        self.max_batch_size = max_batch_size
        self._llm_router = None

    def _get_llm_router(self):
        """Lazy loading du LLMRouter."""
        if self._llm_router is None:
            from knowbase.common.llm_router import get_llm_router
            self._llm_router = get_llm_router()
        return self._llm_router

    def _build_prompt(self, pairs: List[CorefPair]) -> str:
        """Construit le prompt pour le batch de paires."""
        # Section contexte domaine
        if self.domain_context:
            domain_section = f"Contexte domaine: {self.domain_context}\n\n"
        else:
            domain_section = ""

        # Section paires
        pairs_lines = []
        for i, pair in enumerate(pairs, 1):
            pairs_lines.append(self.PAIR_TEMPLATE.format(
                index=i,
                surface_a=pair.surface_a,
                context_a=pair.context_a[:200] if pair.context_a else "(pas de contexte)",
                surface_b=pair.surface_b,
                context_b=pair.context_b[:200] if pair.context_b else "(pas de contexte)",
            ))

        return self.PROMPT_TEMPLATE.format(
            domain_context_section=domain_section,
            pairs_section="\n".join(pairs_lines),
        )

    def _parse_response(self, response: str, expected_count: int) -> List[CorefLLMDecision]:
        """Parse la réponse JSON du LLM."""
        try:
            # Extraire le JSON (le LLM peut ajouter du texte autour)
            start = response.find("{")
            end = response.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON found in response")

            json_str = response[start:end]
            data = json.loads(json_str)

            decisions = []
            for item in data.get("decisions", []):
                decisions.append(CorefLLMDecision(
                    pair_index=item.get("pair_index", 0),
                    same_entity=item.get("same_entity", False),
                    abstain=item.get("abstain", False),
                    confidence=item.get("confidence", 0.0),
                    reason=item.get("reason", ""),
                ))

            # Vérifier qu'on a le bon nombre de décisions
            if len(decisions) != expected_count:
                logger.warning(
                    f"[CorefLLMArbiter] Expected {expected_count} decisions, got {len(decisions)}"
                )

            return decisions

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"[CorefLLMArbiter] Failed to parse LLM response: {e}")
            logger.debug(f"[CorefLLMArbiter] Raw response: {response[:500]}...")
            return []

    def arbitrate(
        self,
        pairs: List[CorefPair],
    ) -> List[CorefLLMDecision]:
        """
        Arbitre un batch de paires via LLM.

        Args:
            pairs: Liste de CorefPair à évaluer

        Returns:
            Liste de CorefLLMDecision (une par paire)
        """
        if not pairs:
            return []

        # Limiter la taille du batch
        if len(pairs) > self.max_batch_size:
            logger.warning(
                f"[CorefLLMArbiter] Batch too large ({len(pairs)}), "
                f"truncating to {self.max_batch_size}"
            )
            pairs = pairs[:self.max_batch_size]

        # Construire le prompt
        prompt = self._build_prompt(pairs)

        try:
            # Appel LLM via router (utilise vLLM si burst mode actif)
            from knowbase.common.llm_router import TaskType, VLLMUnavailableError

            router = self._get_llm_router()

            messages = [
                {"role": "system", "content": "Tu es un expert en linguistique computationnelle."},
                {"role": "user", "content": prompt},
            ]

            response = router.complete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=messages,
                temperature=0.1,  # Basse température pour cohérence
                max_tokens=1024,
            )

            # Parser la réponse
            decisions = self._parse_response(response, len(pairs))

            if decisions:
                logger.info(
                    f"[CorefLLMArbiter] Arbitrated {len(pairs)} pairs: "
                    f"{sum(1 for d in decisions if d.same_entity)} same, "
                    f"{sum(1 for d in decisions if d.abstain)} abstain"
                )
            else:
                # Parsing failed - abstention pour toutes les paires
                logger.warning("[CorefLLMArbiter] Parsing failed, abstaining for all pairs")
                decisions = [
                    CorefLLMDecision(
                        pair_index=i + 1,
                        same_entity=False,
                        abstain=True,
                        confidence=0.0,
                        reason="LLM response parsing failed",
                    )
                    for i in range(len(pairs))
                ]

            return decisions

        except VLLMUnavailableError as e:
            # vLLM indisponible - abstention pour toutes les paires
            logger.warning(f"[CorefLLMArbiter] vLLM unavailable: {e}. Abstaining for all pairs.")
            return [
                CorefLLMDecision(
                    pair_index=i + 1,
                    same_entity=False,
                    abstain=True,
                    confidence=0.0,
                    reason="LLM unavailable",
                )
                for i in range(len(pairs))
            ]

        except Exception as e:
            # Erreur inattendue - abstention
            logger.error(f"[CorefLLMArbiter] Unexpected error: {e}")
            return [
                CorefLLMDecision(
                    pair_index=i + 1,
                    same_entity=False,
                    abstain=True,
                    confidence=0.0,
                    reason=f"Error: {str(e)[:50]}",
                )
                for i in range(len(pairs))
            ]

    def arbitrate_single(
        self,
        surface_a: str,
        surface_b: str,
        context_a: Optional[str] = None,
        context_b: Optional[str] = None,
    ) -> CorefLLMDecision:
        """
        Arbitre une seule paire (raccourci pour arbitrate).

        Args:
            surface_a: Surface de la première mention
            surface_b: Surface de la seconde mention
            context_a: Contexte de la première mention
            context_b: Contexte de la seconde mention

        Returns:
            CorefLLMDecision
        """
        pair = CorefPair(
            surface_a=surface_a,
            surface_b=surface_b,
            context_a=context_a or "",
            context_b=context_b or "",
        )
        results = self.arbitrate([pair])
        return results[0] if results else CorefLLMDecision(
            pair_index=1,
            same_entity=False,
            abstain=True,
            confidence=0.0,
            reason="Arbitration failed",
        )


def create_coref_arbiter(
    domain_context: Optional[str] = None,
    max_batch_size: int = 10,
) -> CorefLLMArbiter:
    """
    Factory function pour créer un arbitre LLM.

    Args:
        domain_context: Contexte domaine optionnel
        max_batch_size: Taille max du batch

    Returns:
        Instance de CorefLLMArbiter
    """
    return CorefLLMArbiter(
        domain_context=domain_context,
        max_batch_size=max_batch_size,
    )


# Export
__all__ = [
    "CorefLLMDecision",
    "CorefPair",
    "CorefLLMArbiter",
    "create_coref_arbiter",
]
