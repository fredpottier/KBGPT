#!/usr/bin/env python3
"""
Evaluateur des 5 metriques primaires pre-enregistrees.

P1: Citation Recall (ALCE) — T1
P2: Contradiction Detection F1 — T2
P3: Version-Mixing Detection F1 — T3
P4: Export Completeness — T4
P5: Faithfulness (RAGAS-style) — Cross

Usage:
    python benchmark/evaluators/primary_metrics.py --osmosis results/osmosis_T1.json --baseline results/rag_T1.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-eval")


# ═══════════════════════════════════════════════════════════════════════
# P1 — Citation Recall (ALCE-style)
# ═══════════════════════════════════════════════════════════════════════


def eval_p1_citation_recall(results: List[Dict]) -> Dict[str, float]:
    """Evalue si les affirmations de la reponse sont supportees par des citations.

    Pour chaque question :
    - Extraire les citations mentionnees dans la reponse ([Source N])
    - Verifier si la reponse contient l'info du ground truth
    - Verifier si les sources citees correspondent au document attendu
    """
    total = 0
    citation_present = 0
    citation_correct = 0
    answer_contains_fact = 0

    for r in results:
        total += 1
        gt = r.get("ground_truth", {})
        response = r.get("response", {})
        answer = response.get("answer", "")

        if not answer:
            continue

        # 1. La reponse contient-elle des citations ?
        citations = re.findall(r"\[Source\s*\d+\]|\[source\s*\d+\]|\[\d+\]", answer, re.IGNORECASE)
        if citations:
            citation_present += 1

        # 2. La citation pointe-t-elle vers le bon document ?
        expected_doc = gt.get("doc_id", "")
        sources_used = response.get("sources_used", [])
        results_list = response.get("results", [])

        if expected_doc:
            for source in sources_used:
                if expected_doc in str(source):
                    citation_correct += 1
                    break
            else:
                for res_item in results_list:
                    if expected_doc in str(res_item.get("source_file", "")):
                        citation_correct += 1
                        break

        # 3. La reponse contient-elle le fait attendu ?
        expected_fact = gt.get("expected_claim", gt.get("claim_text", ""))
        if expected_fact:
            # Match approximatif : au moins 3 mots significatifs en commun
            fact_words = set(w.lower() for w in expected_fact.split() if len(w) > 4)
            answer_words = set(w.lower() for w in answer.split() if len(w) > 4)
            overlap = len(fact_words & answer_words)
            if overlap >= min(3, len(fact_words)):
                answer_contains_fact += 1

    return {
        "P1_citation_recall": citation_present / max(total, 1),
        "P1_citation_correctness": citation_correct / max(total, 1),
        "P1_fact_recall": answer_contains_fact / max(total, 1),
        "P1_total_questions": total,
    }


# ═══════════════════════════════════════════════════════════════════════
# P2 — Contradiction Detection F1
# ═══════════════════════════════════════════════════════════════════════


def eval_p2_contradiction_f1(results: List[Dict]) -> Dict[str, float]:
    """Evalue si le systeme detecte et expose les contradictions.

    Pour chaque question sur une contradiction connue :
    - La reponse mentionne-t-elle les deux cotes ?
    - La reponse arbitre-t-elle silencieusement ?
    """
    total = 0
    both_sides_surfaced = 0
    silent_arbitration = 0
    tension_type_correct = 0

    for r in results:
        total += 1
        gt = r.get("ground_truth", {})
        response = r.get("response", {})
        answer = response.get("answer", "")

        if not answer:
            continue

        claim1_text = gt.get("claim1", {}).get("text", "")
        claim2_text = gt.get("claim2", {}).get("text", "")

        if not claim1_text or not claim2_text:
            continue

        # Extraire les mots cles de chaque claim
        kw1 = set(w.lower() for w in claim1_text.split() if len(w) > 5)
        kw2 = set(w.lower() for w in claim2_text.split() if len(w) > 5)
        answer_words = set(w.lower() for w in answer.split())

        side1_present = len(kw1 & answer_words) >= min(2, len(kw1))
        side2_present = len(kw2 & answer_words) >= min(2, len(kw2))

        if side1_present and side2_present:
            both_sides_surfaced += 1
        elif side1_present or side2_present:
            silent_arbitration += 1

        # Verifier si le type de tension est mentionne
        contradiction_keywords = [
            "contradiction", "contradictoire", "divergen", "tension",
            "different", "contraire", "oppose", "incoheren",
        ]
        if any(kw in answer.lower() for kw in contradiction_keywords):
            tension_type_correct += 1

    # F1 = 2 * P * R / (P + R)
    precision = both_sides_surfaced / max(both_sides_surfaced + silent_arbitration, 1)
    recall = both_sides_surfaced / max(total, 1)
    f1 = 2 * precision * recall / max(precision + recall, 0.0001)

    return {
        "P2_contradiction_f1": f1,
        "P2_both_sides_surfaced": both_sides_surfaced / max(total, 1),
        "P2_silent_arbitration_rate": silent_arbitration / max(total, 1),
        "P2_tension_mentioned": tension_type_correct / max(total, 1),
        "P2_total_questions": total,
    }


# ═══════════════════════════════════════════════════════════════════════
# P3 — Version-Mixing Detection F1
# ═══════════════════════════════════════════════════════════════════════


def eval_p3_version_mixing(results: List[Dict]) -> Dict[str, float]:
    """Evalue si le systeme distingue correctement les versions."""
    total = 0
    version_distinguished = 0
    version_mixed = 0

    for r in results:
        total += 1
        gt = r.get("ground_truth", {})
        response = r.get("response", {})
        answer = response.get("answer", "")

        if not answer:
            continue

        versions = gt.get("versions", [])
        if len(versions) < 2:
            continue

        # Verifier si les versions sont mentionnees dans la reponse
        versions_found = [v for v in versions if str(v) in answer]

        if len(versions_found) >= 2:
            version_distinguished += 1
        elif len(versions_found) == 1:
            # Une seule version mentionnee — potentiel mix silencieux
            version_mixed += 1

    recall = version_distinguished / max(total, 1)
    precision = version_distinguished / max(version_distinguished + version_mixed, 1)
    f1 = 2 * precision * recall / max(precision + recall, 0.0001)

    return {
        "P3_version_mixing_f1": f1,
        "P3_versions_distinguished": version_distinguished / max(total, 1),
        "P3_versions_mixed": version_mixed / max(total, 1),
        "P3_total_questions": total,
    }


# ═══════════════════════════════════════════════════════════════════════
# P4 — Export Completeness
# ═══════════════════════════════════════════════════════════════════════


def eval_p4_export_completeness(results: List[Dict]) -> Dict[str, float]:
    """Evalue la completude des exports d'audit."""
    total = 0
    total_completeness = 0.0

    for r in results:
        total += 1
        gt = r.get("ground_truth", {})
        response = r.get("response", {})
        answer = response.get("answer", "")

        if not answer:
            continue

        expected_claims = gt.get("expected_claim_count", 0)
        expected_docs = gt.get("expected_doc_count", 0)
        entity_name = gt.get("entity", "")

        # Mesurer ce qui est present dans la reponse
        completeness = 0.0
        checks = 0

        # Entity mentionnee ?
        if entity_name and entity_name.lower() in answer.lower():
            completeness += 1
        checks += 1

        # Sources/documents mentionnes ?
        source_keywords = ["source", "document", "guide", "page"]
        if any(kw in answer.lower() for kw in source_keywords):
            completeness += 1
        checks += 1

        # Contradictions mentionnees si attendues ?
        expected_contradictions = gt.get("expected_contradiction_count", 0)
        if expected_contradictions > 0:
            if "contradiction" in answer.lower() or "tension" in answer.lower() or "divergen" in answer.lower():
                completeness += 1
            checks += 1

        # Longueur suffisante ?
        if len(answer) > 200:
            completeness += 1
        checks += 1

        total_completeness += completeness / max(checks, 1)

    return {
        "P4_export_completeness": total_completeness / max(total, 1),
        "P4_total_questions": total,
    }


# ═══════════════════════════════════════════════════════════════════════
# P5 — Faithfulness (RAGAS-style simplified)
# ═══════════════════════════════════════════════════════════════════════


def eval_p5_faithfulness(results: List[Dict]) -> Dict[str, float]:
    """Evalue si la reponse est fidele aux sources recuperees.

    Version simplifiee : verifie que les affirmations de la reponse
    sont supportees par les chunks/claims retournes.
    """
    total = 0
    faithful_count = 0
    hallucination_count = 0
    idk_count = 0

    idk_phrases = [
        "je ne dispose pas", "je n'ai pas", "pas d'information",
        "non documente", "pas dans les sources", "aucune information",
        "i don't have", "no information", "not documented",
    ]

    for r in results:
        total += 1
        response = r.get("response", {})
        answer = response.get("answer", "")

        if not answer:
            continue

        # Detection "I don't know"
        if any(phrase in answer.lower() for phrase in idk_phrases):
            idk_count += 1
            faithful_count += 1  # "je ne sais pas" est fidele
            continue

        # Verifier si le contenu de la reponse est dans les sources
        results_list = response.get("results", response.get("chunks", []))
        source_text = " ".join(
            r_item.get("text", "") for r_item in results_list
        ).lower()

        if not source_text:
            continue

        # Extraire les phrases de la reponse et verifier le support
        sentences = [s.strip() for s in re.split(r'[.!?]', answer) if len(s.strip()) > 20]
        supported = 0

        for sentence in sentences:
            # Mots significatifs de la phrase
            words = set(w.lower() for w in sentence.split() if len(w) > 4)
            # Au moins 50% des mots doivent etre dans les sources
            if words:
                overlap = sum(1 for w in words if w in source_text)
                if overlap / len(words) >= 0.4:
                    supported += 1

        if sentences:
            faithfulness = supported / len(sentences)
            if faithfulness >= 0.6:
                faithful_count += 1
            else:
                hallucination_count += 1

    return {
        "P5_faithfulness": faithful_count / max(total, 1),
        "P5_hallucination_rate": hallucination_count / max(total, 1),
        "P5_idk_rate": idk_count / max(total, 1),
        "P5_total_questions": total,
    }


# ═══════════════════════════════════════════════════════════════════════
# Comparaison OSMOSIS vs Baseline
# ═══════════════════════════════════════════════════════════════════════


def compare_systems(osmosis_path: str, baseline_path: str) -> Dict[str, Any]:
    """Compare OSMOSIS vs une baseline sur les 5 metriques primaires."""

    with open(osmosis_path, "r", encoding="utf-8") as f:
        osmosis_data = json.load(f)
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline_data = json.load(f)

    task = osmosis_data["metadata"]["task"]
    osmosis_results = osmosis_data["results"]
    baseline_results = baseline_data["results"]

    # Evaluer chaque systeme
    evaluators = {
        "T1_provenance": [eval_p1_citation_recall, eval_p5_faithfulness],
        "T2_contradictions": [eval_p2_contradiction_f1, eval_p5_faithfulness],
        "T3_temporal": [eval_p3_version_mixing, eval_p5_faithfulness],
        "T4_audit": [eval_p4_export_completeness, eval_p5_faithfulness],
    }

    evals = evaluators.get(task, [eval_p5_faithfulness])

    osmosis_metrics = {}
    baseline_metrics = {}

    for eval_fn in evals:
        osmosis_metrics.update(eval_fn(osmosis_results))
        baseline_metrics.update(eval_fn(baseline_results))

    # Latence moyenne
    osmosis_latencies = [r["response"].get("latency_ms", 0) for r in osmosis_results]
    baseline_latencies = [r["response"].get("latency_ms", 0) for r in baseline_results]

    osmosis_metrics["avg_latency_ms"] = sum(osmosis_latencies) / max(len(osmosis_latencies), 1)
    baseline_metrics["avg_latency_ms"] = sum(baseline_latencies) / max(len(baseline_latencies), 1)

    # Delta
    deltas = {}
    for key in osmosis_metrics:
        if key in baseline_metrics and isinstance(osmosis_metrics[key], (int, float)):
            deltas[key] = osmosis_metrics[key] - baseline_metrics[key]

    return {
        "task": task,
        "osmosis": osmosis_metrics,
        "baseline": {
            "system": baseline_data["metadata"]["system"],
            "metrics": baseline_metrics,
        },
        "deltas": deltas,
        "osmosis_wins": sum(1 for v in deltas.values() if v > 0),
        "baseline_wins": sum(1 for v in deltas.values() if v < 0),
        "ties": sum(1 for v in deltas.values() if v == 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate primary benchmark metrics")
    parser.add_argument("--osmosis", required=True, help="OSMOSIS results JSON")
    parser.add_argument("--baseline", required=True, help="Baseline results JSON")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    comparison = compare_systems(args.osmosis, args.baseline)

    # Afficher
    print(f"\n{'='*60}")
    print(f"BENCHMARK COMPARISON — {comparison['task']}")
    print(f"{'='*60}")
    print(f"\nOSMOSIS vs {comparison['baseline']['system']}")
    print(f"\n{'Metric':<35} {'OSMOSIS':>10} {'Baseline':>10} {'Delta':>10}")
    print(f"{'-'*65}")

    for key in sorted(comparison["osmosis"].keys()):
        osm_val = comparison["osmosis"][key]
        bas_val = comparison["baseline"]["metrics"].get(key, "N/A")
        delta = comparison["deltas"].get(key, "")

        if isinstance(osm_val, float):
            osm_str = f"{osm_val:.3f}"
            bas_str = f"{bas_val:.3f}" if isinstance(bas_val, float) else str(bas_val)
            delta_str = f"{delta:+.3f}" if isinstance(delta, float) else ""
        else:
            osm_str = str(osm_val)
            bas_str = str(bas_val)
            delta_str = ""

        print(f"{key:<35} {osm_str:>10} {bas_str:>10} {delta_str:>10}")

    print(f"\nOSMOSIS wins: {comparison['osmosis_wins']}, "
          f"Baseline wins: {comparison['baseline_wins']}, "
          f"Ties: {comparison['ties']}")

    # Sauvegarder
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
