"""Unified Intent Router (Optim CH-49 Phase 4 — réduire latence Layer 1 cascade).

Un SEUL LLM call (DeepSeek-V3.1) qui détermine quels operators Cap2 sont
applicables à la question. Permet de skip les operators non-pertinents AU LIEU
de faire 4 detect_intent() séquentiels (gain p50 estimé -9-12s).

Architecture :
  router.dispatch(question) -> RouterDecision
    .applicable_operators: list[str]  # subset de ["temporal_active", "lifecycle_resolution", "kg_query", "set_reasoning"]
    .confidence: float
    .skip_layer1: bool  # si True → court-circuiter Layer 1 vers Layer 0

Charte respectée :
  - Domain-agnostic strict : prompt avec placeholders <DOC_X>, <STATUS> uniquement
  - Le router NE FAIT PAS le raisonnement final — il dispatche
  - Le verifier veto reste actif (gardes-fous Phase 2 préservés)
  - L'operator choisi peut TOUJOURS faire son detect_intent spécifique pour
    extraire ses paramètres (subject_keywords, query_date, polarity, etc.)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


ROUTER_PROMPT = """You are an intent router that decides which structural operator(s) might apply to a documentary question.

You will dispatch the question to a subset of these operators :
- "temporal_active" : "what version was active at date X" / "currently in force"
- "lifecycle_resolution" : "what replaced X" / "what does X supersede" / lineage
- "kg_query" : structural queries — "how many <STATUS>", "list all <STATUS>", "supersession chain"
- "set_reasoning" : "what is NOT in X" / "what is exempted from X" / exclusions
- "comparison_contradiction" : "compare <X> and <Y>" / "are <X> and <Y> aligned?" / contradiction detection

Return JSON only :
{
  "applicable_operators": ["<subset of the 4 operators above>"],
  "confidence": <float 0-1>,
  "skip_layer1": <bool>,
  "reason": "<one short sentence>"
}

Rules :
- If the question is a direct factual question, an explanation request, a content question
  inside a single document, or simply asks for an answer that doesn't fit any structural
  pattern above → applicable_operators = [], skip_layer1 = true.
- If multiple operators could apply, list them in priority order (most specific first).
- confidence reflects how strong the structural signal is.
- skip_layer1 = true ONLY when applicable_operators is empty.

Examples (abstract — placeholders <DOC_X>, <STATUS>, <DATE>):
- "What was the active version of <DOC_X> at <DATE>?" → ["temporal_active"], skip_layer1=false
- "What replaced <DOC_X>?" → ["lifecycle_resolution"], skip_layer1=false
- "How many <STATUS> documents exist?" → ["kg_query"], skip_layer1=false
- "What is excluded from <DOC_X>'s scope?" → ["set_reasoning"], skip_layer1=false
- "Compare <DOC_X> and <DOC_Y> on <ASPECT>" → ["comparison_contradiction"], skip_layer1=false
- "Are <DOC_X> and <DOC_Y> aligned regarding <ASPECT>?" → ["comparison_contradiction"], skip_layer1=false
- "Is there a contradiction between <DOC_X> and <DOC_Y>?" → ["comparison_contradiction"], skip_layer1=false
- "Show the supersession chain of <DOC_X>" → ["kg_query", "lifecycle_resolution"], skip_layer1=false
- "What is the maximum value of <PROPERTY> in <DOC_X>?" → [], skip_layer1=true (factual)
- "Why was <DOC_X> repealed?" → [], skip_layer1=true (causal, not structural)
- "Explain the impact of <DOC_X>" → [], skip_layer1=true (explanation)
- "List the items in Annex of <DOC_X>" → [], skip_layer1=true (positive content list, not structural)
"""


# Opérateurs valides retournés par le router
VALID_OPERATORS = {
    "temporal_active",
    "lifecycle_resolution",
    "kg_query",
    "set_reasoning",
    "comparison_contradiction",
}


@dataclass
class RouterDecision:
    applicable_operators: list[str] = field(default_factory=list)
    confidence: float = 0.0
    skip_layer1: bool = True
    reason: str = ""
    latency_ms: int = 0
    error: Optional[str] = None


class UnifiedIntentRouter:
    """Router unifié : 1 LLM call pour décider du dispatch Layer 1."""

    DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"
    BASE_URL = "https://api.together.xyz/v1"
    DEFAULT_TIMEOUT = 25.0

    def __init__(
        self,
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model or os.getenv("RUNTIME_V4_2_ROUTER_MODEL", self.DEFAULT_MODEL)
        self.timeout = timeout
        self.api_key = os.getenv("TOGETHER_API_KEY", "")

    def dispatch(self, question: str) -> RouterDecision:
        t0 = time.time()

        if not self.api_key:
            return RouterDecision(
                applicable_operators=[],
                confidence=0.0,
                skip_layer1=False,  # fail-open : laisser cascade normale
                reason="missing_api_key",
                latency_ms=0,
                error="missing_api_key",
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": f"Question: {question}"},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=httpx.HTTPTransport(retries=0),
            ) as client:
                resp = client.post(
                    f"{self.BASE_URL}/chat/completions",
                    json=payload, headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"UnifiedIntentRouter call failed: {exc}")
            wall_ms = int((time.time() - t0) * 1000)
            # Fail-open : on laisse la cascade normale s'exécuter
            return RouterDecision(
                applicable_operators=[],
                confidence=0.0,
                skip_layer1=False,
                reason=f"router_error: {exc}",
                latency_ms=wall_ms,
                error=str(exc),
            )

        # Validate output
        applicable_raw = parsed.get("applicable_operators") or []
        applicable = [op for op in applicable_raw if op in VALID_OPERATORS]
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        skip_layer1 = bool(parsed.get("skip_layer1", not applicable))
        reason = str(parsed.get("reason", ""))[:200]

        # Cohérence : si applicable est vide, skip_layer1 doit être True
        if not applicable:
            skip_layer1 = True
        # Si applicable non vide mais router suggère skip_layer1=true → contradiction
        # Privilégier la liste : si le router a listé des operators, on les essaie.
        if applicable and skip_layer1:
            skip_layer1 = False

        wall_ms = int((time.time() - t0) * 1000)
        return RouterDecision(
            applicable_operators=applicable,
            confidence=confidence,
            skip_layer1=skip_layer1,
            reason=reason,
            latency_ms=wall_ms,
        )
