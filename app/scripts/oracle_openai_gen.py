"""Mesure 1 — Tests OpenAI : isolation modèle frontier × archi.

Tests :
  A. GPT-4o + o1-mini sur 30q × 1B (top_k=30) avec prompt LIBRE
  B. GPT-4o sur 30q × 1B avec prompt STRICT V4.2 (= Layer 0 V4.2 prompt)
  C. GPT-4o sur 30q × 1B-ext (top_k=60) avec prompt LIBRE — voir si plus de contexte aide
  E. o1 sur 30q × 1B avec prompt LIBRE — plafond reasoning frontier

Budget tracker stricte (abort si > 30$ cumulés).

Output : /app/data/benchmark/oracle_audit/openai_answers.json
"""
import json
import os
import re
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

SAMPLE = "/app/data/benchmark/oracle_audit/oracle_audit_sample.json"
OUT = Path("/app/data/benchmark/oracle_audit/openai_answers.json")

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if not OPENAI_KEY:
    print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
    sys.exit(1)

# Pricing OpenAI ($/1M tokens) — au 2026-05
PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "o1-mini": {"input": 1.10, "output": 4.40},
    "o1": {"input": 15.0, "output": 60.0},
}

# Tests configuration
PROMPT_LIBRE = """Réponds à la question suivante en utilisant les passages fournis. Cite tes sources avec [doc=ID].

Question : {question}

Passages disponibles :
{chunks}

Réponse :"""

PROMPT_V4_2_STRICT = """You are a documentary assistant. Answer the user's question using ONLY the evidence chunks provided.

Rules:
- If the answer is clearly supported by the chunks, give a concise direct answer with citations [doc=ID]
- If multiple chunks contradict, mention both with citations
- If the chunks don't contain the answer, respond exactly: "La reponse a votre question n'a pas ete trouvee dans les documents disponibles."
- Stay concise: 1-3 sentences max
- Always include [doc=...] citations when claiming a fact

Format your answer as plain text, no JSON.

Question: {question}

Evidence chunks:
{chunks}

Answer:"""

# Tests : (test_label, model_key, prompt_template, chunks_field)
# chunks_field: "chunks_30" (top_k=30, 1B) ou "chunks_60" (top_k=60, 1B-ext)
TESTS = [
    ("A_gpt4o_libre", "gpt-4o", PROMPT_LIBRE, "chunks_30"),
    ("A_o1mini_libre", "o1-mini", PROMPT_LIBRE, "chunks_30"),
    ("B_gpt4o_strict", "gpt-4o", PROMPT_V4_2_STRICT, "chunks_30"),
    ("C_gpt4o_extended", "gpt-4o", PROMPT_LIBRE, "chunks_60"),
    ("E_o1_libre", "o1", PROMPT_LIBRE, "chunks_30"),
]

# Budget tracker (abort si dépasse)
BUDGET_HARD_CAP = 30.0  # USD (marge sur les 34$ disponibles)
budget_used = {"total": 0.0, "by_model": {}}


def call_openai(model_key: str, prompt: str, max_tokens: int = 800, max_retries: int = 3) -> dict:
    """Call OpenAI API. Pour o1/o1-mini : pas de temperature, max_completion_tokens augmenté."""
    is_reasoning = model_key.startswith("o1")
    payload = {
        "model": model_key,
        "messages": [{"role": "user", "content": prompt}],
    }
    if is_reasoning:
        payload["max_completion_tokens"] = max_tokens * 5  # reasoning tokens overhead
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = 0.0

    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=600,
            )
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"].get("content", "") or ""
            usage = data.get("usage", {})

            # Cost calculation
            inp = usage.get("prompt_tokens", 0)
            out = usage.get("completion_tokens", 0)
            pricing = PRICING.get(model_key, {"input": 0, "output": 0})
            cost = (inp / 1e6) * pricing["input"] + (out / 1e6) * pricing["output"]
            budget_used["total"] += cost
            budget_used["by_model"][model_key] = budget_used["by_model"].get(model_key, 0.0) + cost

            return {"text": text, "usage": usage, "cost": cost, "error": None}
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"      [retry {attempt+1}/{max_retries}] {type(e).__name__}: {str(e)[:120]} — wait {wait}s")
                time.sleep(wait)
    return {"text": "", "usage": {}, "cost": 0, "error": str(last_err)}


def format_chunks(claims) -> str:
    parts = []
    for c in claims[:80]:
        text = (
            getattr(c, "quote", None)
            or getattr(c, "verbatim_quote", None)
            or getattr(c, "text", None)
            or ""
        )
        doc_id = getattr(c, "doc_id", None) or "unknown"
        if not text:
            continue
        parts.append(f"[doc={doc_id}] {text[:800]}")
    return "\n\n".join(parts)


def main():
    sample = json.load(open(SAMPLE))
    questions = sample["questions"]
    print(f"Loaded {len(questions)} questions")

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

    # Reprise
    if OUT.exists():
        results = json.load(open(OUT))
        print(f"[resume] Chargé {len(results.get('per_question', []))} questions")
        budget_used["total"] = results.get("budget_used", 0.0)
        budget_used["by_model"] = results.get("budget_by_model", {})
    else:
        results = {"per_question": [], "_tests": [t[0] for t in TESTS]}

    done_qids = {q["question_id"] for q in results["per_question"]}
    questions_todo = [q for q in questions if q["question_id"] not in done_qids]
    print(f"À traiter : {len(questions_todo)}/30 questions")
    print(f"Budget déjà utilisé : ${budget_used['total']:.2f} / ${BUDGET_HARD_CAP}")

    t0 = time.time()
    for i, q in enumerate(questions_todo):
        if budget_used["total"] >= BUDGET_HARD_CAP:
            print(f"\n!!! BUDGET DÉPASSÉ ({budget_used['total']:.2f}$) — abort après q{i} !!!")
            break

        qid = q["question_id"]
        question = q["question"]
        print(f"\n[{i+1}/{len(questions_todo)}] {qid} | {q['category']}")

        # Retrievals : top_k=30 et top_k=60
        try:
            claims_30 = collector.collect(question=question, top_k=30, mode="single").claims
            chunks_30 = format_chunks(claims_30)
        except Exception as e:
            print(f"  retrieval 30 error: {e}")
            chunks_30 = ""
        try:
            claims_60 = collector.collect(question=question, top_k=60, mode="single").claims
            chunks_60 = format_chunks(claims_60)
        except Exception as e:
            print(f"  retrieval 60 error: {e}")
            chunks_60 = ""

        chunks_by_field = {"chunks_30": chunks_30, "chunks_60": chunks_60}
        print(f"  retrieval 30 chars: {len(chunks_30)} | 60 chars: {len(chunks_60)}")

        per_q = {
            "question_id": qid,
            "category": q["category"],
            "question": question,
            "answers": {},  # {test_label: {"text": ..., "usage": ..., "cost": ..., "latency_ms": ...}}
        }

        # Parallèle : 5 tests par question
        def run_test(test_label, model_key, prompt_tpl, chunks_field):
            chunks = chunks_by_field.get(chunks_field, "")
            if not chunks:
                return (test_label, {"text": "", "error": "no_chunks", "cost": 0, "latency_ms": 0})
            prompt = prompt_tpl.format(question=question, chunks=chunks[:120000])
            t1 = time.time()
            out = call_openai(model_key, prompt, max_tokens=800)
            tg = int((time.time() - t1) * 1000)
            return (test_label, {**out, "latency_ms": tg, "model": model_key, "chunks_used": chunks_field})

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(run_test, *test) for test in TESTS]
            for fut in as_completed(futures):
                test_label, res = fut.result()
                if res.get("error"):
                    print(f"  {test_label} ERROR: {res['error']}")
                else:
                    print(f"  {test_label} ({res['latency_ms']}ms, ${res['cost']:.3f}): {res['text'][:60]}...")
                per_q["answers"][test_label] = res

        results["per_question"].append(per_q)
        results["budget_used"] = budget_used["total"]
        results["budget_by_model"] = budget_used["by_model"]

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"  [budget cumul: ${budget_used['total']:.2f}/${BUDGET_HARD_CAP}]")

    elapsed = time.time() - t0
    print(f"\n=== Génération terminée. {elapsed:.0f}s ===")
    print(f"Budget total utilisé : ${budget_used['total']:.2f}")
    print(f"Détail par modèle :")
    for m, c in sorted(budget_used["by_model"].items()):
        print(f"  {m:<15} : ${c:.2f}")
    print(f"\nFichier : {OUT}")


if __name__ == "__main__":
    main()
