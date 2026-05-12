"""Re-run o3-mini sur les 30 questions (substitut o1-mini déprécié).

Ajoute la clé "A_o3mini_libre" dans openai_answers.json pour chaque question.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, "/app/src")
from neo4j import GraphDatabase
from knowbase.config.settings import get_settings
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.facts_first.evidence_collector import EvidenceCollector

OUT = Path("/app/data/benchmark/oracle_audit/openai_answers.json")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()

PROMPT = """Réponds à la question suivante en utilisant les passages fournis. Cite tes sources avec [doc=ID].

Question : {question}

Passages disponibles :
{chunks}

Réponse :"""


def call(prompt):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        json={"model": "o3-mini", "messages": [{"role": "user", "content": prompt}], "max_completion_tokens": 4000},
        timeout=600,
    )
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"].get("content", "") or ""
    usage = data.get("usage", {})
    inp = usage.get("prompt_tokens", 0)
    out = usage.get("completion_tokens", 0)
    cost = (inp / 1e6) * 1.10 + (out / 1e6) * 4.40
    return {"text": text, "usage": usage, "cost": cost, "error": None}


def format_chunks(claims):
    parts = []
    for c in claims[:80]:
        text = getattr(c, "quote", None) or ""
        doc_id = getattr(c, "doc_id", None) or "unknown"
        if text:
            parts.append(f"[doc={doc_id}] {text[:800]}")
    return "\n\n".join(parts)


def main():
    data = json.load(open(OUT))

    # Setup retriever
    settings = get_settings()
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
    driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
    retriever = ClaimRetriever(
        qdrant_client=qdrant, embedder=embedder, driver=driver,
        collection_name="knowbase_chunks_v2", tenant_id="default",
    )
    collector = EvidenceCollector(retriever=retriever, neo4j_driver=driver, tenant_id="default")

    total_cost = 0.0
    t0 = time.time()
    for i, q in enumerate(data["per_question"]):
        if "A_o3mini_libre" in q.get("answers", {}) and q["answers"]["A_o3mini_libre"].get("text"):
            continue  # skip déjà fait
        question = q["question"]
        try:
            claims = collector.collect(question=question, top_k=30, mode="single").claims
            chunks = format_chunks(claims)
        except Exception as e:
            print(f"[{i+1}] {q['question_id']} retrieval error: {e}")
            continue
        if not chunks:
            continue
        prompt = PROMPT.format(question=question, chunks=chunks[:120000])
        try:
            t1 = time.time()
            res = call(prompt)
            tg = int((time.time() - t1) * 1000)
            total_cost += res["cost"]
            print(f"[{i+1}/{len(data['per_question'])}] {q['question_id']} ({tg}ms, ${res['cost']:.3f}): {res['text'][:60]}...")
            q["answers"]["A_o3mini_libre"] = {**res, "latency_ms": tg, "model": "o3-mini", "chunks_used": "chunks_30"}
        except Exception as e:
            print(f"[{i+1}] {q['question_id']} ERROR: {e}")
            q["answers"]["A_o3mini_libre"] = {"text": "", "error": str(e), "cost": 0, "latency_ms": 0}

        # Sauvegarde incrémentale
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n=== Done. ${total_cost:.2f} en {elapsed:.0f}s ===")


if __name__ == "__main__":
    main()
