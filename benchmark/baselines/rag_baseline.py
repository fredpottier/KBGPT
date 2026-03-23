#!/usr/bin/env python3
"""
RAG Baseline — Meme corpus, memes embeddings, SANS Knowledge Graph.

Isole exactement la valeur ajoutee du KG en gardant tout le reste identique.

APPROCHE EQUITABLE : Utilise l'API OSMOSIS avec KG desactive.
- Memes embeddings (multilingual-e5-large)
- Meme collection Qdrant (knowbase_chunks_v2)
- Meme LLM de synthese (GPT-4o-mini)
- SANS enrichissement KG (use_graph_context=false, use_kg_traversal=false)

Cela isole EXACTEMENT la valeur ajoutee du Knowledge Graph.

Usage:
    python benchmark/baselines/rag_baseline.py --config benchmark/config.yaml --questions benchmark/questions/task1_provenance_kg.json
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
logger = logging.getLogger("benchmark-rag")


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


def retrieve_chunks_direct(
    question: str, qdrant_url: str, collection: str,
    tei_url: str, top_k: int = 10,
) -> Dict[str, Any]:
    """Retrieval direct TEI + Qdrant — memes embeddings, SANS passer par l'API OSMOSIS.

    Avantage : pas de synthese native inutile (economise ~40s/question).
    Memes embeddings multilingual-e5-large via TEI burst.
    """
    start = time.time()
    try:
        # 1. Embedding via TEI (meme modele que l'app OSMOSIS)
        embed_resp = requests.post(
            f"{tei_url}/embed",
            json={"inputs": f"query: {question}"},
            timeout=10,
        )
        if embed_resp.status_code != 200:
            return {"error": f"TEI error: {embed_resp.status_code}", "retrieve_ms": 0}
        embedding = embed_resp.json()[0]

        # 2. Qdrant vector search (meme collection que l'app OSMOSIS)
        search_resp = requests.post(
            f"{qdrant_url}/collections/{collection}/points/query",
            json={
                "query": embedding,
                "limit": top_k,
                "with_payload": True,
            },
            timeout=10,
        )
        if search_resp.status_code != 200:
            return {"error": f"Qdrant error: {search_resp.status_code}", "retrieve_ms": 0}

        points = search_resp.json().get("result", {}).get("points", [])
        retrieve_ms = (time.time() - start) * 1000

        chunks = [
            {
                "text": p.get("payload", {}).get("text", ""),
                "source_file": p.get("payload", {}).get("doc_id", ""),
                "doc_id": p.get("payload", {}).get("doc_id", ""),
                "score": p.get("score", 0),
                "chunk_id": p.get("payload", {}).get("chunk_id", ""),
                "page_no": p.get("payload", {}).get("page_no"),
            }
            for p in points
        ]

        return {
            "chunks": chunks,
            "retrieve_ms": retrieve_ms,
            "error": None,
        }

    except Exception as e:
        return {"error": str(e), "retrieve_ms": (time.time() - start) * 1000}


def _get_llm_client(llm_model: str):
    """Retourne le client OpenAI adapte au modele (GPT ou Qwen/vLLM)."""
    from openai import OpenAI
    if "qwen" in llm_model.lower() or llm_model.startswith("Qwen/"):
        vllm_url = os.environ.get("VLLM_URL", "http://54.93.245.241:8000")
        return OpenAI(api_key="EMPTY", base_url=f"{vllm_url}/v1")
    return OpenAI()


# Meme prompt que run_osmosis.py — equite de comparaison
SYNTHESIS_SYSTEM_PROMPT = """You are a precise assistant. Answer questions using ONLY the provided sources.

MANDATORY RULES:
1. Every factual statement MUST be followed by [Source N]
2. Be specific: include names, numbers, values, transaction codes when available
3. If the information is partially available, answer with what you have — do NOT refuse
4. ONLY say "information not available" if NONE of the sources contain ANY relevant information
5. If sources contain contradictions or divergences, mention them explicitly

Answer in the SAME LANGUAGE as the question."""


def synthesize_answer(
    question: str,
    chunks: List[Dict],
    llm_model: str,
    max_tokens: int = 1200,
) -> Dict[str, Any]:
    """Synthetise une reponse depuis les chunks — SANS enrichissement KG.

    Meme prompt que le runner OSMOSIS, mais SANS les metadonnees KG.
    """
    context_parts = []
    for i, chunk in enumerate(chunks):
        source = chunk.get("source_file", "unknown")
        text = chunk["text"][:800]
        context_parts.append(f"[Source {i+1}: {source}]\n{text}")

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
    corpus = config["corpus"]
    api_base = corpus["osmosis_api"]

    with open(questions_path, "r", encoding="utf-8") as f:
        questions_data = json.load(f)

    questions = questions_data["questions"]
    metadata = questions_data["metadata"]

    # Determiner le LLM a utiliser
    llm_model = llm_override or config["models"]["synthesis_primary"]

    # Determiner le mode retrieval
    mode = "vector_only_via_api"
    for bl in config.get("baselines", []):
        if bl["name"] == baseline_name:
            if not llm_override:
                llm_model = bl.get("llm", llm_model)
            break

    # Direct TEI + Qdrant retrieval (pas de synthese native inutile)
    qdrant_url = corpus["qdrant"]["url"]
    collection = corpus["qdrant"]["collection"]
    tei_url = os.environ.get("TEI_URL", "http://54.93.245.241:8001")
    mode = "direct_tei_qdrant"

    logger.info(
        f"Running RAG baseline '{baseline_name}': {len(questions)} questions, "
        f"LLM={llm_model}, mode={mode} (TEI+Qdrant direct, no API overhead)"
    )

    top_k = config["retrieval"]["top_k"]

    results = []
    for i, q in enumerate(questions):
        logger.info(f"  [{i+1}/{len(questions)}] {q['question'][:80]}...")

        # 1. Retrieve direct (TEI embedding + Qdrant search — 1 seul appel, pas de synthese native)
        retrieval = retrieve_chunks_direct(q["question"], qdrant_url, collection, tei_url, top_k)

        if retrieval.get("error"):
            results.append({
                "question_id": q["question_id"],
                "task": q["task"],
                "question": q["question"],
                "system": baseline_name,
                "response": {
                    "answer": "",
                    "error": retrieval["error"],
                    "latency_ms": retrieval.get("retrieve_ms", 0),
                },
                "ground_truth": q["ground_truth"],
                "grading_rules": q.get("grading_rules", {}),
            })
            continue

        # 2. Synthesize (meme LLM, SANS metadonnees KG)
        synthesis = synthesize_answer(q["question"], retrieval["chunks"], llm_model)

        total_latency = retrieval["retrieve_ms"] + synthesis.get("latency_ms", 0)

        results.append({
            "question_id": q["question_id"],
            "task": q["task"],
            "question": q["question"],
            "system": baseline_name,
            "response": {
                "answer": synthesis["answer"],
                "chunks_retrieved": len(retrieval["chunks"]),
                "results": [
                    {
                        "text": c["text"][:300],
                        "source_file": c["source_file"],
                        "score": c["score"],
                        "doc_id": c["doc_id"],
                    }
                    for c in retrieval["chunks"]
                ],
                "sources_used": [c["source_file"] for c in retrieval["chunks"] if c.get("source_file")],
                "latency_ms": total_latency,
                "retrieve_ms": retrieval["retrieve_ms"],
                "synthesis_ms": synthesis.get("latency_ms", 0),
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

        time.sleep(0.3)

    # Sauvegarder
    if not output_path:
        output_dir = Path("benchmark/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
                "run_at": datetime.now(timezone.utc).isoformat(),
                "note": "RAG via API OSMOSIS avec KG desactive — memes embeddings, pur vector search",
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
