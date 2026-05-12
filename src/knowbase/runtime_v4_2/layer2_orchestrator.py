"""Layer 2 Adaptive Orchestrator (CH-49 Phase 3, Cap3).

Agent LLM avec tool use pour les questions complexes nécessitant un raisonnement
multi-étape (causal, multi-hop, hypothétique, audit retrospectif).

Modèle : **DeepSeek-V3.1** via Together AI (open-source, anti-biais vs Composer Llama).
Charte ADR §0 respectée : pas de Sonnet/GPT-4o.

Pattern :
  1. Plan : LLM décompose la question en sous-questions / étapes
  2. Execute : LLM appelle iterativement les tools (Cap2 ops + vector_search)
  3. Synthesize : LLM synthétise les résultats en une réponse finale citée

Budget compute : max 5 iterations, timeout p95 45s.

Trigger pipeline (ADR §1 Cap3) :
  - Layer 0 ABSTAIN ET aucun operator Cap2 applicable
  - Layer 1 retourne low_confidence ou ambigu
  - Plusieurs operators Cap2 applicables avec scores conflictuels
  - Type complexe (multi-hop / causal / hypothetical) détecté en amont
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from knowbase.runtime_v4_2.tools import ToolRegistry, ToolCallResult

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an adaptive reasoning agent for documentary question answering.

You have access to tools that let you :
- search the corpus (vector_search)
- query the knowledge graph (lifecycle_resolution, kg_query)
- check if a document version was active at a date (temporal_active_version)
- find items excluded from a scope (set_reasoning_negation)
- extract answers from gathered chunks (extract_answer_from_chunks)

Your method :
1. Read the question carefully. Identify what needs to be reasoned (causal, multi-hop, conditional, hypothetical).
2. Decide which tool(s) to call. You may call multiple tools across iterations.
3. After each tool result, decide : do you have enough to answer, or need more evidence?
4. When ready, produce the FINAL ANSWER as plain text with [doc=ID] citations.

Constraints :
- Always cite sources with [doc=ID] markers
- If after 3-4 tool calls you cannot answer, say so explicitly: "La reponse a votre question n'a pas ete trouvee dans les documents disponibles."
- Stay grounded in chunks/operators output — do not fabricate facts
- Keep your final answer concise: 2-5 sentences

Output your final answer as plain text (no JSON wrapper) once you've gathered enough evidence."""


@dataclass
class Layer2Step:
    iteration: int
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    assistant_message: Optional[str] = None
    duration_ms: int = 0


@dataclass
class Layer2Response:
    decision: str  # ANSWER | ABSTAIN
    answer: str
    n_iterations: int = 0
    tool_calls_log: list[dict] = field(default_factory=list)
    plan: Optional[str] = None
    abstention_reason: Optional[str] = None
    latency_breakdown_ms: dict = field(default_factory=dict)
    error: Optional[str] = None


class Layer2Orchestrator:
    """Agent orchestrator avec tool use, DeepSeek-V3.1 (Together AI)."""

    DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"
    BASE_URL = "https://api.together.xyz/v1"
    MAX_ITERATIONS = 5
    DEFAULT_TIMEOUT = 60.0  # par appel
    MAX_TOTAL_LATENCY_MS = 45000  # budget total

    def __init__(
        self,
        tool_registry: ToolRegistry,
        model: Optional[str] = None,
        max_iterations: int = MAX_ITERATIONS,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.tool_registry = tool_registry
        self.model = model or os.getenv("LAYER2_MODEL", self.DEFAULT_MODEL)
        self.max_iterations = max_iterations
        self.timeout = timeout
        self.api_key = os.getenv("TOGETHER_API_KEY", "")

    def answer(self, question: str) -> Layer2Response:
        timings: dict[str, int] = {}
        t_total = time.time()
        tool_calls_log: list[dict] = []

        if not self.api_key:
            return Layer2Response(
                decision="ABSTAIN",
                answer="Erreur configuration : TOGETHER_API_KEY manquante.",
                error="missing_api_key",
                latency_breakdown_ms={"total_ms": 0},
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        tools = self.tool_registry.get_tool_defs()

        for iteration in range(self.max_iterations):
            # Vérifier le budget global
            elapsed_ms = int((time.time() - t_total) * 1000)
            if elapsed_ms > self.MAX_TOTAL_LATENCY_MS:
                logger.warning(f"[L2] timeout budget {elapsed_ms}ms after iter {iteration}")
                break

            t_iter = time.time()
            try:
                response_msg = self._llm_call(messages, tools)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[L2] LLM call failed iter {iteration}: {exc}")
                timings[f"iter_{iteration}_ms"] = int((time.time() - t_iter) * 1000)
                return Layer2Response(
                    decision="ABSTAIN",
                    answer="Erreur Layer 2 orchestrator.",
                    n_iterations=iteration,
                    tool_calls_log=tool_calls_log,
                    abstention_reason=f"llm_error: {exc}",
                    error=str(exc),
                    latency_breakdown_ms=timings,
                )
            timings[f"iter_{iteration}_ms"] = int((time.time() - t_iter) * 1000)

            # Le LLM a produit du content sans tool_calls → réponse finale
            tool_calls = response_msg.get("tool_calls") or []
            content = response_msg.get("content") or ""

            if not tool_calls:
                # Réponse finale
                timings["total_ms"] = int((time.time() - t_total) * 1000)
                if not content.strip():
                    return Layer2Response(
                        decision="ABSTAIN",
                        answer="Layer 2 orchestrator a terminé sans réponse explicite.",
                        n_iterations=iteration + 1,
                        tool_calls_log=tool_calls_log,
                        abstention_reason="empty_final_message",
                        latency_breakdown_ms=timings,
                    )
                # Détection abstention dans le contenu
                if "n'a pas ete trouvee" in content.lower() or "not found in" in content.lower():
                    return Layer2Response(
                        decision="ABSTAIN",
                        answer=content,
                        n_iterations=iteration + 1,
                        tool_calls_log=tool_calls_log,
                        abstention_reason="orchestrator_explicit_abstain",
                        latency_breakdown_ms=timings,
                    )
                return Layer2Response(
                    decision="ANSWER",
                    answer=content,
                    n_iterations=iteration + 1,
                    tool_calls_log=tool_calls_log,
                    latency_breakdown_ms=timings,
                )

            # Le LLM a demandé des tool calls
            messages.append(response_msg)
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                arg_str = func.get("arguments", "{}")
                try:
                    args = json.loads(arg_str)
                except json.JSONDecodeError:
                    args = {}
                logger.info(f"[L2 iter={iteration}] tool={tool_name} args={list(args.keys())}")
                result = self.tool_registry.execute(tool_name, args)
                tool_calls_log.append({
                    "iteration": iteration,
                    "tool_name": tool_name,
                    "arguments": args,
                    "success": result.success,
                    "latency_ms": result.latency_ms,
                    "result_summary": self._summarize_result(result.result),
                })
                # Append le résultat comme message tool
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result.result, ensure_ascii=False)[:8000],
                })

        # Si on sort de la boucle sans réponse finale, c'est qu'on a atteint max_iterations
        timings["total_ms"] = int((time.time() - t_total) * 1000)
        return Layer2Response(
            decision="ABSTAIN",
            answer="Layer 2 orchestrator a atteint le budget max sans converger.",
            n_iterations=self.max_iterations,
            tool_calls_log=tool_calls_log,
            abstention_reason="max_iterations_reached",
            latency_breakdown_ms=timings,
        )

    # ------------------------------------------------------------- internals
    def _llm_call(self, messages: list[dict], tools: list[dict]) -> dict:
        """Appel chat completion avec tool calling."""
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "temperature": 0.1,
            "max_tokens": 1500,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            timeout=self.timeout,
            transport=httpx.HTTPTransport(retries=0),
        ) as client:
            resp = client.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload, headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        return msg

    @staticmethod
    def _summarize_result(result: dict) -> str:
        """Résumé compact d'un tool result pour log."""
        if not isinstance(result, dict):
            return str(result)[:200]
        if "error" in result:
            return f"error: {result['error']}"
        if "decision" in result:
            return f"decision={result['decision']}, answer_len={len(result.get('answer', ''))}"
        if "n_chunks" in result:
            return f"n_chunks={result['n_chunks']}"
        return json.dumps(result, ensure_ascii=False)[:200]
