"""S0.5 — Fast path distribution multi-corpus (révisé V1.1 R3+Q3).

Classifier les questions via DeBERTa S2 cascade pour mesurer :
- % de questions "factual_simple" (éligibles au cheap path V5)
- Précision du routing vs ground-truth
- Distribution par corpus

ADR V1.4 §3e gate : ≥ 40% factual_simple agrégé ET précision routing ≥ 90%.
Plan B B-1/B-2/B-3/B-4 si gate échoue (cf ADR §3e V1.2).

Corpus :
- SAP : 30q gold-set Fred-rédigé (primary_type ground truth)
- Aerospace : ~50q proxy via domain in {manufacturing, scientific, it_cloud} du training set
- Regulatory_eu : 49q domain=regulatory + 45q legal du training set (≈94q)

Mapping gold-set SAP primary_type → DeBERTa labels (7 classes) :
- factual / quantitative / contextual / multi_hop / negation → factual
- listing → list
- lifecycle → temporal
- comparison → comparison
- causal → causal
- false_premise → false_premise
- unanswerable → unanswerable

Fast path éligible = top1 == 'factual' ET confidence ≥ 0.85.

Run :
    docker exec knowbase-app bash -c "cd /app && python scripts/s05_fast_path_distribution.py"
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")
sys.path.insert(0, "/app")

from knowbase.facts_first.analyzer_cascade import AnalyzerCascade

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GOLDSET = Path("/app/benchmark/questions/gold_set_sap_v2.json")
TRAINING_JSONL = Path("/app/data/router/train.jsonl")
OUT = Path("/app/benchmark/results/s05_fast_path_distribution_v2.json")

# Map V5 answer_shape → fast_path éligible
FAST_PATH_DEBERTA_LABEL = "factual"
CONFIDENCE_THRESHOLD = 0.85

# Mapping gold-set SAP primary_type → DeBERTa label
SAP_GOLDSET_TO_DEBERTA = {
    "factual": "factual",
    "quantitative": "factual",
    "contextual": "factual",
    "multi_hop": "factual",
    "negation": "factual",
    "listing": "list",
    "lifecycle": "temporal",
    "comparison": "comparison",
    "causal": "causal",
    "false_premise": "false_premise",
    "unanswerable": "unanswerable",
}


def classify_question(cascade: AnalyzerCascade, question: str) -> dict:
    """Run DeBERTa classification on a question, return top-1 + top-2."""
    try:
        top1, c1, top2, c2 = cascade.predict_deberta(question)
        eligible_fast_path = (top1 == FAST_PATH_DEBERTA_LABEL) and (c1 >= CONFIDENCE_THRESHOLD)
        return {
            "top1": top1,
            "top1_conf": c1,
            "top2": top2,
            "top2_conf": c2,
            "fast_path_eligible": eligible_fast_path,
            "error": None,
        }
    except Exception as e:
        return {
            "top1": None,
            "top1_conf": 0.0,
            "top2": None,
            "top2_conf": 0.0,
            "fast_path_eligible": False,
            "error": str(e),
        }


def load_sap_questions() -> list[dict]:
    """Charger gold-set SAP avec mapping primary_type → DeBERTa label."""
    items = json.loads(GOLDSET.read_text(encoding="utf-8"))
    questions = []
    for q in items:
        primary = q.get("primary_type", "unknown")
        deberta_gt = SAP_GOLDSET_TO_DEBERTA.get(primary, "factual")  # default factual
        questions.append({
            "id": q["id"],
            "text": q["question"],
            "gt_type": deberta_gt,
            "gt_original_type": primary,
        })
    return questions


def load_training_subset(domains: list[str], max_n: int = 50) -> list[dict]:
    """Charger sample du training set filtrée par domains."""
    if not TRAINING_JSONL.exists():
        return []
    items = []
    with open(TRAINING_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("domain") in domains:
                items.append({
                    "id": d.get("id", f"unk_{len(items)}"),
                    "text": d.get("text", ""),
                    "gt_type": d.get("label_name", "unknown"),
                    "gt_original_type": d.get("label_name", "unknown"),
                    "domain": d.get("domain"),
                    "language": d.get("language"),
                })
            if len(items) >= max_n:
                break
    return items


def analyze_corpus(corpus_name: str, questions: list[dict], cascade: AnalyzerCascade) -> dict:
    """Run cascade sur questions, calcul métriques."""
    logger.info(f"[{corpus_name}] Analyzing {len(questions)} questions...")
    results = []
    for q in questions:
        question_text = q["text"]
        gt_type = q["gt_type"]
        if not question_text:
            continue
        pred = classify_question(cascade, question_text)
        results.append({
            "id": q["id"],
            "question": question_text[:200],
            "gt_type": gt_type,
            "gt_original_type": q.get("gt_original_type", gt_type),
            "pred_top1": pred["top1"],
            "pred_top1_conf": pred["top1_conf"],
            "pred_top2": pred["top2"],
            "pred_top2_conf": pred["top2_conf"],
            "fast_path_eligible": pred["fast_path_eligible"],
            "error": pred["error"],
        })

    n = len(results)
    if n == 0:
        return {"corpus": corpus_name, "n": 0, "error": "no questions"}

    n_eligible = sum(1 for r in results if r["fast_path_eligible"])
    fast_path_pct = n_eligible / n

    dist_pred = Counter(r["pred_top1"] for r in results)
    dist_gt = Counter(r["gt_type"] for r in results)

    correct = sum(1 for r in results if r["pred_top1"] == r["gt_type"])
    precision = correct / n

    by_shape = defaultdict(lambda: {"n": 0, "correct": 0, "avg_conf": []})
    for r in results:
        by_shape[r["gt_type"]]["n"] += 1
        if r["pred_top1"] == r["gt_type"]:
            by_shape[r["gt_type"]]["correct"] += 1
        by_shape[r["gt_type"]]["avg_conf"].append(r["pred_top1_conf"])
    by_shape_summary = {
        shape: {
            "n": d["n"],
            "precision": d["correct"] / d["n"] if d["n"] > 0 else 0,
            "avg_conf": sum(d["avg_conf"]) / len(d["avg_conf"]) if d["avg_conf"] else 0,
        }
        for shape, d in by_shape.items()
    }

    logger.info(f"  n={n}, fast_path={fast_path_pct:.1%}, precision={precision:.1%}")
    return {
        "corpus": corpus_name,
        "n": n,
        "fast_path_eligible_count": n_eligible,
        "fast_path_pct": fast_path_pct,
        "routing_precision": precision,
        "dist_pred_top1": dict(dist_pred),
        "dist_gt_type": dict(dist_gt),
        "by_shape": by_shape_summary,
        "samples": results,
    }


def main():
    logger.info("Loading AnalyzerCascade (DeBERTa S2)...")
    cascade = AnalyzerCascade()

    # 1. SAP gold-set
    sap_questions = load_sap_questions()
    logger.info(f"SAP gold-set: {len(sap_questions)} questions")
    sap_stats = analyze_corpus("SAP_PCE_gold_set", sap_questions, cascade)

    # 2. Aerospace proxy (manufacturing + scientific + it_cloud domains)
    aerospace_q = load_training_subset(["manufacturing", "scientific", "it_cloud"], max_n=50)
    logger.info(f"Aerospace proxy: {len(aerospace_q)} questions")
    aerospace_stats = analyze_corpus("aerospace_proxy", aerospace_q, cascade)

    # 3. Regulatory + legal
    regulatory_q = load_training_subset(["regulatory", "legal"], max_n=50)
    logger.info(f"Regulatory+legal: {len(regulatory_q)} questions")
    regulatory_stats = analyze_corpus("regulatory_eu_sample", regulatory_q, cascade)

    # Aggregate
    all_corpora = [sap_stats, aerospace_stats, regulatory_stats]
    total_n = sum(c.get("n", 0) for c in all_corpora)
    total_eligible = sum(c.get("fast_path_eligible_count", 0) for c in all_corpora)
    agg_fast_path = total_eligible / total_n if total_n > 0 else 0

    total_correct = 0
    for c in all_corpora:
        for d in c.get("by_shape", {}).values():
            total_correct += int(d["precision"] * d["n"])
    agg_precision = total_correct / total_n if total_n > 0 else 0

    # Gate assessment
    gate_fast_path_threshold = 0.40
    gate_precision_threshold = 0.90
    gate_passed = (agg_fast_path >= gate_fast_path_threshold and agg_precision >= gate_precision_threshold)

    # Plan B
    if gate_passed:
        plan_b = None
    elif agg_fast_path >= 0.36 and agg_precision >= 0.81:
        plan_b = "B-1 : resserrer cheap path à confidence > 0.95 (vs 0.85)"
    elif agg_fast_path >= 0.32 and agg_precision >= 0.72:
        plan_b = "B-2 : cheap path adaptatif par corpus, tuning routeur Phase 2"
    elif agg_fast_path >= 0.28 and agg_precision >= 0.63:
        plan_b = "B-3 : abandonner cheap path, agent path systématique, revoir cap tokens"
    else:
        plan_b = "B-4 : revoir architecture, possibilité hybride V4.2/V5"

    report = {
        "metadata": {
            "ran_at": datetime.utcnow().isoformat(),
            "purpose": "S0.5 Fast path distribution multi-corpus",
            "model": "DeBERTa S2 (XLM-R fine-tuned on 14767q multi-domains)",
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "gate_fast_path_threshold": gate_fast_path_threshold,
            "gate_precision_threshold": gate_precision_threshold,
            "fast_path_label": FAST_PATH_DEBERTA_LABEL,
            "sap_mapping": SAP_GOLDSET_TO_DEBERTA,
        },
        "aggregate": {
            "total_n": total_n,
            "fast_path_eligible_count": total_eligible,
            "fast_path_pct": agg_fast_path,
            "routing_precision": agg_precision,
            "gate_passed": gate_passed,
            "plan_b_if_failed": plan_b,
        },
        "per_corpus": {
            "sap": sap_stats,
            "aerospace_proxy": aerospace_stats,
            "regulatory_eu": regulatory_stats,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWritten: {OUT}")
    print(f"=" * 70)
    print(f"S0.5 RESULTS")
    print(f"=" * 70)
    print(f"Total: n={total_n}")
    print(f"  Fast path eligible: {total_eligible}/{total_n} = {agg_fast_path:.1%}")
    print(f"  Routing precision: {agg_precision:.1%}")
    print(f"")
    print(f"Per corpus:")
    for c in all_corpora:
        if c.get("n", 0) > 0:
            print(f"  {c['corpus']:30s} n={c['n']:3d}  fast_path={c['fast_path_pct']:.1%}  precision={c['routing_precision']:.1%}")
    print(f"")
    print(f"GATE (fast_path >= {gate_fast_path_threshold:.0%} ET precision >= {gate_precision_threshold:.0%})")
    print(f"Result: {'PASSED' if gate_passed else 'FAILED'}")
    if not gate_passed:
        print(f"Plan B applicable: {plan_b}")


if __name__ == "__main__":
    main()
