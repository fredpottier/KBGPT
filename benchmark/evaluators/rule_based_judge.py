#!/usr/bin/env python3
"""
Rule-based Judge — Évaluateur déterministe pour T1 (provenance) et T4 (audit).

Pas de LLM, pas de parsing JSON, pas de biais longueur.
Reproductible, gratuit, instantané.

Usage:
    python benchmark/evaluators/rule_based_judge.py --results benchmark/results/run_v5_osmosis_task1_human.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def normalize(text: str) -> str:
    """Normalise pour comparaison : lowercase, whitespace, ponctuation."""
    t = text.lower().strip()
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return t


def extract_keywords(text: str, min_len: int = 4) -> set:
    """Extrait les mots significatifs (>= min_len chars)."""
    return {w for w in normalize(text).split() if len(w) >= min_len}


# ═══════════════════════════════════════════════════════════════════════
# T1 — Provenance : le fait attendu est-il dans la réponse ?
# ═══════════════════════════════════════════════════════════════════════

def judge_t1(result: Dict) -> Dict:
    """Évalue une réponse T1 par keyword matching sur le ground truth."""
    answer = result["response"].get("answer", "")
    gt = result["ground_truth"]
    expected_claim = gt.get("expected_claim", "")
    verbatim = gt.get("verbatim_quote", "")
    expected_doc = gt.get("doc_id", "")
    sources_used = result["response"].get("sources_used", [])

    answer_norm = normalize(answer)

    # 1. Réponse vide ou IDK ?
    if not answer or len(answer) < 20:
        return {"factual_correctness": 0.0, "answers_correctly": False,
                "says_idk": True, "citation_present": False,
                "correct_source_cited": False, "answer_relevant": False}

    idk_patterns = ["information not available", "pas disponible",
                    "je ne dispose pas", "aucune information",
                    "not available in the sources", "je ne trouve pas"]
    says_idk = any(p in answer.lower() for p in idk_patterns)

    # 2. Le fait attendu est-il dans la réponse ?
    # Stratégie : extraire les mots-clés du claim et du verbatim,
    # vérifier le taux de couverture dans la réponse
    claim_keywords = extract_keywords(expected_claim)
    verbatim_keywords = extract_keywords(verbatim)

    # Combiner : union des mots-clés claim + verbatim
    all_keywords = claim_keywords | verbatim_keywords
    if not all_keywords:
        return {"factual_correctness": 0.0, "answers_correctly": False,
                "says_idk": says_idk, "citation_present": False,
                "correct_source_cited": False, "answer_relevant": False}

    answer_words = set(normalize(answer).split())
    matched = all_keywords & answer_words
    coverage = len(matched) / len(all_keywords) if all_keywords else 0

    # Score factual : basé sur la couverture des mots-clés
    # >= 0.5 couverture = réponse contient le fait (les chunks parlent du sujet)
    # >= 0.3 = réponse partielle
    factual = min(coverage * 1.5, 1.0)  # scale up, cap at 1.0

    # 3. La bonne source est-elle citée ?
    doc_prefix = expected_doc[:20] if expected_doc else ""
    citation_present = any("[source" in answer.lower() or "source:" in answer.lower()
                          for _ in [1])
    correct_source = any(doc_prefix in s for s in sources_used) if doc_prefix else False

    # 4. La réponse est-elle pertinente (pas hors sujet) ?
    # Si au moins 20% des mots-clés sont présents, c'est pertinent
    answer_relevant = coverage >= 0.2 and not says_idk

    # 5. Answers correctly = factual >= 0.7 ET source correcte
    answers_correctly = factual >= 0.7 and correct_source

    # Si IDK mais la couverture est > 0, c'est un false_idk
    if says_idk and coverage >= 0.2:
        says_idk_when_info_exists = True
    else:
        says_idk_when_info_exists = says_idk and coverage < 0.2

    return {
        "factual_correctness": round(factual, 3),
        "answers_correctly": answers_correctly,
        "says_idk": says_idk,
        "says_idk_when_info_exists": says_idk and coverage >= 0.2,
        "citation_present": citation_present,
        "correct_source_cited": correct_source,
        "answer_relevant": answer_relevant,
        "keyword_coverage": round(coverage, 3),
    }


# ═══════════════════════════════════════════════════════════════════════
# T4 — Audit : couverture, sources, complétude
# ═══════════════════════════════════════════════════════════════════════

def judge_t4(result: Dict) -> Dict:
    """Évalue une réponse T4 par couverture documentaire et complétude."""
    answer = result["response"].get("answer", "")
    gt = result["ground_truth"]
    entity = gt.get("entity", "")
    expected_doc_count = int(gt.get("expected_doc_count", gt.get("must_mention_docs_count", 0)))
    expected_docs = gt.get("expected_docs", [])
    sources_used = result["response"].get("sources_used", [])

    answer_norm = normalize(answer)

    if not answer or len(answer) < 30:
        return {"factual_correctness": 0.0, "answers_correctly": False,
                "completeness": 0.0, "topic_coverage": False,
                "sources_mentioned": 0, "answer_relevant": False}

    # 1. L'entité est-elle mentionnée ?
    entity_norm = normalize(entity)
    entity_mentioned = entity_norm in answer_norm or any(
        w in answer_norm for w in entity_norm.split() if len(w) >= 4
    )

    # 2. Combien de sources distinctes ?
    unique_sources = set(sources_used)
    sources_count = len(unique_sources)

    # 3. Sources attendues couvertes ?
    if isinstance(expected_docs, list):
        docs_covered = sum(1 for doc in expected_docs
                          if any(doc[:20] in s for s in sources_used))
        doc_coverage = docs_covered / len(expected_docs) if expected_docs else 0
    else:
        doc_coverage = min(sources_count / max(expected_doc_count, 1), 1.0)

    # 4. Longueur comme proxy de complétude (T4 = export, plus = mieux)
    # Normaliser entre 200 et 2000 chars
    length_score = min(max((len(answer) - 200) / 1800, 0), 1.0)

    # 5. Score factual composite
    factual = (
        0.3 * (1.0 if entity_mentioned else 0.0) +
        0.4 * doc_coverage +
        0.3 * length_score
    )

    answers_correctly = factual >= 0.7 and sources_count >= 2

    return {
        "factual_correctness": round(factual, 3),
        "answers_correctly": answers_correctly,
        "completeness": round(length_score, 3),
        "topic_coverage": entity_mentioned,
        "sources_mentioned": sources_count,
        "doc_coverage": round(doc_coverage, 3),
        "answer_relevant": entity_mentioned,
        "answer_length": len(answer),
    }


# ═══════════════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════════════

def aggregate(judgments: List[Dict], task: str) -> Dict:
    """Agrège les jugements en scores."""
    n = len(judgments)
    if n == 0:
        return {}

    scores = {}
    jlist = [j["judgment"] for j in judgments]

    # Métriques universelles
    factuals = [j["factual_correctness"] for j in jlist]
    scores["factual_correctness_avg"] = sum(factuals) / n
    scores["answers_correctly_rate"] = sum(1 for j in jlist if j["answers_correctly"]) / n
    scores["answer_relevant_rate"] = sum(1 for j in jlist if j["answer_relevant"]) / n

    if task.startswith("T1"):
        scores["false_idk_rate"] = sum(1 for j in jlist if j.get("says_idk_when_info_exists")) / n
        scores["citation_present_rate"] = sum(1 for j in jlist if j["citation_present"]) / n
        scores["correct_source_rate"] = sum(1 for j in jlist if j["correct_source_cited"]) / n
        # false_answer = relevant mais factual < 0.5
        scores["false_answer_rate"] = sum(1 for j in jlist
                                          if j["answer_relevant"] and j["factual_correctness"] < 0.5) / n
        scores["irrelevant_rate"] = sum(1 for j in jlist if not j["answer_relevant"]) / n

    elif task.startswith("T4"):
        scores["completeness_avg"] = sum(j["completeness"] for j in jlist) / n
        scores["topic_coverage_rate"] = sum(1 for j in jlist if j["topic_coverage"]) / n
        scores["sources_mentioned_rate"] = sum(1 for j in jlist if j["sources_mentioned"] >= 2) / n
        scores["false_answer_rate"] = sum(1 for j in jlist
                                          if j["answer_relevant"] and j["factual_correctness"] < 0.4) / n

    elif task.startswith("T5"):
        # Métriques par catégorie
        chains = [j for j in jlist if j.get("category") == "cross_doc_chain"]
        proactive = [j for j in jlist if j.get("category") == "proactive_contradiction"]
        multi = [j for j in jlist if j.get("category") == "multi_source_synthesis"]

        if chains:
            scores["cross_doc_chain_score"] = sum(j["cross_doc_score"] for j in chains) / len(chains)
            scores["cross_doc_chain_correct"] = sum(1 for j in chains if j["answers_correctly"]) / len(chains)
            scores["cross_doc_avg_docs_cited"] = sum(j["docs_cited"] for j in chains) / len(chains)

        if proactive:
            scores["proactive_detection_rate"] = sum(1 for j in proactive if j["proactive_detection"]) / len(proactive)
            scores["proactive_both_sides_rate"] = sum(1 for j in proactive if j.get("both_sides_surfaced")) / len(proactive)
            scores["proactive_full_score"] = sum(1 for j in proactive if j["answers_correctly"]) / len(proactive)

        if multi:
            scores["multi_source_correct"] = sum(1 for j in multi if j["answers_correctly"]) / len(multi)
            scores["multi_source_avg_docs"] = sum(j["docs_cited"] for j in multi) / len(multi)
            scores["multi_source_aspect_coverage"] = sum(j["multi_aspect_coverage"] for j in multi) / len(multi)

        scores["questions_by_category"] = {
            "cross_doc_chain": len(chains),
            "proactive_contradiction": len(proactive),
            "multi_source_synthesis": len(multi),
        }

    scores["total_evaluated"] = n
    scores["total_error_rate"] = 0.0

    return scores


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# T5 — KG Differentiators : cross-doc, proactive detection, multi-source
# ═══════════════════════════════════════════════════════════════════════

def judge_t5(result: Dict) -> Dict:
    """Évalue une réponse T5 — ce qu'un RAG pur ne peut PAS faire."""
    answer = result["response"].get("answer", "")
    gt = result["ground_truth"]
    sources_used = result["response"].get("sources_used", [])
    # Extraire la catégorie du champ task (T5_cross_doc, T5_proactive_detection, T5_multi_source)
    task_field = result.get("task", "")
    if "cross_doc" in task_field:
        category = "cross_doc_chain"
    elif "proactive" in task_field:
        category = "proactive_contradiction"
    elif "multi_source" in task_field:
        category = "multi_source_synthesis"
    else:
        category = result.get("category", "")
    answer_lower = answer.lower()

    if not answer or len(answer) < 30:
        return {"factual_correctness": 0.0, "answers_correctly": False,
                "cross_doc_score": 0.0, "docs_cited": 0,
                "proactive_detection": False, "multi_aspect_coverage": 0.0,
                "answer_relevant": False, "category": category}

    unique_docs = set()
    for s in sources_used:
        # Extraire le prefixe doc (ex: "027_SAP...")
        doc_prefix = s[:3] if s else ""
        if doc_prefix.isdigit():
            unique_docs.add(doc_prefix)

    docs_cited = len(unique_docs)

    if category == "cross_doc_chain":
        # Vérifier si chaque élément de la chaîne est mentionné
        chain = gt.get("chain", [])
        chain_hits = 0
        for link in chain:
            link_keywords = extract_keywords(link["text"])
            matched = link_keywords & set(normalize(answer).split())
            if len(matched) >= max(2, len(link_keywords) * 0.3):
                chain_hits += 1

        chain_coverage = chain_hits / len(chain) if chain else 0
        min_docs = gt.get("docs_required", 2)

        return {
            "factual_correctness": round(chain_coverage * 0.7 + min(docs_cited / min_docs, 1.0) * 0.3, 3),
            "answers_correctly": chain_coverage >= 0.66 and docs_cited >= 2,
            "cross_doc_score": round(chain_coverage, 3),
            "chain_elements_found": chain_hits,
            "chain_total": len(chain),
            "docs_cited": docs_cited,
            "proactive_detection": False,
            "multi_aspect_coverage": 0.0,
            "answer_relevant": chain_coverage >= 0.3,
            "category": "cross_doc_chain",
        }

    elif category == "proactive_contradiction":
        # La question ne demande PAS s'il y a une contradiction
        # Le système devrait PROACTIVEMENT la signaler
        tension_words = ["contradi", "divergen", "tension", "incoheren",
                        "deux version", "different", "noter que", "attention",
                        "cependant", "toutefois", "en revanche", "while",
                        "however", "discrepan", "a change", "renomm",
                        "deux document", "version 2022", "version 2023"]
        proactive = any(w in answer_lower for w in tension_words)

        # Vérifier si les deux côtés de la contradiction sont mentionnés
        hidden = gt.get("hidden_contradiction", {})
        c1_kw = extract_keywords(hidden.get("claim1", {}).get("text", ""))
        c2_kw = extract_keywords(hidden.get("claim2", {}).get("text", ""))
        c1_unique = {w for w in c1_kw - c2_kw if len(w) > 4}
        c2_unique = {w for w in c2_kw - c1_kw if len(w) > 4}
        answer_words = set(normalize(answer).split())
        both_sides = (len(c1_unique & answer_words) >= 1 and
                     len(c2_unique & answer_words) >= 1) if (c1_unique and c2_unique) else False

        fc = 0.0
        if proactive and both_sides:
            fc = 1.0
        elif proactive:
            fc = 0.7
        elif both_sides:
            fc = 0.5
        else:
            fc = 0.3 if docs_cited >= 2 else 0.1

        return {
            "factual_correctness": fc,
            "answers_correctly": proactive and both_sides,
            "cross_doc_score": 0.0,
            "docs_cited": docs_cited,
            "proactive_detection": proactive,
            "both_sides_surfaced": both_sides,
            "multi_aspect_coverage": 0.0,
            "answer_relevant": True,
            "category": "proactive_contradiction",
        }

    elif category == "multi_source_synthesis":
        # Vérifier la couverture multi-source
        min_docs = gt.get("min_docs_required", 3)
        expected_aspects = gt.get("expected_aspects", [])

        # Vérifier les aspects couverts
        aspects_found = 0
        for aspect in expected_aspects:
            aspect_keywords = set(aspect.lower().replace("_", " ").split())
            if any(kw in answer_lower for kw in aspect_keywords if len(kw) > 3):
                aspects_found += 1

        aspect_coverage = aspects_found / len(expected_aspects) if expected_aspects else 0
        doc_score = min(docs_cited / min_docs, 1.0)

        fc = 0.4 * doc_score + 0.4 * aspect_coverage + 0.2 * min(len(answer) / 1500, 1.0)

        return {
            "factual_correctness": round(fc, 3),
            "answers_correctly": docs_cited >= min_docs and aspect_coverage >= 0.5,
            "cross_doc_score": round(doc_score, 3),
            "docs_cited": docs_cited,
            "proactive_detection": False,
            "multi_aspect_coverage": round(aspect_coverage, 3),
            "aspects_found": aspects_found,
            "aspects_total": len(expected_aspects),
            "answer_relevant": True,
            "answer_length": len(answer),
            "category": "multi_source_synthesis",
        }

    return {"factual_correctness": 0.0, "answers_correctly": False,
            "cross_doc_score": 0.0, "docs_cited": 0,
            "proactive_detection": False, "multi_aspect_coverage": 0.0,
            "answer_relevant": False, "category": category}


TASK_JUDGES = {
    "T1": judge_t1,
    "T2": None,  # T2 = évaluation manuelle, pas rule-based
    "T4": judge_t4,
    "T5": judge_t5,
}


def evaluate(results_path: str, output_path: str = None):
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data["results"]
    metadata = data["metadata"]
    task = metadata["task"]

    judge_fn = TASK_JUDGES.get(task)
    if not judge_fn:
        logger.error(f"Pas de juge rule-based pour {task}. Utiliser l'évaluation manuelle.")
        return

    logger.info(f"Rule-based judge: {len(results)} results for {metadata['system']}/{task}")

    judgments = []
    for r in results:
        judgment = judge_fn(r)
        judgments.append({
            "question_id": r["question_id"],
            "system": metadata["system"],
            "judgment": judgment,
            "error": None,
        })

    scores = aggregate(judgments, task)

    output = {
        "metadata": {
            **metadata,
            "judge_model": "rule-based-v1",
            "judge_type": "deterministic",
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "scores": scores,
        "judgments": judgments,
    }

    out_path = output_path or results_path.replace(".json", "_ruled.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\n{'='*50}")
    logger.info(f"RULE-BASED JUDGE — {metadata['system']} / {task}")
    logger.info(f"{'='*50}")
    for k, v in sorted(scores.items()):
        if isinstance(v, float):
            logger.info(f"  {k:<35s} {v:.3f}")
        else:
            logger.info(f"  {k:<35s} {v}")

    return scores


def main():
    parser = argparse.ArgumentParser(description="Rule-based judge (T1/T4)")
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    evaluate(args.results, args.output)


if __name__ == "__main__":
    main()
