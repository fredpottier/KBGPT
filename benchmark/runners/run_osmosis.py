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
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _get_llm_client(llm_model: str):
    """Retourne le client OpenAI adapte au modele (GPT ou Qwen/vLLM)."""
    from openai import OpenAI
    if "qwen" in llm_model.lower() or llm_model.startswith("Qwen/"):
        vllm_url = os.environ.get("VLLM_URL", "http://63.178.18.3:8000")
        return OpenAI(api_key="EMPTY", base_url=f"{vllm_url}/v1")
    return OpenAI()


# Prompt de synthese renforce — identique entre OSMOSIS et RAG
# En anglais pour meilleur instruction-following Qwen 2.5
SYNTHESIS_SYSTEM_PROMPT = """You are a precise assistant. Answer questions using ONLY the provided sources.

MANDATORY RULES:
1. Every factual statement MUST be followed by [Source N]
2. Be specific: include names, numbers, values, transaction codes when available
3. If the information is partially available, answer with what you have — do NOT refuse
4. ONLY say "information not available" if NONE of the sources contain ANY relevant information
5. If sources contain contradictions or divergences, mention them explicitly
6. If [Contradiction] or [Entites] metadata is provided with a source, incorporate it in your answer

Answer in the SAME LANGUAGE as the question."""


def synthesize_with_standard_llm(
    question: str,
    chunks: List[Dict],
    llm_model: str = "gpt-4o",
    max_tokens: int = 1200,
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
            extra += f"\n  [Entites: {', '.join(entities[:5])}]"
        if contradictions:
            for contra in contradictions[:2]:
                if contra:
                    extra += f"\n  [Contradiction: {contra[:200]}]"
        context_parts.append(f"[Source {i+1}: {source}]{extra}\n{text}")

    context = "\n\n".join(context_parts)

    source_map_lines = []
    for i, chunk in enumerate(chunks):
        doc = chunk.get("source_file", "unknown")
        source_map_lines.append(f"  [Source {i+1}] = {doc}")
    source_map = "\n".join(source_map_lines)

    user_prompt = f"""Source mapping:
{source_map}

Sources:

{context}

Question: {question}

Answer (cite every source with [Source N]):"""

    start = time.time()
    try:
        client = _get_llm_client(llm_model)
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
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


def _process_one_question(args) -> Dict[str, Any]:
    """Traite une question (pour parallelisation via ThreadPoolExecutor)."""
    i, q, api_base, token, llm_model, total = args
    logger.info(f"  [{i+1}/{total}] {q['question'][:80]}...")

    retrieval = retrieve_osmosis(api_base, token, q["question"])

    if retrieval.get("error"):
        return {
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
        }

    # Synthesize avec le MEME LLM (GPT-4o-mini)
    synthesis = synthesize_with_standard_llm(
        q["question"], retrieval["chunks"], llm_model,
    )

    total_latency = retrieval["retrieve_ms"] + synthesis.get("synthesis_ms", 0)

    return {
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
    }


def run_benchmark(
    config_path: str,
    questions_path: str,
    output_path: str = None,
    max_workers: int = 4,
):
    """Execute le benchmark OSMOSIS avec parallelisation."""
    config = load_config(config_path)
    corpus = config["corpus"]
    api_base = corpus["osmosis_api"]
    llm_model = config["models"]["synthesis_primary"]

    with open(questions_path, "r", encoding="utf-8") as f:
        qdata = json.load(f)

    questions = qdata["questions"]
    metadata = qdata["metadata"]

    logger.info(f"Running OSMOSIS benchmark: {len(questions)} questions, {max_workers} workers")

    # Auth
    token = get_auth_token(api_base)
    logger.info("Auth OK")

    # Preparer les arguments pour le pool
    total = len(questions)
    args_list = [
        (i, q, api_base, token, llm_model, total)
        for i, q in enumerate(questions)
    ]

    # Execution parallele
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one_question, args): args[0] for args in args_list}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"  Question {idx} failed: {e}")
                q = questions[idx]
                results.append({
                    "question_id": q["question_id"],
                    "task": q["task"],
                    "question": q["question"],
                    "system": "osmosis",
                    "response": {"answer": "", "error": str(e), "latency_ms": 0},
                    "ground_truth": q["ground_truth"],
                    "grading_rules": q.get("grading_rules", {}),
                })

    # Trier par question_id pour reproductibilite
    results.sort(key=lambda r: r["question_id"])

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
                "max_workers": max_workers,
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
    parser.add_argument("--workers", type=int, default=4, help="Nombre de workers paralleles")
    args = parser.parse_args()

    run_benchmark(args.config, args.questions, args.output, args.workers)


if __name__ == "__main__":
    main()
