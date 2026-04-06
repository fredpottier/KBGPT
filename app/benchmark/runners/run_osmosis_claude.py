#!/usr/bin/env python3
"""
Benchmark OSMOSIS full-pipeline avec Claude Sonnet comme LLM de synthese.

Compare la qualite de synthese entre le LLM local (Qwen) et Claude Sonnet
sur les MEMES chunks OSMOSIS (retrieval identique, seule la synthese change).

Usage:
    python benchmark/runners/run_osmosis_claude.py \
        --config benchmark/config.yaml \
        --questions benchmark/questions/task1_provenance_human.json \
        --output benchmark/results/20260325_sprint2/osmosis_T1_human_claude.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-osmosis-claude")

CLAUDE_MODEL = "claude-sonnet-4-20250514"

SYNTHESIS_SYSTEM_PROMPT = """You are a precise document analysis assistant. Answer questions using ONLY the provided sources.

MANDATORY RULES:
1. Every factual statement MUST be followed by [Source N]
2. Be specific: include names, numbers, values, transaction codes when available
3. If the information is partially available, answer with what you have — do NOT refuse
4. ONLY say "information not available" if NONE of the sources contain ANY relevant information
5. If sources contain contradictions or divergences, mention them explicitly

Answer in the SAME LANGUAGE as the question."""


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_auth_token(api_base: str) -> str:
    resp = requests.post(
        f"{api_base}/api/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json().get("access_token", "")
    raise RuntimeError(f"Auth failed: {resp.status_code}")


def retrieve_osmosis(api_base: str, token: str, question: str) -> Dict[str, Any]:
    """Appelle l'API OSMOSIS pour recuperer les chunks enrichis + synthese native."""
    resp = requests.post(
        f"{api_base}/api/search",
        json={
            "question": question,
            "use_graph_context": True,
            "graph_enrichment_level": "standard",
            "use_graph_first": True,
            "use_kg_traversal": True,
            "use_latest": True,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    retrieve_ms = 0
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "retrieve_ms": 0}

    data = resp.json()
    results = data.get("results", [])
    return {
        "chunks": [
            {
                "text": r.get("text", ""),
                "source_file": r.get("source_file", ""),
                "score": r.get("score", 0),
                "doc_id": r.get("source_file", ""),
            }
            for r in results[:10]
        ],
        "native_synthesis": data.get("synthesis", {}).get("synthesized_answer", ""),
        "signal_report": data.get("signal_report"),
        "retrieve_ms": retrieve_ms,
        "error": None,
    }


def synthesize_with_claude(question: str, chunks: List[Dict], max_tokens: int = 1500) -> Dict[str, Any]:
    """Synthetise avec Claude Sonnet via l'API Anthropic."""
    import anthropic

    context_parts = []
    for i, chunk in enumerate(chunks):
        source = chunk.get("source_file", "unknown")
        text = chunk["text"][:800]
        context_parts.append(f"[Source {i+1}: {source}]\n{text}")
    context = "\n\n".join(context_parts)

    source_map_lines = [f"  [Source {i+1}] = {c.get('source_file', 'unknown')}" for i, c in enumerate(chunks)]
    source_map = "\n".join(source_map_lines)

    user_prompt = f"""Source mapping:
{source_map}

Sources:

{context}

Question: {question}

Answer (cite every source with [Source N]):"""

    start = time.time()
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0,
        )
        answer = response.content[0].text if response.content else ""
        tokens = (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0
        synthesis_ms = (time.time() - start) * 1000
        return {"answer": answer, "tokens": tokens, "synthesis_ms": synthesis_ms, "error": None}
    except Exception as e:
        return {"answer": "", "tokens": 0, "synthesis_ms": (time.time() - start) * 1000, "error": str(e)}


def run_benchmark(config_path: str, questions_path: str, output_path: str = None):
    config = load_config(config_path)
    corpus = config["corpus"]
    api_base = corpus["osmosis_api"]

    with open(questions_path, "r", encoding="utf-8") as f:
        qdata = json.load(f)
    questions = qdata["questions"]
    metadata = qdata["metadata"]

    logger.info(f"Running OSMOSIS+Claude benchmark: {len(questions)} questions, model={CLAUDE_MODEL}")

    token = get_auth_token(api_base)
    logger.info("Auth OK")

    results = []
    for i, q in enumerate(questions):
        logger.info(f"  [{i+1}/{len(questions)}] {q['question'][:80]}...")

        retrieval = retrieve_osmosis(api_base, token, q["question"])
        if retrieval.get("error"):
            results.append({
                "question_id": q["question_id"], "task": q["task"],
                "question": q["question"], "system": "osmosis_claude",
                "response": {"answer": "", "error": retrieval["error"], "latency_ms": 0},
                "ground_truth": q["ground_truth"], "grading_rules": q.get("grading_rules", {}),
            })
            continue

        synthesis = synthesize_with_claude(q["question"], retrieval["chunks"])

        results.append({
            "question_id": q["question_id"],
            "task": q["task"],
            "question": q["question"],
            "system": "osmosis_claude",
            "response": {
                "answer": synthesis["answer"],
                "native_synthesis": retrieval.get("native_synthesis", ""),
                "chunks_retrieved": len(retrieval["chunks"]),
                "results": [{"text": c["text"][:300], "source_file": c["source_file"], "score": c["score"]} for c in retrieval["chunks"]],
                "sources_used": [c["source_file"] for c in retrieval["chunks"] if c.get("source_file")],
                "signal_report": retrieval.get("signal_report"),
                "latency_ms": retrieval["retrieve_ms"] + synthesis.get("synthesis_ms", 0),
                "synthesis_ms": synthesis.get("synthesis_ms", 0),
                "tokens": synthesis.get("tokens", 0),
                "error": synthesis.get("error"),
            },
            "ground_truth": q["ground_truth"],
            "grading_rules": q.get("grading_rules", {}),
        })
        time.sleep(0.5)  # rate limit Anthropic

    results.sort(key=lambda r: r["question_id"])

    if not output_path:
        output_dir = Path("benchmark/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"osmosis_claude_{metadata['task']}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "system": "osmosis_claude",
                "llm_model": CLAUDE_MODEL,
                "task": metadata["task"],
                "corpus": metadata.get("corpus", "SAP Enterprise Documentation"),
                "questions_count": len(results),
                "run_at": datetime.now(timezone.utc).isoformat(),
                "note": "OSMOSIS retrieval + Claude Sonnet synthesis (memes chunks, LLM different)",
                "full_pipeline": True,
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    errors = sum(1 for r in results if r["response"].get("error"))
    logger.info(f"Done: {len(results)} questions, {errors} errors")
    logger.info(f"Results saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSMOSIS + Claude Sonnet benchmark")
    parser.add_argument("--config", default="benchmark/config.yaml")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    run_benchmark(args.config, args.questions, args.output)
