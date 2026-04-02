#!/usr/bin/env python3
"""Reevalue un rapport T2/T5 existant avec un LLM-juge (GPT-4o-mini).

Les reponses OSMOSIS ne sont PAS relancees — seule l'evaluation change.
Permet de comparer keyword matching vs LLM-juge sur les memes donnees.
"""

import json
import os
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    model = "gpt-4o-mini"

    d = Path("data/benchmark/results")
    t2_files = sorted(d.glob("t2t5_run_*.json"), key=lambda f: f.stat().st_mtime)
    if not t2_files:
        logger.error("No T2/T5 reports found")
        return

    latest = t2_files[-1]
    data = json.loads(latest.read_text())
    logger.info(f"Reevaluating {latest.name} with LLM judge ({model})")

    per_sample = data.get("per_sample", [])

    T2_PROMPT = (
        'You are a strict benchmark evaluator for a document contradiction detection system.\n\n'
        'Question: "{question}"\n'
        'Ground truth claim 1: "{claim1}"\n'
        'Ground truth claim 2: "{claim2}"\n\n'
        'The system should detect the tension between these two claims and present BOTH sides.\n\n'
        'Actual answer (first 400 chars):\n"{answer}"\n\n'
        'Evaluate three aspects (each 0 or 1):\n'
        '1. both_sides_surfaced: Does the answer present BOTH positions/claims?\n'
        '2. tension_mentioned: Does the answer mention a tension, difference, or contradiction?\n'
        '3. both_sources_cited: Does the answer cite or reference both source documents?\n\n'
        'Reply with ONLY three numbers separated by commas: both_sides,tension,sources\n'
        'Example: 1,1,0'
    )

    T5_PROMPT = (
        'You are a strict benchmark evaluator for a cross-document analysis system.\n\n'
        'Question: "{question}"\nCategory: {category}\n\n'
        'Actual answer (first 400 chars):\n"{answer}"\n\n'
        'Evaluate (0.0 to 1.0):\n'
        '1. chain_coverage: How well does the answer cover the chain of facts across documents?\n'
        '2. multi_doc_cited: Does the answer reference multiple documents?\n\n'
        'Reply with ONLY two numbers separated by commas: chain_coverage,multi_doc_cited\n'
        'Example: 0.7,1.0'
    )

    new_per_sample = []
    t2_all = {"both_sides_surfaced": [], "tension_mentioned": [], "both_sources_cited": []}
    t5_chain = []
    t5_multi = []
    t5_proactive = []

    for i, s in enumerate(per_sample):
        ev = s.get("evaluation", {})
        task_type = ev.get("task_type", "")
        question = s.get("question", "")
        answer = s.get("answer", s.get("response", ""))
        if not answer:
            answer = ""
        gt = s.get("ground_truth", {})

        try:
            if task_type == "T2":
                claim1 = gt.get("claim1", {}).get("text", "")[:150]
                claim2 = gt.get("claim2", {}).get("text", "")[:150]
                resp = client.chat.completions.create(
                    model=model, max_tokens=10, temperature=0.0,
                    messages=[{"role": "user", "content": T2_PROMPT.format(
                        question=question[:200], claim1=claim1, claim2=claim2, answer=answer[:400]
                    )}],
                )
                raw = resp.choices[0].message.content.strip()
                parts = [float(x.strip()) for x in raw.split(",")]
                if len(parts) >= 3:
                    new_eval = {
                        "task_type": "T2",
                        "both_sides_surfaced": parts[0],
                        "tension_mentioned": parts[1],
                        "both_sources_cited": parts[2],
                        "judge_model": model,
                    }
                    t2_all["both_sides_surfaced"].append(parts[0])
                    t2_all["tension_mentioned"].append(parts[1])
                    t2_all["both_sources_cited"].append(parts[2])
                    s_copy = dict(s)
                    s_copy["evaluation"] = new_eval
                    new_per_sample.append(s_copy)
                else:
                    new_per_sample.append(s)

            elif task_type == "T5":
                category = ev.get("category", "")
                resp = client.chat.completions.create(
                    model=model, max_tokens=10, temperature=0.0,
                    messages=[{"role": "user", "content": T5_PROMPT.format(
                        question=question[:200], category=category, answer=answer[:400]
                    )}],
                )
                raw = resp.choices[0].message.content.strip()
                parts = [float(x.strip()) for x in raw.split(",")]
                if len(parts) >= 2:
                    tension_kw = ["contradiction", "diverge", "tension", "different", "contrast",
                                  "however", "cependant", "toutefois", "neanmoins", "attention"]
                    proactive = 1.0 if (category == "proactive_contradiction" and
                                        any(kw in answer.lower() for kw in tension_kw)) else 0.0

                    new_eval = {
                        "task_type": "T5",
                        "category": category,
                        "chain_coverage": parts[0],
                        "multi_doc_cited": parts[1],
                        "proactive_detection": proactive,
                        "judge_model": model,
                    }
                    if category != "proactive_contradiction":
                        t5_chain.append(parts[0])
                    t5_multi.append(parts[1])
                    if category == "proactive_contradiction":
                        t5_proactive.append(proactive)

                    s_copy = dict(s)
                    s_copy["evaluation"] = new_eval
                    new_per_sample.append(s_copy)
                else:
                    new_per_sample.append(s)
            else:
                new_per_sample.append(s)

        except Exception as e:
            logger.debug(f"Skip {i}: {e}")
            new_per_sample.append(s)

        if (i + 1) % 25 == 0:
            logger.info(f"  {i+1}/{len(per_sample)} reevaluated")

    # Aggregate
    new_scores = {}
    if t2_all["both_sides_surfaced"]:
        for k in ["both_sides_surfaced", "tension_mentioned", "both_sources_cited"]:
            new_scores[k] = round(sum(t2_all[k]) / len(t2_all[k]), 4)
        new_scores["t2_count"] = len(t2_all["both_sides_surfaced"])

    if t5_chain:
        new_scores["chain_coverage"] = round(sum(t5_chain) / len(t5_chain), 4)
    if t5_multi:
        new_scores["multi_doc_cited"] = round(sum(t5_multi) / len(t5_multi), 4)
    if t5_proactive:
        new_scores["proactive_detection"] = round(sum(t5_proactive) / len(t5_proactive), 4)
        new_scores["proactive_count"] = len(t5_proactive)
    new_scores["t5_count"] = len(t5_multi) if t5_multi else 0
    new_scores["total_evaluated"] = new_scores.get("t2_count", 0) + new_scores.get("t5_count", 0)

    # Save
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": data.get("profile", ""),
        "profile_label": data.get("profile_label", ""),
        "tag": "REEVAL_LLM_JUDGE",
        "description": f"Reevaluation de {latest.name} avec LLM-juge {model}",
        "synthesis_model": data.get("synthesis_model", ""),
        "judge_model": model,
        "judge_mode": "llm",
        "duration_s": data.get("duration_s", 0),
        "scores": new_scores,
        "scores_keyword": data.get("scores", {}),
        "per_sample": new_per_sample,
        "errors": 0,
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = d / f"t2t5_run_{ts}_REEVAL_LLM_JUDGE.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info(f"Report saved: {report_path.name}")
    logger.info("")
    old = data.get("scores", {})
    logger.info("=== KEYWORD (original) vs LLM-JUGE ===")
    for k in ["both_sides_surfaced", "tension_mentioned", "both_sources_cited", "chain_coverage", "multi_doc_cited", "proactive_detection"]:
        o = old.get(k, "?")
        n = new_scores.get(k, "?")
        delta = ""
        if isinstance(o, (int, float)) and isinstance(n, (int, float)):
            d_val = round((n - o) * 100, 1)
            delta = f"  ({'+' if d_val > 0 else ''}{d_val}pp)"
        logger.info(f"  {k:25s}: {o} -> {n}{delta}")


if __name__ == "__main__":
    main()
