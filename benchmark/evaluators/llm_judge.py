#!/usr/bin/env python3
"""
LLM-as-Judge — Evaluateur semantique utilisant GPT-4o-mini.

Remplace le matching par mots-cles par un jugement LLM sur :
- Factual correctness (la reponse est-elle factuellement correcte ?)
- Citation support (les citations supportent-elles les affirmations ?)
- Contradiction awareness (les tensions sont-elles signalees ?)
- Completeness (la reponse couvre-t-elle le sujet ?)

Usage:
    python benchmark/evaluators/llm_judge.py --results benchmark/results/osmosis_T1_fair.json
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-judge")


def call_judge(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    """Appelle le LLM juge et parse la reponse JSON."""
    from openai import OpenAI

    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or "{}"
        tokens = response.usage.total_tokens if response.usage else 0
        return {"result": json.loads(text), "tokens": tokens, "error": None}
    except Exception as e:
        return {"result": {}, "tokens": 0, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Jugements par tache
# ═══════════════════════════════════════════════════════════════════════

JUDGE_SYSTEM = """Tu es un evaluateur rigoureux de systemes de question-reponse documentaire.
Tu evalues si une reponse est correcte, sourcee, et complete par rapport a une question et un ground truth.
Reponds TOUJOURS en JSON valide avec les champs demandes. Sois strict mais juste."""


def judge_provenance(question: str, answer: str, ground_truth: dict) -> Dict:
    """Juge T1 : la reponse cite-t-elle correctement ses sources ?"""
    expected_claim = ground_truth.get("expected_claim", "")
    expected_doc = ground_truth.get("doc_id", "")
    verbatim = ground_truth.get("verbatim_quote", "")

    prompt = f"""Evalue cette reponse sur 4 criteres (score 0-1 chacun).

Question: {question}

Reponse du systeme:
{answer[:2000]}

Information attendue (ground truth):
- Fait attendu: {expected_claim[:500]}
- Document source: {expected_doc}
- Citation verbatim: {verbatim[:300]}

Evalue en JSON:
{{
  "factual_correctness": 0.0-1.0,  // La reponse contient-elle le fait attendu (meme paraphrase) ?
  "citation_present": true/false,   // La reponse cite-t-elle des sources [Source N] ?
  "correct_source_cited": true/false, // Le bon document est-il cite ?
  "answer_relevant": true/false,    // La reponse repond-elle a la question ?
  "says_idk_correctly": true/false, // Si pas d'info, le systeme dit-il "je ne sais pas" ?
  "reasoning": "explication courte"
}}"""

    return call_judge(JUDGE_SYSTEM, prompt)


def judge_contradiction(question: str, answer: str, ground_truth: dict) -> Dict:
    """Juge T2 : la reponse expose-t-elle les deux cotes d'une contradiction ?"""
    claim1 = ground_truth.get("claim1", {}).get("text", "")
    claim2 = ground_truth.get("claim2", {}).get("text", "")
    tension = ground_truth.get("tension_nature", "")

    prompt = f"""Evalue si cette reponse gere correctement une contradiction documentaire.

Question: {question}

Reponse du systeme:
{answer[:2000]}

Contradiction connue:
- Position A: {claim1[:300]}
- Position B: {claim2[:300]}
- Type de tension: {tension}

Evalue en JSON:
{{
  "surfaces_both_sides": true/false,      // Les deux positions sont-elles mentionnees ?
  "silent_arbitration": true/false,        // Le systeme choisit-il un cote sans le dire ?
  "mentions_tension": true/false,          // Le mot "contradiction/tension/divergence" est-il utilise ?
  "correct_tension_type": true/false,      // Le type de tension est-il correctement identifie ?
  "provides_sources_for_both": true/false, // Les deux positions sont-elles sourcees ?
  "reasoning": "explication courte"
}}"""

    return call_judge(JUDGE_SYSTEM, prompt)


def judge_temporal(question: str, answer: str, ground_truth: dict) -> Dict:
    """Juge T3 : la reponse distingue-t-elle les versions ?"""
    versions = ground_truth.get("versions", [])
    entity = ground_truth.get("entity", "")

    prompt = f"""Evalue si cette reponse gere correctement les versions/editions.

Question: {question}

Reponse du systeme:
{answer[:2000]}

Contexte temporel:
- Sujet: {entity}
- Versions connues: {', '.join(str(v) for v in versions)}

Evalue en JSON:
{{
  "distinguishes_versions": true/false,  // Les versions sont-elles distinguees ?
  "mixes_versions_silently": true/false, // Des infos de versions differentes sont-elles melangees sans le dire ?
  "attributes_to_correct_version": true/false, // Les infos sont-elles attribuees a la bonne version ?
  "mentions_evolution": true/false,      // L'evolution entre versions est-elle mentionnee ?
  "reasoning": "explication courte"
}}"""

    return call_judge(JUDGE_SYSTEM, prompt)


def judge_audit(question: str, answer: str, ground_truth: dict) -> Dict:
    """Juge T4 : la reponse est-elle complete et tracable ?"""
    entity = ground_truth.get("entity", "")
    expected_claims = ground_truth.get("expected_claim_count", 0)
    expected_contradictions = ground_truth.get("expected_contradiction_count", 0)

    prompt = f"""Evalue la completude et la tracabilite de cet export.

Question: {question}

Reponse du systeme:
{answer[:2000]}

Attendu:
- Sujet: {entity}
- Nombre de claims attendus: {expected_claims}
- Contradictions attendues: {expected_contradictions}

Evalue en JSON:
{{
  "covers_main_topic": true/false,        // Le sujet principal est-il couvert ?
  "mentions_sources": true/false,          // Les documents sources sont-ils mentionnes ?
  "mentions_contradictions": true/false,   // Les contradictions sont-elles signalees (si attendues) ?
  "appears_comprehensive": true/false,     // La reponse semble-t-elle complete ?
  "traceable_to_documents": true/false,    // Chaque affirmation est-elle tracable a un document ?
  "completeness_score": 0.0-1.0,           // Score global de completude
  "reasoning": "explication courte"
}}"""

    return call_judge(JUDGE_SYSTEM, prompt)


# ═══════════════════════════════════════════════════════════════════════
# Runner principal
# ═══════════════════════════════════════════════════════════════════════


TASK_JUDGES = {
    "T1_provenance": judge_provenance,
    "T1": judge_provenance,
    "T2_contradictions": judge_contradiction,
    "T2": judge_contradiction,
    "T3_temporal": judge_temporal,
    "T3": judge_temporal,
    "T4_audit": judge_audit,
    "T4": judge_audit,
}


def evaluate_results(results_path: str, model: str = "gpt-4o-mini", output_path: str = None):
    """Evalue tous les resultats d'un fichier avec le LLM juge."""

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

    for i, r in enumerate(results):
        answer = r["response"].get("answer", "")
        question = r["question"]
        gt = r["ground_truth"]

        logger.info(f"  [{i+1}/{len(results)}] Judging {r['question_id']}...")

        judgment = judge_fn(question, answer, gt)
        total_tokens += judgment.get("tokens", 0)

        judgments.append({
            "question_id": r["question_id"],
            "system": system,
            "judgment": judgment["result"],
            "error": judgment.get("error"),
        })

        time.sleep(0.3)  # Rate limiting

    # Aggreger les scores
    scores = aggregate_judgments(judgments, task)

    # Sauvegarder
    if not output_path:
        out_dir = Path("benchmark/results")
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = out_dir / f"judge_{system}_{task}_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "system": system,
                "task": task,
                "judge_model": model,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "total_tokens": total_tokens,
                "source_results": results_path,
            },
            "scores": scores,
            "judgments": judgments,
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"Evaluation complete. Tokens used: {total_tokens}")
    logger.info(f"Results saved to {output_path}")

    # Afficher les scores
    print(f"\n{'='*50}")
    print(f"LLM JUDGE SCORES — {system} / {task}")
    print(f"{'='*50}")
    for k, v in sorted(scores.items()):
        if isinstance(v, float):
            print(f"  {k:<40} {v:.3f}")
        else:
            print(f"  {k:<40} {v}")

    return scores


def aggregate_judgments(judgments: List[Dict], task: str) -> Dict[str, Any]:
    """Agregation des jugements en scores."""
    total = len(judgments)
    if total == 0:
        return {}

    scores = {}

    if task in ("T1_provenance", "T1"):
        scores["factual_correctness_avg"] = _avg_field(judgments, "factual_correctness")
        scores["citation_present_rate"] = _bool_rate(judgments, "citation_present")
        scores["correct_source_rate"] = _bool_rate(judgments, "correct_source_cited")
        scores["answer_relevant_rate"] = _bool_rate(judgments, "answer_relevant")
        scores["idk_correct_rate"] = _bool_rate(judgments, "says_idk_correctly")

    elif task in ("T2_contradictions", "T2"):
        scores["both_sides_surfaced_rate"] = _bool_rate(judgments, "surfaces_both_sides")
        scores["silent_arbitration_rate"] = _bool_rate(judgments, "silent_arbitration")
        scores["tension_mentioned_rate"] = _bool_rate(judgments, "mentions_tension")
        scores["correct_tension_type_rate"] = _bool_rate(judgments, "correct_tension_type")
        scores["both_sourced_rate"] = _bool_rate(judgments, "provides_sources_for_both")

    elif task in ("T3_temporal", "T3"):
        scores["version_distinguished_rate"] = _bool_rate(judgments, "distinguishes_versions")
        scores["version_mixing_rate"] = _bool_rate(judgments, "mixes_versions_silently")
        scores["correct_attribution_rate"] = _bool_rate(judgments, "attributes_to_correct_version")
        scores["evolution_mentioned_rate"] = _bool_rate(judgments, "mentions_evolution")

    elif task in ("T4_audit", "T4"):
        scores["topic_coverage_rate"] = _bool_rate(judgments, "covers_main_topic")
        scores["sources_mentioned_rate"] = _bool_rate(judgments, "mentions_sources")
        scores["contradictions_flagged_rate"] = _bool_rate(judgments, "mentions_contradictions")
        scores["comprehensiveness_rate"] = _bool_rate(judgments, "appears_comprehensive")
        scores["traceability_rate"] = _bool_rate(judgments, "traceable_to_documents")
        scores["completeness_avg"] = _avg_field(judgments, "completeness_score")

    scores["total_evaluated"] = total
    return scores


def _avg_field(judgments: List[Dict], field: str) -> float:
    values = []
    for j in judgments:
        v = j.get("judgment", {}).get(field)
        if isinstance(v, (int, float)):
            values.append(v)
    return sum(values) / max(len(values), 1)


def _bool_rate(judgments: List[Dict], field: str) -> float:
    total = 0
    true_count = 0
    for j in judgments:
        v = j.get("judgment", {}).get(field)
        if isinstance(v, bool):
            total += 1
            if v:
                true_count += 1
    return true_count / max(total, 1)


def main():
    parser = argparse.ArgumentParser(description="LLM-as-Judge evaluator")
    parser.add_argument("--results", required=True, help="Results JSON to evaluate")
    parser.add_argument("--model", default="gpt-4o-mini", help="Judge model")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    evaluate_results(args.results, args.model, args.output)


if __name__ == "__main__":
    main()
