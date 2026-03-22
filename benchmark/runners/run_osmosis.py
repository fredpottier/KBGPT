#!/usr/bin/env python3
"""
Runner OSMOSIS — Interroge l'API OSMOSIS pour chaque question du benchmark.

IMPORTANT: Pour un benchmark equitable, la synthese est faite avec le MEME LLM
que le RAG baseline (GPT-4o par defaut). Seul le retrieval + enrichissement KG differe.

Pipeline:
1. Appel API OSMOSIS /api/search → chunks enrichis (entites, contradictions, graph context)
2. Synthese GPT-4o avec le MEME prompt que le RAG baseline
3. Capture des metadonnees KG (contradictions, entities, insight hints)

Usage:
    python benchmark/runners/run_osmosis.py --config benchmark/config.yaml --questions benchmark/questions/task1_provenance_kg.json
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
logger = logging.getLogger("benchmark-osmosis")


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
    raise RuntimeError(f"Auth failed: {resp.status_code} {resp.text[:200]}")


def retrieve_osmosis(api_base: str, token: str, question: str) -> Dict[str, Any]:
    """Appelle l'API OSMOSIS pour recuperer les chunks enrichis (SANS synthese LLM)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "question": question,
        "use_graph_context": True,
        "graph_enrichment_level": "standard",
        "use_graph_first": True,
        "use_kg_traversal": True,
        "use_latest": True,
    }

    start = time.time()
    try:
        resp = requests.post(
            f"{api_base}/api/search",
            json=payload,
            headers=headers,
            timeout=120,
        )
        retrieve_ms = (time.time() - start) * 1000

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}", "retrieve_ms": retrieve_ms}

        data = resp.json()
        results = data.get("results", [])

        return {
            "chunks": [
                {
                    "text": r.get("text", ""),
                    "source_file": r.get("source_file", ""),
                    "score": r.get("score", 0),
                    "doc_id": r.get("source_file", ""),
                    "claim_id": r.get("claim_id"),
                    "entity_names": r.get("entity_names", []),
                    "contradiction_texts": r.get("contradiction_texts", []),
                    "source_type": r.get("source_type", ""),
                }
                for r in results[:10]
            ],
            "graph_context": data.get("graph_context", {}),
            "related_articles": data.get("related_articles", []),
            "insight_hints": data.get("insight_hints", []),
            "cross_doc_comparisons": data.get("cross_doc_comparisons", []),
            # Capturer la synthese OSMOSIS native pour comparaison secondaire
            "native_synthesis": data.get("synthesis", {}).get("synthesized_answer", ""),
            "native_confidence": data.get("synthesis", {}).get("confidence", 0),
            "retrieve_ms": retrieve_ms,
            "error": None,
        }

    except requests.Timeout:
        return {"error": "Timeout (120s)", "retrieve_ms": 120000}
    except Exception as e:
        return {"error": str(e), "retrieve_ms": (time.time() - start) * 1000}


def synthesize_with_standard_llm(
    question: str,
    chunks: List[Dict],
    llm_model: str = "gpt-4o",
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    """Synthetise avec le MEME LLM et le MEME prompt que le RAG baseline.

    Seule difference : les chunks OSMOSIS contiennent des metadonnees KG
    (entity_names, contradiction_texts) que le prompt peut exploiter.
    """
    context_parts = []
    for i, chunk in enumerate(chunks):
        source = chunk.get("source_file", "unknown")
        text = chunk["text"][:800]
        # OSMOSIS ajoute : entites et contradictions dans le contexte
        extra = ""
        entities = chunk.get("entity_names", [])
        contradictions = chunk.get("contradiction_texts", [])
        if entities:
            extra += f"\n  [Entites: {', '.join(entities[:3])}]"
        if contradictions:
            extra += f"\n  [Contradiction: {contradictions[0][:150]}]"
        context_parts.append(f"[Source {i+1}: {source}]{extra}\n{text}")

    context = "\n\n".join(context_parts)

    system_prompt = """Tu es un assistant qui repond aux questions en se basant UNIQUEMENT sur les sources fournies.
Regles:
- Cite tes sources avec [Source N] apres chaque affirmation
- Si l'information n'est pas dans les sources, dis "Je ne dispose pas de cette information dans les documents fournis."
- Ne fabrique pas d'information
- Sois precis et factuel
- Si des contradictions sont signalees entre sources, mentionne-les explicitement"""

    user_prompt = f"""Sources disponibles:

{context}

Question: {question}

Reponse (avec citations [Source N]):"""

    start = time.time()
    try:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0,
        )
        answer = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        synthesis_ms = (time.time() - start) * 1000

        return {
            "answer": answer,
            "tokens": tokens,
            "synthesis_ms": synthesis_ms,
            "error": None,
        }
    except Exception as e:
        return {
            "answer": "",
            "tokens": 0,
            "synthesis_ms": (time.time() - start) * 1000,
            "error": str(e),
        }


def run_benchmark(config_path: str, questions_path: str, output_path: str = None):
    config = load_config(config_path)
    api_base = config["corpus"]["osmosis_api"]
    llm_model = config["models"]["synthesis_primary"]

    with open(questions_path, "r", encoding="utf-8") as f:
        questions_data = json.load(f)

    questions = questions_data["questions"]
    metadata = questions_data["metadata"]

    logger.info(f"Running OSMOSIS benchmark: {len(questions)} questions, LLM={llm_model}")

    token = get_auth_token(api_base)
    logger.info("Authenticated with OSMOSIS API")

    results = []
    for i, q in enumerate(questions):
        logger.info(f"  [{i+1}/{len(questions)}] {q['question'][:80]}...")

        # 1. Retrieve via OSMOSIS (KG-enriched)
        retrieval = retrieve_osmosis(api_base, token, q["question"])

        if retrieval.get("error"):
            results.append({
                "question_id": q["question_id"],
                "task": q["task"],
                "question": q["question"],
                "system": "osmosis",
                "response": {
                    "answer": "",
                    "error": retrieval["error"],
                    "latency_ms": retrieval.get("retrieve_ms", 0),
                },
                "ground_truth": q["ground_truth"],
                "grading_rules": q.get("grading_rules", {}),
            })
            continue

        # 2. Synthesize avec le MEME LLM (GPT-4o)
        synthesis = synthesize_with_standard_llm(
            q["question"], retrieval["chunks"], llm_model,
        )

        total_latency = retrieval["retrieve_ms"] + synthesis.get("synthesis_ms", 0)

        results.append({
            "question_id": q["question_id"],
            "task": q["task"],
            "question": q["question"],
            "system": "osmosis",
            "response": {
                "answer": synthesis["answer"],
                "native_synthesis": retrieval.get("native_synthesis", ""),
                "chunks_retrieved": len(retrieval["chunks"]),
                "results": retrieval["chunks"],
                "sources_used": [c["source_file"] for c in retrieval["chunks"] if c.get("source_file")],
                # Metadonnees KG (ce que RAG n'a PAS)
                "entity_names": list(set(
                    e for c in retrieval["chunks"] for e in c.get("entity_names", [])
                )),
                "contradiction_texts": list(set(
                    t for c in retrieval["chunks"] for t in c.get("contradiction_texts", [])
                )),
                "graph_context": retrieval.get("graph_context", {}),
                "related_articles": retrieval.get("related_articles", []),
                "insight_hints": retrieval.get("insight_hints", []),
                "cross_doc_comparisons": retrieval.get("cross_doc_comparisons", []),
                # Timing
                "latency_ms": total_latency,
                "retrieve_ms": retrieval["retrieve_ms"],
                "synthesis_ms": synthesis.get("synthesis_ms", 0),
                "tokens": synthesis.get("tokens", 0),
                "error": synthesis.get("error"),
            },
            "ground_truth": q["ground_truth"],
            "grading_rules": q.get("grading_rules", {}),
        })

        time.sleep(0.5)

    # Sauvegarder
    if not output_path:
        output_dir = Path("benchmark/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"osmosis_{metadata['task']}_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "system": "osmosis",
                "llm_model": llm_model,
                "task": metadata["task"],
                "corpus": metadata["corpus"],
                "questions_count": len(results),
                "run_at": datetime.now(timezone.utc).isoformat(),
                "config": config_path,
                "api_base": api_base,
                "note": "Synthese faite avec le MEME LLM que le RAG baseline (equitable)",
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    errors = sum(1 for r in results if r["response"].get("error"))
    avg_latency = sum(r["response"].get("latency_ms", 0) for r in results) / max(len(results), 1)
    logger.info(f"Done: {len(results)} questions, {errors} errors, avg latency {avg_latency:.0f}ms")
    logger.info(f"Results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Run OSMOSIS benchmark (equitable LLM)")
    parser.add_argument("--config", default="benchmark/config.yaml")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    run_benchmark(args.config, args.questions, args.output)


if __name__ == "__main__":
    main()
