"""S0.4 — Upper-bound LLM test : 30q SAP PCE → DeepSeek-V3.1 direct avec full context oracle.

Établit le ceiling de qualité du LLM sans dépendre du retrieval V5. Si le ceiling est < 0.85,
la cible V5.1 (0.80 holdout) est irréaliste — il faut accepter limite architecturale ou
changer de LLM.

Approche :
1. Charger gold_set_sap_v1.json (30q)
2. Pour chaque question, charger les structures DSG des supporting_doc_ids
3. Construire prompt = full sections concatenées + question
4. Appel DeepSeek-V3.1 via Together AI (réutilise call_llm de reasoning_agent)
5. Sauvegarder réponses (schema compatible rejudge_only.py)
6. Run judge Llama-3.3-70B via rejudge_only.py

Gate : ceiling ≥ 0.85.

Run :
    docker exec knowbase-app bash -c "cd /app && python scripts/s04_upper_bound_test.py"
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")
sys.path.insert(0, "/app")

from knowbase.runtime_v5.reasoning_agent import call_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GOLDSET = Path("/app/benchmark/questions/gold_set_sap_v2.json")
STRUCTURES_DIR = Path("/app/data/poc_a/structures")
OUT = Path("/app/benchmark/results/gold_set_sap_v2_upperbound_baseline.json")

MAX_CONTEXT_CHARS = 80_000  # ~20k tokens
MODEL = "deepseek-ai/DeepSeek-V3.1"


def load_doc_structure(doc_id: str) -> dict | None:
    """Charge une structure DSG par doc_id (suffixe match)."""
    # Try last 8 chars suffix match first (most specific)
    candidates = list(STRUCTURES_DIR.glob(f"*{doc_id[-8:]}*.json"))
    if not candidates:
        # Fallback : full doc_id substring
        candidates = list(STRUCTURES_DIR.glob(f"*{doc_id}*.json"))
    if not candidates:
        return None
    with open(candidates[0], encoding="utf-8") as f:
        return json.load(f)


def build_oracle_context(supporting_doc_ids: list[str], max_chars: int = MAX_CONTEXT_CHARS) -> tuple[str, list[str]]:
    """Construit un contexte oracle = concat sections des supporting docs.

    Retourne (context, docs_found).
    Si total > max_chars, tronque équitablement par doc.
    """
    docs_sections = []
    docs_found = []
    for doc_id in supporting_doc_ids:
        struct = load_doc_structure(doc_id)
        if struct is None:
            logger.warning(f"  Structure not found for doc_id={doc_id}")
            continue
        docs_found.append(struct.get("doc_name", doc_id))
        sections = struct.get("sections", [])
        doc_text = f"\n\n=== DOCUMENT : {struct.get('doc_name', doc_id)} ===\n"
        for sec in sections:
            doc_text += f"\n[Section {sec.get('numbering', '?')} — {sec.get('title', '')}]\n"
            doc_text += sec.get("text", "")[:5000] + "\n"
        docs_sections.append(doc_text)

    if not docs_sections:
        return "", []

    per_doc_budget = max_chars // len(docs_sections)
    truncated = [d[:per_doc_budget] for d in docs_sections]
    full = "\n".join(truncated)
    if len(full) > max_chars:
        full = full[:max_chars] + "\n\n[... CONTEXTE TRONQUE ...]"
    return full, docs_found


def query_llm_oracle(question: str, oracle_context: str) -> dict:
    """Appel DeepSeek avec contexte oracle complet (no tools)."""
    system_prompt = (
        "You are a SAP S/4HANA Cloud, Private Edition expert. "
        "Answer the user question based ONLY on the provided context sections. "
        "If the context contains the answer, provide a complete, structured response. "
        "Cite section numbering and document names. "
        "If the context does NOT contain the answer, say so explicitly. "
        "Reply in French."
    )
    user_msg = (
        f"=== CONTEXTE ORACLE (sections complètes des documents supporting) ===\n"
        f"{oracle_context}\n\n=== QUESTION ===\n{question}"
    )

    t0 = time.time()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    response = call_llm(messages=messages, tools=[], model=MODEL, max_tokens=2000)
    latency_ms = int((time.time() - t0) * 1000)

    if "error" in response:
        return {
            "answer": "",
            "tokens_total": 0,
            "latency_ms": latency_ms,
            "model": MODEL,
            "provider": "unknown",
            "error": response["error"],
        }

    try:
        choice = response["choices"][0]
        answer = choice["message"].get("content", "") or ""
        usage = response.get("usage", {})
        return {
            "answer": answer,
            "tokens_total": usage.get("total_tokens", 0),
            "latency_ms": latency_ms,
            "model": MODEL,
            "provider": response.get("_provider", "unknown"),
            "error": None,
        }
    except (KeyError, IndexError) as e:
        return {
            "answer": "",
            "tokens_total": 0,
            "latency_ms": latency_ms,
            "model": MODEL,
            "provider": response.get("_provider", "unknown"),
            "error": f"parse error: {e}",
        }


def main():
    items = json.loads(GOLDSET.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(items)} questions from gold-set")

    per_sample = []
    for i, item in enumerate(items, 1):
        qid = item["id"]
        question = item["question"]
        gt = item.get("ground_truth", {})
        ref = gt.get("answer", "")
        expected_docs = gt.get("supporting_doc_ids", [])

        logger.info(f"[{i}/{len(items)}] {qid} — {item.get('primary_type')}")
        oracle_context, docs_found = build_oracle_context(expected_docs)

        if not oracle_context:
            logger.warning(f"  No oracle context built — skipping")
            per_sample.append({
                "id": qid,
                "question": question,
                "primary_type": item.get("primary_type"),
                "reference_answer": ref,
                "osmosis_answer": "(ORACLE_CONTEXT_EMPTY — no structures found for supporting_doc_ids)",
                "latency_ms": 0,
                "judge": {"score": -1.0, "error": "not_judged_yet"},
                "structured_metrics": {
                    "exact_match_identifiers": {"score": None, "n_matched": 0, "n_expected": 0},
                    "citation_presence": {"score": None, "n_cited": 0, "n_expected": 0},
                    "structured_avg": None,
                },
                "disagreement": None,
                "osmosis_meta": {"system": "DeepSeek-V3.1 ORACLE", "error": "oracle_empty"},
            })
            continue

        logger.info(f"  {len(docs_found)} docs found, oracle ctx {len(oracle_context):,} chars")
        result = query_llm_oracle(question, oracle_context)
        logger.info(f"  -> {result['latency_ms']}ms, {result['tokens_total']} tk, {len(result['answer'])} ch ans (provider={result['provider']})")

        per_sample.append({
            "id": qid,
            "question": question,
            "primary_type": item.get("primary_type"),
            "reference_answer": ref,
            "osmosis_answer": result["answer"],
            "latency_ms": result["latency_ms"],
            "judge": {"score": -1.0, "error": "not_judged_yet"},
            "structured_metrics": {
                "exact_match_identifiers": {"score": None, "n_matched": 0, "n_expected": 0},
                "citation_presence": {"score": None, "n_cited": 0, "n_expected": 0},
                "structured_avg": None,
            },
            "disagreement": None,
            "osmosis_meta": {
                "system": "S0.4 Upper-bound DeepSeek-V3.1 + ORACLE full context",
                "tokens_total": result["tokens_total"],
                "model": result["model"],
                "provider": result["provider"],
                "oracle_context_chars": len(oracle_context),
                "docs_found": len(docs_found),
                "docs_expected": len(expected_docs),
                "error": result.get("error"),
            },
        })

    report = {
        "metadata": {
            "gold_set_path": str(GOLDSET),
            "system_under_test": "S0.4 Upper-bound LLM test (DeepSeek-V3.1 + ORACLE full context, no retrieval)",
            "model": MODEL,
            "max_context_chars": MAX_CONTEXT_CHARS,
            "ran_at": datetime.utcnow().isoformat(),
            "purpose": "Establish LLM ceiling without retrieval dependency. Gate >= 0.85.",
        },
        "scores": {"global": {}, "by_category": {}},
        "per_sample": per_sample,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    n_skipped = sum(1 for s in per_sample if s['osmosis_answer'].startswith('(ORACLE'))
    n_errored = sum(1 for s in per_sample if s.get('osmosis_meta', {}).get('error'))
    logger.info(f"\nWritten: {OUT}")
    logger.info(f"Total: {len(per_sample)} | Skipped (oracle empty): {n_skipped} | Errored: {n_errored}")
    logger.info("NEXT: run rejudge_only.py to score")


if __name__ == "__main__":
    main()
