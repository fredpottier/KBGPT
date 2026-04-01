#!/usr/bin/env python3
"""
Claude Judge — Evaluateur semantique utilisant Claude Haiku.

Script ISOLE sans import openai pour eviter les conflits httpx.

Usage:
    ANTHROPIC_API_KEY=sk-... python benchmark/evaluators/claude_judge.py \
        --results benchmark/results/run_v2_task1_human.json \
        --output benchmark/results/run_v2_task1_human_judged.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Any, Dict, List

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def call_claude(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL) -> Dict:
    """Appelle Claude via REST API directe (pas le SDK)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"result": {}, "tokens": 0, "error": "ANTHROPIC_API_KEY not set"}

    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": 0,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "{}")
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        # Parser le JSON de la reponse
        clean = text.strip()
        if clean.startswith("```json"):
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif clean.startswith("```"):
            clean = clean.split("```")[1].split("```")[0].strip()

        # Trouver le JSON dans la reponse
        import re
        json_match = re.search(r'\{[^{}]*\}', clean, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(clean)

        return {"result": result, "tokens": tokens, "error": None}

    except requests.exceptions.Timeout:
        return {"result": {}, "tokens": 0, "error": "Anthropic API timeout (120s)"}
    except requests.exceptions.HTTPError as e:
        return {"result": {}, "tokens": 0, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except json.JSONDecodeError as e:
        return {"result": {}, "tokens": 0, "error": f"JSON parse error: {str(e)[:100]}"}
    except Exception as e:
        return {"result": {}, "tokens": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════════════════════
# Jugements par tache
# ═══════════════════════════════════════════════════════════════════════

JUDGE_SYSTEM = """Tu es un evaluateur rigoureux de systemes de question-reponse documentaire.
Tu evalues si une reponse est correcte, sourcee, et complete par rapport a une question et un ground truth.
Reponds TOUJOURS en JSON valide avec les champs demandes. Sois strict mais juste."""


def judge_provenance(question, answer, ground_truth, source_map=""):
    expected_claim = ground_truth.get("expected_claim", "")
    expected_doc = ground_truth.get("doc_id", "")
    verbatim = ground_truth.get("verbatim_quote", "")

    source_map_section = ""
    if source_map:
        source_map_section = f"\nCorrespondance des sources:\n{source_map}\n"

    prompt = f"""Evalue cette reponse.

Question: {question}

Reponse du systeme:
{answer[:2000]}
{source_map_section}
Information attendue:
- Fait attendu: {expected_claim[:500]}
- Document source: {expected_doc}
- Citation: {verbatim[:300]}

Evalue en JSON:
{{"factual_correctness": 0.0-1.0, "citation_present": true/false, "correct_source_cited": true/false, "answer_relevant": true/false, "says_idk_when_info_exists": true/false, "answers_correctly": true/false, "reasoning": "explication courte"}}"""

    return call_claude(JUDGE_SYSTEM, prompt)


def judge_contradiction(question, answer, ground_truth, source_map=""):
    claim1 = ground_truth.get("claim1", {}).get("text", "")
    claim2 = ground_truth.get("claim2", {}).get("text", "")
    tension = ground_truth.get("tension_nature", "")

    prompt = f"""Evalue si cette reponse gere correctement une contradiction documentaire.

Question: {question}

Reponse:
{answer[:2000]}

Contradiction attendue:
- Claim 1: {claim1[:300]}
- Claim 2: {claim2[:300]}
- Nature: {tension}

Evalue en JSON:
{{"both_sides_mentioned": true/false, "tension_acknowledged": true/false, "factual_correctness": 0.0-1.0, "answer_relevant": true/false, "reasoning": "explication"}}"""

    return call_claude(JUDGE_SYSTEM, prompt)


def judge_audit(question, answer, ground_truth, source_map=""):
    scope = ground_truth.get("expected_scope", ground_truth.get("scope", ""))
    expected = ground_truth.get("expected_claim", ground_truth.get("key_facts", ""))

    prompt = f"""Evalue cette reponse d'audit documentaire.

Question: {question}

Reponse:
{answer[:3000]}

Attendu:
- Scope: {scope[:300]}
- Faits cles: {str(expected)[:500]}

Evalue en JSON:
{{"factual_correctness": 0.0-1.0, "completeness": 0.0-1.0, "answer_relevant": true/false, "answers_correctly": true/false, "reasoning": "explication"}}"""

    return call_claude(JUDGE_SYSTEM, prompt)


TASK_JUDGES = {
    "T1_provenance": judge_provenance,
    "T1": judge_provenance,
    "T2_contradictions": judge_contradiction,
    "T2": judge_contradiction,
    "T4_audit": judge_audit,
    "T4": judge_audit,
}


def aggregate_judgments(judgments, task):
    """Agrege les scores des jugements."""
    scores = {}
    valid = [j for j in judgments if j.get("judgment") and not j.get("error")]
    total = len(judgments)

    if not valid:
        return {
            "factual_correctness_avg": 0.0,
            "answers_correctly_rate": 0.0,
            "false_answer_rate": 0.0,
            "false_idk_rate": 0.0,
            "irrelevant_rate": 1.0,
            "total_error_rate": len([j for j in judgments if j.get("error")]) / max(total, 1),
            "total_evaluated": total,
        }

    factuals = [j["judgment"].get("factual_correctness", 0) for j in valid]
    scores["factual_correctness_avg"] = sum(factuals) / len(factuals) if factuals else 0

    # Answers correctly = factual >= 0.8
    correct = sum(1 for f in factuals if f >= 0.8)
    scores["answers_correctly_rate"] = correct / total

    # Relevant
    relevant = sum(1 for j in valid if j["judgment"].get("answer_relevant", False))
    scores["answer_relevant_rate"] = relevant / total

    # False IDK (dit "je ne sais pas" alors que l'info existe)
    false_idk = sum(1 for j in valid if j["judgment"].get("says_idk_when_info_exists", False))
    scores["false_idk_rate"] = false_idk / total

    # False answer (repond faux)
    false_answer = sum(1 for f in factuals if 0 < f < 0.5)
    scores["false_answer_rate"] = false_answer / total

    # Irrelevant
    irrelevant = sum(1 for j in valid if not j["judgment"].get("answer_relevant", False))
    scores["irrelevant_rate"] = irrelevant / total

    scores["total_error_rate"] = len([j for j in judgments if j.get("error")]) / max(total, 1)
    scores["total_evaluated"] = total

    # Metriques T2 (contradictions) — agreger depuis les judgments individuels
    both_sides_count = sum(1 for j in valid if j["judgment"].get("both_sides_mentioned", False))
    tension_count = sum(1 for j in valid if j["judgment"].get("tension_acknowledged", False))
    if both_sides_count > 0 or tension_count > 0:
        scores["both_sides_surfaced_rate"] = both_sides_count / total
        scores["tension_mentioned_rate"] = tension_count / total
        # silent_arbitration = repond sans mentionner la tension
        silent = sum(1 for j in valid
                     if j["judgment"].get("answer_relevant", False)
                     and not j["judgment"].get("tension_acknowledged", False))
        scores["silent_arbitration_rate"] = silent / total

    # Metriques T4 (audit) — mapper depuis les metriques existantes
    # topic_coverage et completeness sont approximees via factual + relevant
    if any(j["judgment"].get("completeness") is not None for j in valid):
        completeness = [
            float(j["judgment"]["completeness"])
            for j in valid
            if j["judgment"].get("completeness") is not None
            and str(j["judgment"]["completeness"]).replace(".", "", 1).isdigit()
        ]
        scores["completeness_avg"] = sum(completeness) / len(completeness) if completeness else 0
        scores["topic_coverage_rate"] = scores["answer_relevant_rate"]
        scores["traceability_rate"] = scores.get("citation_present_rate", scores["answer_relevant_rate"])

    return scores


def evaluate_results(results_path, model=DEFAULT_MODEL, output_path=None, workers=1):
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data["results"]
    metadata = data["metadata"]
    task = metadata["task"]
    system = metadata["system"]

    judge_fn = TASK_JUDGES.get(task)
    if not judge_fn:
        logger.error(f"Pas de juge pour la tache {task}")
        return

    logger.info(f"Evaluating {len(results)} results for {system}/{task} with {model}")

    judgments = []
    total_tokens = 0

    if workers > 1:
        # Parallele
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def judge_one(i, r):
            answer = r["response"].get("answer", "")
            question = r["question"]
            gt = r["ground_truth"]
            chunks = r["response"].get("results", r["response"].get("chunks", []))
            source_map = ""
            if chunks:
                source_map = "\n".join(
                    f"[Source {j+1}] = {c.get('source_file', c.get('doc_id', '?'))}"
                    for j, c in enumerate(chunks)
                )
            return i, r["question_id"], judge_fn(question, answer, gt, source_map=source_map)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(judge_one, i, r): i for i, r in enumerate(results)}
            for future in as_completed(futures):
                i, qid, judgment = future.result()
                total_tokens += judgment.get("tokens", 0)
                judgments.append({
                    "question_id": qid,
                    "system": system,
                    "judgment": judgment["result"],
                    "error": judgment.get("error"),
                })
                ok = "OK" if judgment["result"] else "ERR"
                logger.info(f"  [{len(judgments)}/{len(results)}] {qid} → {ok}")
    else:
        # Sequentiel
        for i, r in enumerate(results):
            answer = r["response"].get("answer", "")
            question = r["question"]
            gt = r["ground_truth"]
            chunks = r["response"].get("results", r["response"].get("chunks", []))
            source_map = ""
            if chunks:
                source_map = "\n".join(
                    f"[Source {j+1}] = {c.get('source_file', c.get('doc_id', '?'))}"
                    for j, c in enumerate(chunks)
                )

            logger.info(f"  [{i+1}/{len(results)}] Judging {r['question_id']}...")
            judgment = judge_fn(question, answer, gt, source_map=source_map)
            total_tokens += judgment.get("tokens", 0)
            judgments.append({
                "question_id": r["question_id"],
                "system": system,
                "judgment": judgment["result"],
                "error": judgment.get("error"),
            })
            time.sleep(0.1)

    scores = aggregate_judgments(judgments, task)

    output = {
        "metadata": {
            **metadata,
            "judge_model": model,
            "total_tokens": total_tokens,
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "scores": scores,
        "judgments": judgments,
    }

    out_path = output_path or results_path.replace(".json", f"_judged.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\n{'='*50}")
    logger.info(f"CLAUDE JUDGE SCORES — {system} / {task}")
    logger.info(f"{'='*50}")
    for k, v in sorted(scores.items()):
        logger.info(f"  {k:<40s} {v:.3f}" if isinstance(v, float) else f"  {k:<40s} {v}")

    return scores


def main():
    parser = argparse.ArgumentParser(description="Claude Judge (isolated)")
    parser.add_argument("--results", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=None)
    parser.add_argument("--workers", type=int, default=10, help="Parallel workers")
    args = parser.parse_args()

    evaluate_results(args.results, args.model, args.output, args.workers)


if __name__ == "__main__":
    main()
