#!/usr/bin/env python3
"""
CH-41.0 livrable E — Mesure du baseline factual_correctness (gate D-FF13).

But : avant d'activer le D-FF13 chunk-extractive fallback (tranche 5 V4 Facts-First),
mesurer la performance du pipeline V3 actuel sur les questions factual du gold-set
v4. Le gate ship pour D-FF13 est :

  factual_correctness(facts-first+D-FF13) ≥ factual_correctness(V3 baseline) sur ≥30q

Le V3 actuel est traité comme « RAG baseline » par convention dans cette mesure
(avant migration Facts-First). Ce baseline V3 est le seuil à ne pas régresser.

Process :
1. Filtre les 25 questions factual du gold-set v4
2. Pour chaque, appelle /api/runtime_v3/answer (pipeline V3 actuel)
3. Persiste les {question, answer, reference, contexts} dans un JSON RAGAS-compatible
4. Optionnel : lance ragas_diagnostic en mode reference-only pour calculer
   factual_correctness (FactualCorrectness ne nécessite que answer + reference,
   pas user_input — cf bug fix CH-40.1)

Usage :
  python scripts/measure_rag_baseline_factual.py --collect       # appels V3 only
  python scripts/measure_rag_baseline_factual.py --score         # calcule score
  python scripts/measure_rag_baseline_factual.py                 # collect + score
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "benchmark" / "calibration" / "rag_baseline_factual.json"

V3_API_URL = os.getenv("OSMOSIS_API_URL", "http://localhost:8000") + "/api/runtime_v3/answer"


def load_factual_questions() -> list[dict]:
    gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    return [q for q in gold if q.get("primary_type") == "factual"]


def call_v3(question: str, language: str = "fr") -> dict | None:
    payload = {"question": question, "language": language, "tenant_id": "default"}
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(V3_API_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("V3 call failed for question : %s", exc)
        return None


def collect_responses(questions: list[dict], max_workers: int = 4) -> list[dict]:
    samples = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(call_v3, q["question"], q.get("language", "fr")): q for q in questions}
        for fut in as_completed(futures):
            q = futures[fut]
            v3_resp = fut.result()
            if not v3_resp:
                logger.warning("Skipping %s : no V3 response", q["id"])
                continue
            answer = v3_resp.get("answer", "")
            contexts = v3_resp.get("contexts", []) or v3_resp.get("retrieved_chunks", [])
            samples.append({
                "id": q["id"],
                "question": q["question"],
                "language": q.get("language", "fr"),
                "answer": answer,
                "reference": q.get("ground_truth", {}).get("ground_truth_answer", ""),
                "contexts": contexts if isinstance(contexts, list) else [],
                "exact_identifiers": q.get("ground_truth", {}).get("exact_identifiers", []),
                "supporting_doc_ids": q.get("ground_truth", {}).get("supporting_doc_ids", []),
            })
    logger.info("Collected %d/%d responses in %.1fs", len(samples), len(questions), time.time() - t0)
    return samples


def score_with_ragas(samples: list[dict]) -> dict:
    """
    Calcule RAGAS FactualCorrectness sur chaque sample.
    Note : FactualCorrectness ne prend que answer + reference (pas user_input,
    pas contexts) — corrigé dans CH-40.1.
    """
    try:
        from ragas import SingleTurnSample
        from ragas.metrics import FactualCorrectness
        from ragas.llms import LangchainLLMWrapper
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.error("ragas / langchain-openai not installed locally — run from container app")
        return {"error": "ragas_not_available"}

    deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")
    if not deepinfra_key:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("DEEPINFRA_API_KEY="):
                    deepinfra_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not deepinfra_key:
        return {"error": "missing_deepinfra_key"}

    llm = ChatOpenAI(
        model="meta-llama/Llama-3.3-70B-Instruct",
        api_key=deepinfra_key,
        base_url="https://api.deepinfra.com/v1/openai",
        temperature=0.1,
    )
    metric = FactualCorrectness(llm=LangchainLLMWrapper(llm))

    import asyncio
    scores = []
    for s in samples:
        if not s.get("answer") or not s.get("reference"):
            continue
        try:
            sample = SingleTurnSample(response=s["answer"], reference=s["reference"])
            score = asyncio.run(metric.single_turn_ascore(sample))
            scores.append({"id": s["id"], "factual_correctness": float(score)})
        except Exception as exc:
            logger.warning("RAGAS score failed for %s : %s", s["id"], exc)
            scores.append({"id": s["id"], "factual_correctness": None, "error": str(exc)})

    valid = [x["factual_correctness"] for x in scores if x.get("factual_correctness") is not None]
    if not valid:
        return {"error": "no_valid_scores", "details": scores}
    return {
        "n_total": len(scores),
        "n_valid": len(valid),
        "mean": sum(valid) / len(valid),
        "min": min(valid),
        "max": max(valid),
        "per_sample": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="Collect V3 responses only")
    parser.add_argument("--score", action="store_true", help="Compute RAGAS factual_correctness on existing samples")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    do_collect = args.collect or (not args.collect and not args.score)
    do_score = args.score or (not args.collect and not args.score)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if do_collect:
        qs = load_factual_questions()
        if args.limit:
            qs = qs[: args.limit]
        logger.info("Filtered %d factual questions from gold-set", len(qs))
        samples = collect_responses(qs)
        OUTPUT_PATH.write_text(json.dumps({"samples": samples, "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Persisted %d samples to %s", len(samples), OUTPUT_PATH)

    if do_score:
        if not OUTPUT_PATH.exists():
            logger.error("No samples file to score : %s", OUTPUT_PATH)
            return 1
        data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        samples = data.get("samples", [])
        logger.info("Scoring %d samples with RAGAS FactualCorrectness", len(samples))
        result = score_with_ragas(samples)
        data["factual_correctness_baseline"] = result
        OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Result : %s", json.dumps({k: v for k, v in result.items() if k != "per_sample"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
