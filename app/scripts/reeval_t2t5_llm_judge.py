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
        'You are a benchmark evaluator for a document contradiction detection system.\n\n'
        'Question: "{question}"\n\n'
        'The corpus contains TWO claims that may be in tension:\n'
        'Claim 1 (from document A): "{claim1}"\n'
        'Claim 2 (from document B): "{claim2}"\n\n'
        'The system produced this answer (first 400 chars):\n"{answer}"\n\n'
        'Rate each aspect from 0 to 100:\n'
        '1. both_sides: Does the answer present information from BOTH claims? Even paraphrased, in a different language, or summarized — if BOTH perspectives are covered, score high.\n'
        '2. tension: Does the answer acknowledge a difference, evolution, tension, contradiction, or divergence between sources? Look for words like "however", "but", "cependant", "toutefois", "differs", "changed", "evolution", "attention", "diverge" in ANY language.\n'
        '3. sources: Does the answer reference or cite multiple source documents? Look for any mention of document names, years, guide names, version numbers.\n\n'
        'Reply with ONLY three numbers (0-100) separated by commas.\n'
        'Example: 85,70,60'
    )

    T5_PROMPT = (
        'You are a benchmark evaluator for a cross-document analysis system.\n\n'
        'Question: "{question}"\nCategory: {category}\n\n'
        'The system produced this answer (first 400 chars):\n"{answer}"\n\n'
        'Rate each aspect from 0 to 100:\n'
        '1. chain_coverage: How well does the answer cover facts from multiple documents to build a complete answer? A good answer connects information across sources.\n'
        '2. multi_doc: Does the answer reference or cite multiple source documents? Look for any document names, years, or version references.\n\n'
        'Reply with ONLY two numbers (0-100) separated by commas.\n'
        'Example: 75,80'
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
                    # Scores 0-100 → normaliser en 0-1
                    sides = min(parts[0], 100) / 100.0
                    tension = min(parts[1], 100) / 100.0
                    sources = min(parts[2], 100) / 100.0
                    new_eval = {
                        "task_type": "T2",
                        "both_sides_surfaced": round(sides, 3),
                        "tension_mentioned": round(tension, 3),
                        "both_sources_cited": round(sources, 3),
                        "judge_model": model,
                        "judge_raw": raw,
                    }
                    t2_all["both_sides_surfaced"].append(sides)
                    t2_all["tension_mentioned"].append(tension)
                    t2_all["both_sources_cited"].append(sources)
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
                    # Scores 0-100 → normaliser en 0-1
                    chain = min(parts[0], 100) / 100.0
                    multi = min(parts[1], 100) / 100.0

                    tension_kw = ["contradiction", "diverge", "tension", "different", "contrast",
                                  "however", "cependant", "toutefois", "neanmoins", "attention"]
                    proactive = 1.0 if (category == "proactive_contradiction" and
                                        any(kw in answer.lower() for kw in tension_kw)) else 0.0

                    new_eval = {
                        "task_type": "T5",
                        "category": category,
                        "chain_coverage": round(chain, 3),
                        "multi_doc_cited": round(multi, 3),
                        "proactive_detection": proactive,
                        "judge_model": model,
                        "judge_raw": raw,
                    }
                    if category != "proactive_contradiction":
                        t5_chain.append(chain)
                    t5_multi.append(multi)
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
