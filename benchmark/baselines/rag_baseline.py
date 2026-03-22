#!/usr/bin/env python3
"""
RAG Baseline — Meme corpus, meme embeddings, SANS Knowledge Graph.

Isole exactement la valeur ajoutee du KG en gardant tout le reste identique.

Usage:
    python benchmark/baselines/rag_baseline.py --config benchmark/config.yaml --questions benchmark/questions/task1_provenance_kg.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-rag")


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_rag_chain(config: dict, mode: str = "vector_only"):
    """Construit le pipeline RAG sans KG.

    mode:
      - vector_only: Qdrant vector search uniquement
      - bm25_vector: BM25 + vector hybrid (si disponible)
    """
    from qdrant_client import QdrantClient
    from sentence_transformers import SentenceTransformer

    qdrant_cfg = config["corpus"]["qdrant"]
    client = QdrantClient(url=qdrant_cfg["url"])
    model = SentenceTransformer(config["models"]["embedding"])

    return {
        "qdrant": client,
        "collection": qdrant_cfg["collection"],
        "model": model,
        "top_k": config["retrieval"]["top_k"],
        "score_threshold": config["retrieval"]["score_threshold"],
        "max_context_tokens": config["retrieval"]["max_context_tokens"],
        "mode": mode,
    }


def retrieve_chunks(chain: dict, question: str) -> List[Dict]:
    """Recherche vectorielle pure dans Qdrant — SANS Neo4j."""
    from qdrant_client.models import models

    embedding = chain["model"].encode(
        f"query: {question}",
        normalize_embeddings=True,
    ).tolist()

    try:
        # Qdrant client >= 1.12
        results = chain["qdrant"].query_points(
            collection_name=chain["collection"],
            query=embedding,
            limit=chain["top_k"],
            score_threshold=chain["score_threshold"],
        ).points
    except (AttributeError, TypeError):
        # Fallback: anciennes versions
        results = chain["qdrant"].search(
            collection_name=chain["collection"],
            query_vector=embedding,
            limit=chain["top_k"],
            score_threshold=chain["score_threshold"],
        )

    chunks = []
    for hit in results:
        payload = hit.payload or {}
        chunks.append({
            "text": payload.get("text", ""),
            "source_file": payload.get("source_file", payload.get("document_name", "")),
            "doc_id": payload.get("doc_id", payload.get("document_id", "")),
            "score": hit.score,
            "chunk_id": payload.get("chunk_id", ""),
            "page_no": payload.get("page_no"),
        })

    return chunks


def synthesize_answer(
    question: str,
    chunks: List[Dict],
    llm_model: str,
    max_tokens: int = 1500,
) -> Dict[str, Any]:
    """Synthetise une reponse depuis les chunks — SANS enrichissement KG."""

    # Construire le contexte depuis les chunks
    context_parts = []
    for i, chunk in enumerate(chunks):
        source = chunk.get("source_file", "unknown")
        text = chunk["text"][:800]
        context_parts.append(f"[Source {i+1}: {source}]\n{text}")

    context = "\n\n".join(context_parts)

    system_prompt = """Tu es un assistant qui repond aux questions en se basant UNIQUEMENT sur les sources fournies.
Regles:
- Cite tes sources avec [Source N] apres chaque affirmation
- Si l'information n'est pas dans les sources, dis "Je ne dispose pas de cette information dans les documents fournis."
- Ne fabrique pas d'information
- Sois precis et factuel"""

    user_prompt = f"""Sources disponibles:

{context}

Question: {question}

Reponse (avec citations [Source N]):"""

    # Appel LLM
    start = time.time()
    try:
        if "claude" in llm_model.lower():
            answer, tokens = _call_claude(system_prompt, user_prompt, llm_model, max_tokens)
        else:
            answer, tokens = _call_openai(system_prompt, user_prompt, llm_model, max_tokens)

        latency_ms = (time.time() - start) * 1000
        return {
            "answer": answer,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as e:
        return {
            "answer": "",
            "tokens": 0,
            "latency_ms": (time.time() - start) * 1000,
            "error": str(e),
        }


def _call_openai(system: str, user: str, model: str, max_tokens: int):
    from openai import OpenAI
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0,
    )
    answer = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0
    return answer, tokens


def _call_claude(system: str, user: str, model: str, max_tokens: int):
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0,
    )
    answer = response.content[0].text if response.content else ""
    tokens = (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0
    return answer, tokens


def run_rag_benchmark(
    config_path: str,
    questions_path: str,
    baseline_name: str = "rag_claim",
    llm_override: str = None,
    output_path: str = None,
):
    config = load_config(config_path)

    with open(questions_path, "r", encoding="utf-8") as f:
        questions_data = json.load(f)

    questions = questions_data["questions"]
    metadata = questions_data["metadata"]

    # Determiner le LLM a utiliser
    llm_model = llm_override or config["models"]["synthesis_primary"]

    # Determiner le mode retrieval
    mode = "vector_only"
    for bl in config.get("baselines", []):
        if bl["name"] == baseline_name:
            mode = bl.get("retrieval", "vector_only")
            if not llm_override:
                llm_model = bl.get("llm", llm_model)
            break

    logger.info(
        f"Running RAG baseline '{baseline_name}': {len(questions)} questions, "
        f"LLM={llm_model}, mode={mode}"
    )

    chain = build_rag_chain(config, mode)

    results = []
    for i, q in enumerate(questions):
        logger.info(f"  [{i+1}/{len(questions)}] {q['question'][:80]}...")

        # 1. Retrieve
        retrieve_start = time.time()
        chunks = retrieve_chunks(chain, q["question"])
        retrieve_ms = (time.time() - retrieve_start) * 1000

        # 2. Synthesize
        synthesis = synthesize_answer(q["question"], chunks, llm_model)

        results.append({
            "question_id": q["question_id"],
            "task": q["task"],
            "question": q["question"],
            "system": baseline_name,
            "response": {
                "answer": synthesis["answer"],
                "chunks_retrieved": len(chunks),
                "chunks": [
                    {
                        "text": c["text"][:300],
                        "source_file": c["source_file"],
                        "score": c["score"],
                        "doc_id": c["doc_id"],
                    }
                    for c in chunks
                ],
                "latency_ms": retrieve_ms + synthesis["latency_ms"],
                "retrieve_ms": retrieve_ms,
                "synthesis_ms": synthesis["latency_ms"],
                "tokens": synthesis["tokens"],
                "error": synthesis["error"],
                # RAG n'a PAS ces champs (c'est le point)
                "entity_names": [],
                "contradiction_texts": [],
                "graph_context": None,
                "insight_hints": [],
                "related_articles": [],
            },
            "ground_truth": q["ground_truth"],
            "grading_rules": q.get("grading_rules", {}),
        })

        time.sleep(0.5)

    # Sauvegarder
    if not output_path:
        output_dir = Path("benchmark/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"{baseline_name}_{metadata['task']}_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "system": baseline_name,
                "llm_model": llm_model,
                "retrieval_mode": mode,
                "task": metadata["task"],
                "corpus": metadata["corpus"],
                "questions_count": len(results),
                "run_at": datetime.utcnow().isoformat(),
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    errors = sum(1 for r in results if r["response"].get("error"))
    avg_latency = sum(r["response"].get("latency_ms", 0) for r in results) / max(len(results), 1)
    logger.info(f"Done: {len(results)} questions, {errors} errors, avg latency {avg_latency:.0f}ms")
    logger.info(f"Results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Run RAG baseline benchmark")
    parser.add_argument("--config", default="benchmark/config.yaml")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--baseline", default="rag_claim",
                        choices=["rag_claim", "rag_hybrid", "chatgpt_context", "claude_context"])
    parser.add_argument("--llm", default=None, help="Override LLM model")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    run_rag_benchmark(args.config, args.questions, args.baseline, args.llm, args.output)


if __name__ == "__main__":
    main()
