"""B4 — Bake-off rapide V5.1 sur 3 modèles × 3 questions.

Objectif : identifier le modèle qui :
1. Produit le moins de tool_calls "fantômes" (texte avec ｜tool▁calls▁begin｜
   dans content au lieu de tool_calls structurés)
2. Réponse propre avec citations
3. Latence raisonnable

Modèles testés (charte OSMOSIS open-source serverless via Together AI) :
- deepseek-ai/DeepSeek-V3.1 (baseline current)
- Qwen/Qwen2.5-72B-Instruct-Turbo
- meta-llama/Llama-3.3-70B-Instruct-Turbo

Questions samples panel quantitative (3 représentatives) :
- Q1 SLA quantitative (a marché OK avec DeepSeek)
- Q2 OS updates quantitative (quirk DeepSeek)
- Q6 LoB factual (sans citations)
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src" if Path("/app/src").exists() else "src")

from knowbase.runtime_v5.http_llm_caller import HTTPLLMCaller
from knowbase.runtime_v5.reasoning_agent_v51 import ReasoningAgentV51
from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import ToolRegistry, reset_default_registry
from knowbase.runtime_v5.tools.v2_tools_registration import register_v2_tools


CANDIDATE_MODELS = [
    "deepseek-ai/DeepSeek-V3.1",
    "Qwen/Qwen2.5-72B-Instruct-Turbo",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
]


# Pattern pour détecter les tool_calls fantômes dans le content
PHANTOM_TOOL_CALL_PATTERN = re.compile(
    r"[｜|]tool[▁_]calls?[▁_](?:begin|sep|end)[｜|]|"
    r"<tool[_-]call>|"
    r"\bfunction_call\b.*\{",
    re.IGNORECASE,
)


def has_phantom_tool_call(answer_text: str) -> bool:
    """True si l'answer contient des tokens de tool_call fantômes."""
    if not answer_text:
        return False
    return bool(PHANTOM_TOOL_CALL_PATTERN.search(answer_text))


def has_citation(answer_text: str) -> bool:
    if not answer_text:
        return False
    return bool(re.search(r"\[doc=[\w]+|\[Source\s+\d+", answer_text))


def run_one(model: str, q: dict, registry: ToolRegistry) -> dict:
    """Lance une question sur un modèle. Force un nouveau caller à chaque fois
    pour bien isoler le modèle."""
    llm = HTTPLLMCaller(model=model, force_provider="together")
    agent = ReasoningAgentV51(llm_caller=llm, registry=registry)

    t0 = time.time()
    try:
        result = agent.run(
            question=q.get("question", ""),
            tenant_id="default",
            answer_shape=q.get("primary_type"),
        )
        latency = time.time() - t0
        answer = result.answer or ""
        return {
            "qid": q.get("id"),
            "model": model,
            "latency_s": round(latency, 2),
            "agent_latency_s": round(result.latency_s, 2),
            "status": result.epistemic_status.value,
            "stop_reason": result.stop_reason,
            "n_iterations": result.workspace.budgets_snapshot.iterations,
            "n_tool_calls": result.workspace.budgets_snapshot.tool_calls,
            "n_evidence": len(result.workspace.evidence_collected),
            "output_tokens": result.workspace.budgets_snapshot.output_tokens,
            "answer_chars": len(answer),
            "phantom_tool_call": has_phantom_tool_call(answer),
            "has_citation": has_citation(answer),
            "answer_preview": answer[:600],
        }
    except Exception as e:
        return {
            "qid": q.get("id"),
            "model": model,
            "error": f"{type(e).__name__}: {e}",
            "latency_s": round(time.time() - t0, 2),
        }


def main():
    panel_path = Path("/app/benchmark/questions/quantitative_panel_10q.json")
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    qs = panel["questions"]

    # Sample : Q1 (SLA, OK avec DeepSeek), Q2 (OS updates, fantôme), Q6 (LoB factual)
    sample_indices = [0, 1, 5]
    sample_qs = [qs[i] for i in sample_indices]

    print(f"=== Bake-off V5.1 ===")
    print(f"Modèles : {len(CANDIDATE_MODELS)}")
    for m in CANDIDATE_MODELS:
        print(f"  - {m}")
    print(f"Questions (sample {len(sample_qs)}) :")
    for q in sample_qs:
        print(f"  - {q.get('id')} [{q.get('primary_type')}] : {q.get('question','')[:80]}...")

    # Setup registry (shared across models)
    reset_default_registry()
    registry = ToolRegistry()
    register_poc_tools(registry)
    register_v2_tools(registry)

    # Run all combinations
    runs = []
    for model in CANDIDATE_MODELS:
        print(f"\n--- Model: {model} ---")
        for q in sample_qs:
            print(f"  Q{q.get('id')} ({q.get('primary_type')})...")
            r = run_one(model, q, registry)
            runs.append(r)
            if "error" in r:
                print(f"    ❌ {r['error']}")
            else:
                flags = []
                if r["phantom_tool_call"]:
                    flags.append("PHANTOM")
                if r["has_citation"]:
                    flags.append("CITED")
                print(f"    {r['latency_s']}s · {r['n_iterations']}it · {r['n_tool_calls']}tc "
                      f"· {r['n_evidence']}ev · {r['output_tokens']}tok · {r['answer_chars']}c · "
                      f"{'|'.join(flags) or '—'}")

    # ─── Aggregate by model ──────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"AGGREGATE BY MODEL")
    print(f"{'=' * 70}")
    by_model: dict[str, list[dict]] = {}
    for r in runs:
        by_model.setdefault(r["model"], []).append(r)

    summary = []
    for model, rs in by_model.items():
        errors = [r for r in rs if "error" in r]
        ok = [r for r in rs if "error" not in r]
        phantom_rate = sum(1 for r in ok if r["phantom_tool_call"]) / len(ok) if ok else 0
        citation_rate = sum(1 for r in ok if r["has_citation"]) / len(ok) if ok else 0
        avg_latency = statistics.mean(r["latency_s"] for r in ok) if ok else 0
        avg_iter = statistics.mean(r["n_iterations"] for r in ok) if ok else 0
        avg_tools = statistics.mean(r["n_tool_calls"] for r in ok) if ok else 0
        avg_evidence = statistics.mean(r["n_evidence"] for r in ok) if ok else 0

        s = {
            "model": model,
            "n_completed": len(ok),
            "n_errors": len(errors),
            "phantom_rate": round(phantom_rate, 2),
            "citation_rate": round(citation_rate, 2),
            "avg_latency_s": round(avg_latency, 1),
            "avg_iterations": round(avg_iter, 1),
            "avg_tool_calls": round(avg_tools, 1),
            "avg_evidence": round(avg_evidence, 1),
        }
        summary.append(s)
        print(f"\n{model}")
        print(f"  completed={len(ok)}/{len(rs)}  errors={len(errors)}")
        print(f"  phantom_rate={phantom_rate:.0%}  citation_rate={citation_rate:.0%}")
        print(f"  avg_latency={avg_latency:.1f}s  avg_iter={avg_iter:.1f}  avg_tools={avg_tools:.1f}  avg_evidence={avg_evidence:.1f}")

    # Winner suggestion
    print(f"\n{'=' * 70}")
    print(f"WINNER SUGGESTION")
    print(f"{'=' * 70}")
    # Score : phantom_rate=bad (poids fort), citation_rate=good, latency=lower better
    def score(s):
        p = (1.0 - s["phantom_rate"]) * 3.0  # poids 3 (très important)
        c = s["citation_rate"] * 2.0  # poids 2
        l = max(0, 1 - s["avg_latency_s"] / 60.0)  # 60s = 0, 0s = 1
        return p + c + l
    summary.sort(key=score, reverse=True)
    print(f"\nRanking (score = (1-phantom)×3 + citation×2 + (1-latency/60)):")
    for i, s in enumerate(summary):
        print(f"  {i+1}. {s['model']} : score={score(s):.2f}")
        print(f"      phantom={s['phantom_rate']:.0%} cite={s['citation_rate']:.0%} "
              f"lat={s['avg_latency_s']}s iter={s['avg_iterations']} ev={s['avg_evidence']}")

    if summary:
        winner = summary[0]
        print(f"\n→ Winner suggéré : {winner['model']}")

    # Persist
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(f"/app/benchmark/runs/bakeoff_models_{ts}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "ts": ts,
            "models": CANDIDATE_MODELS,
            "n_questions": len(sample_qs),
            "panel_source": str(panel_path),
        },
        "runs": runs,
        "summary": summary,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
