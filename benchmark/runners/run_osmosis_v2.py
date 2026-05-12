#!/usr/bin/env python3
"""
Runner OSMOSIS V2 — Interroge l'API runtime_v2/answer pour chaque question du benchmark.

Différences vs run_osmosis.py (V1.1) :
- Endpoint : POST /api/runtime_v2/answer (au lieu de /api/search + synthèse séparée)
- La synthèse est déjà faite par le pipeline V2 (synthesized_answer dans la réponse)
- Capture les nouveaux métadonnées V2 : decision, anchor_type, n_authoritative_docs,
  n_conflicts_unresolved, trust_score

Usage :
    python benchmark/runners/run_osmosis_v2.py \\
      --config benchmark/config.yaml \\
      --questions benchmark/questions/task1_provenance_kg.json \\
      --output data/forensics/runs/osmosis_v2_<ts>.jsonl
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
logger = logging.getLogger("benchmark-osmosis-v2")


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_questions(questions_path: str) -> List[Dict[str, Any]]:
    with open(questions_path, "r", encoding="utf-8") as f:
        return json.load(f)


def query_osmosis_v2(
    api_url: str,
    question: str,
    audit_mode: bool = False,
    top_k: int = 8,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Appelle POST /api/runtime_v2/answer."""
    try:
        resp = requests.post(
            f"{api_url}/api/runtime_v2/answer",
            json={
                "question": question,
                "audit_mode": audit_mode,
                "top_k_claims": top_k,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        logger.error("Pipeline V2 call failed for question '%.50s': %s", question, exc)
        return {"error": str(exc)}


def process_question(
    api_url: str, q: dict, audit_default: bool = False
) -> Dict[str, Any]:
    """Traite une question : V2 → réponse + métriques."""
    question_text = q.get("question") or q.get("text") or q.get("query")
    if not question_text:
        return {"error": "Empty question", "question_id": q.get("id")}

    start = time.time()
    response = query_osmosis_v2(api_url, question_text, audit_mode=audit_default)
    latency_ms = (time.time() - start) * 1000

    if "error" in response:
        return {
            "question_id": q.get("id"),
            "question": question_text,
            "error": response["error"],
            "latency_ms": latency_ms,
        }

    return {
        "question_id": q.get("id"),
        "question": question_text,
        "answer": response.get("synthesized_answer") or "",
        "decision": response.get("decision"),
        "anchor_type": (response.get("anchor") or {}).get("anchor_type"),
        "anchor_scope": (response.get("anchor") or {}).get("scope") or {},
        "n_authoritative_docs": len(response.get("authoritative_doc_ids") or []),
        "authoritative_doc_ids": response.get("authoritative_doc_ids") or [],
        "n_claims": len(response.get("claims") or []),
        "n_conflicts_unresolved": sum(
            1 for c in (response.get("conflicts") or [])
            if not c.get("is_resolved_by_lifecycle")
        ),
        "n_evolution_points": len(response.get("evolution_points") or []),
        "trust_score": response.get("trust_score"),
        "trust_breakdown": response.get("trust_breakdown") or {},
        "escalation_message": response.get("escalation_message"),
        "ground_truth_doc_id": q.get("ground_truth_doc_id"),
        "ground_truth_answer": q.get("ground_truth_answer"),
        "category": q.get("category"),
        "task": q.get("task"),
        "latency_ms": latency_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-url", default=os.getenv("OSMOSIS_API_URL", "http://localhost:8000"))
    parser.add_argument("--audit", action="store_true", help="Activer audit_mode pour toutes les questions")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    config = load_config(args.config)
    questions = load_questions(args.questions)
    logger.info("Running %d questions on OSMOSIS V2 (%s)", len(questions), args.api_url)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_question, args.api_url, q, args.audit): q
                for q in questions
            }
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                if i % 10 == 0:
                    logger.info("Processed %d/%d", i, len(questions))

    logger.info("DONE — %d questions, output : %s", len(questions), out_path)


if __name__ == "__main__":
    main()
