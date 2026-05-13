"""Smoke test V5.1 end-to-end avec vrai LLM HTTP (B3).

Branche :
- HTTPLLMCaller (Together AI prioritaire)
- ReasoningAgentV51 avec tracer + metrics
- Tools registry POC + V2
- ClaimSegmenter + GroundingVerifier (NoOp pour le smoke)

Run 1 question simple du panel quantitative_panel_10q.

Usage :
    docker exec knowbase-app python scripts/smoke_test_v51_http.py

Coût estimé : ~$0.02 / question (DeepSeek-V3.1).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure imports work
sys.path.insert(0, "/app/src" if Path("/app/src").exists() else "src")

from knowbase.runtime_v5.http_llm_caller import HTTPLLMCaller
from knowbase.runtime_v5.observability.metrics import MetricsRegistry
from knowbase.runtime_v5.observability.tracer import InMemoryTracer
from knowbase.runtime_v5.reasoning_agent_v51 import ReasoningAgentV51
from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import ToolRegistry, reset_default_registry
from knowbase.runtime_v5.tools.v2_tools_registration import register_v2_tools


def main():
    # Check API key
    has_together = bool(os.getenv("TOGETHER_API_KEY", "").strip())
    has_deepinfra = bool(os.getenv("DEEPINFRA_API_KEY", "").strip())
    if not (has_together or has_deepinfra):
        print("ERROR: no TOGETHER_API_KEY or DEEPINFRA_API_KEY in env")
        return 1
    provider = "Together AI" if has_together else "DeepInfra"
    print(f"Provider auto-detected: {provider}")

    # ─── Load panel question ─────────────────────────────────────────────
    panel_path = Path("/app/benchmark/questions/quantitative_panel_10q.json")
    if not panel_path.exists():
        print(f"ERROR: panel not found: {panel_path}")
        return 1
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    questions = panel.get("questions", [])
    if not questions:
        print("ERROR: panel empty")
        return 1

    # Use first question
    q = questions[0]
    question_text = q.get("question", "")
    expected_answer = (
        q.get("ground_truth", {}).get("answer", "")
        if isinstance(q.get("ground_truth"), dict)
        else q.get("ground_truth_text", "")
    )
    primary_type = q.get("primary_type", "?")
    print(f"\n─── Question ─────────────────────────────────────")
    print(f"ID: {q.get('id', '?')}")
    print(f"Type: {primary_type}")
    print(f"Q: {question_text[:200]}...")
    print(f"Expected: {expected_answer[:200]}...")

    # ─── Setup V5.1 agent ────────────────────────────────────────────────
    reset_default_registry()
    registry = ToolRegistry()
    register_poc_tools(registry)
    register_v2_tools(registry)
    print(f"\n─── Registry ───────────────────────────────────────")
    print(f"Public tools: {registry.stats()['n_public']}")
    print(f"Experimental: {registry.stats()['n_experimental']}")

    llm = HTTPLLMCaller(model="deepseek-ai/DeepSeek-V3.1")
    tracer = InMemoryTracer()
    metrics = MetricsRegistry()
    agent = ReasoningAgentV51(
        llm_caller=llm,
        registry=registry,
        tracer=tracer,
        metrics=metrics,
    )

    # ─── Run agent ───────────────────────────────────────────────────────
    print(f"\n─── Running V5.1 ReasoningAgent on real LLM... ─────")
    t0 = time.time()
    try:
        result = agent.run(
            question=question_text,
            tenant_id="default",
            answer_shape=primary_type,
        )
    except Exception as e:
        print(f"\nERROR during run: {type(e).__name__}: {e}")
        return 2
    duration = time.time() - t0

    # ─── Report ──────────────────────────────────────────────────────────
    print(f"\n─── Result ─────────────────────────────────────────")
    print(f"Status: {result.epistemic_status.value}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Latency: {duration:.2f}s")
    print(f"\nAnswer ({len(result.answer)} chars):")
    print(result.answer[:1500])
    print("..." if len(result.answer) > 1500 else "")

    ws_sum = result.workspace.summary()
    print(f"\n─── Workspace summary ──────────────────────────────")
    print(f"n_tool_calls: {ws_sum['n_tool_calls']}")
    print(f"n_evidence_items: {ws_sum['n_evidence_items']}")
    print(f"n_iterations: {result.workspace.budgets_snapshot.iterations}")
    print(f"output_tokens: {result.workspace.budgets_snapshot.output_tokens}")
    print(f"retrieved_chars: {result.workspace.budgets_snapshot.retrieved_chars}")
    print(f"repairs: {ws_sum['n_repairs']}")
    print(f"tool_errors: {ws_sum['n_tool_errors']}")

    # Trace summary
    root_spans = tracer.get_root_spans()
    inference_spans = tracer.get_spans_by_name("gen_ai.inference")
    tool_spans = tracer.get_spans_by_name("gen_ai.execute_tool")
    print(f"\n─── Tracer ─────────────────────────────────────────")
    print(f"root spans: {len(root_spans)}")
    print(f"inference spans: {len(inference_spans)}")
    print(f"tool execute spans: {len(tool_spans)}")
    if tool_spans:
        print(f"tools called: {[s.attributes.get('tool_name') for s in tool_spans]}")

    # Metrics
    snap = metrics.snapshot()
    print(f"\n─── Metrics ────────────────────────────────────────")
    print(f"counters: {list(snap['counters'].keys())}")
    print(f"histograms: {list(snap['histograms'].keys())}")

    # Verdict
    print(f"\n─── Verdict ────────────────────────────────────────")
    answer_ok = bool(result.answer and len(result.answer.strip()) > 10)
    has_citation = "[doc=" in result.answer or "[Source" in result.answer
    print(f"  ✓ answer non-empty: {answer_ok}")
    print(f"  ✓ has citation: {has_citation}")
    print(f"  ✓ status: {result.epistemic_status.value}")
    print(f"  ✓ latency: {duration:.2f}s (cible p50 ≤ 25s)")

    if not answer_ok:
        print("\n❌ SMOKE TEST FAILED")
        return 3
    print("\n✅ SMOKE TEST PASSED — V5.1 répond end-to-end via HTTPLLMCaller réel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
