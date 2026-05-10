"""
CH-46 — Analyse qualité du bench stratifié 30q.

Lit le JSON output de diag_v4_stratified_breakdown.py et calcule :
  1. Decision correctness : ANSWER attendu vs reçu / ABSTAIN attendu vs reçu
  2. Exact identifier preservation : substring case-insensitive de chaque ID attendu
  3. Doc ID citation : intersection avec supporting_doc_ids du gold-set
  4. Faithfulness Channel 2 (déjà dans la réponse V4)

Output : tableau global + détail par type + liste des cas problématiques.

Usage : docker exec knowbase-app python /app/scripts/analyze_v4_stratified_quality.py /app/data/router/v4_stratified_CH46_quality.json
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path


def normalize(s: str) -> str:
    """Lowercase + collapse whitespace."""
    return " ".join(s.lower().split())


def has_identifier(text: str, ident: str) -> bool:
    """Substring case-insensitive après normalisation."""
    return normalize(ident) in normalize(text)


def evaluate_one(sample: dict) -> dict:
    """Calcule les métriques pour un sample."""
    gt = sample.get("ground_truth") or {}
    answer = sample.get("answer") or ""
    decision = sample.get("decision") or ""
    doc_ids_cited = sample.get("doc_ids_cited") or []

    # 1. Decision correctness
    expected_answerability = (gt.get("answerability") or "answerable").lower()
    received = "ABSTAIN" if decision == "ABSTAIN" else "ANSWER"
    if expected_answerability == "answerable":
        decision_correct = received == "ANSWER"
    elif expected_answerability == "unanswerable":
        decision_correct = received == "ABSTAIN"
    else:  # partial
        decision_correct = True  # accepter les 2

    # False premise check
    fp_expected = bool(gt.get("false_premise"))
    fp_detected = sample.get("decision") == "REJECT_FALSE_PREMISE" or "false premise" in answer.lower() or "fausse prémisse" in answer.lower()
    fp_correct = (fp_expected == fp_detected) if fp_expected or fp_detected else True

    # 2. Exact identifier preservation
    expected_ids = gt.get("exact_identifiers") or []
    matched_ids = [i for i in expected_ids if has_identifier(answer, i)]
    n_matched = len(matched_ids)
    n_expected = len(expected_ids)
    id_score = n_matched / n_expected if n_expected > 0 else None  # None = N/A

    # 3. Doc ID citation
    expected_doc_ids = gt.get("supporting_doc_ids") or []
    cited_set = set(doc_ids_cited)
    expected_set = set(expected_doc_ids)
    matched_docs = cited_set & expected_set
    n_doc_matched = len(matched_docs)
    n_doc_expected = len(expected_set)
    doc_score = n_doc_matched / n_doc_expected if n_doc_expected > 0 else None

    # 4. Faithfulness Channel 2 NLI
    faith_score = sample.get("faithfulness_score")
    faith_verdict = sample.get("faithfulness_verdict")

    return {
        "id": sample.get("id"),
        "type": sample.get("primary_type"),
        "decision_correct": decision_correct,
        "received_decision": received,
        "expected_answerability": expected_answerability,
        "fp_correct": fp_correct,
        "fp_expected": fp_expected,
        "fp_detected": fp_detected,
        "id_score": id_score,
        "ids_matched": matched_ids,
        "ids_missing": [i for i in expected_ids if not has_identifier(answer, i)],
        "n_matched_ids": n_matched,
        "n_expected_ids": n_expected,
        "doc_score": doc_score,
        "doc_matched": list(matched_docs),
        "doc_missing": list(expected_set - cited_set),
        "n_doc_matched": n_doc_matched,
        "n_doc_expected": n_doc_expected,
        "faith_score": faith_score,
        "faith_verdict": faith_verdict,
        "answer_preview": answer[:200],
    }


def main(path: str):
    p = Path(path)
    if not p.exists():
        sys.exit(f"File not found: {path}")
    samples = json.loads(p.read_text(encoding="utf-8"))
    print(f"Loaded {len(samples)} samples")

    evaluations = [evaluate_one(s) for s in samples if "error" not in s]

    # Aggregate global
    n = len(evaluations)
    n_decision_ok = sum(1 for e in evaluations if e["decision_correct"])
    n_fp_ok = sum(1 for e in evaluations if e["fp_correct"])
    id_scores = [e["id_score"] for e in evaluations if e["id_score"] is not None]
    doc_scores = [e["doc_score"] for e in evaluations if e["doc_score"] is not None]
    faith_scores = [e["faith_score"] for e in evaluations if e["faith_score"] is not None and e["faith_score"] > 0]

    print(f"\n=== GLOBAL (n={n}) ===")
    print(f"  decision_correctness   : {n_decision_ok}/{n} = {n_decision_ok / n * 100:.0f}%")
    print(f"  false_premise_handled  : {n_fp_ok}/{n} = {n_fp_ok / n * 100:.0f}%")
    if id_scores:
        avg_id = sum(id_scores) / len(id_scores)
        print(f"  exact_identifier_avg   : {avg_id:.2%} (sur {len(id_scores)} samples avec ≥1 ID attendu)")
    if doc_scores:
        avg_doc = sum(doc_scores) / len(doc_scores)
        print(f"  doc_citation_avg       : {avg_doc:.2%} (sur {len(doc_scores)} samples avec doc_ids attendus)")
    if faith_scores:
        avg_faith = sum(faith_scores) / len(faith_scores)
        print(f"  faithfulness_avg (NLI) : {avg_faith:.2%} (sur {len(faith_scores)} samples avec NLI valide)")

    # Aggregate per type
    print(f"\n=== PAR TYPE ===")
    print(f"{'type':<12} {'n':>3} {'decision':>10} {'fp':>6} {'id_avg':>8} {'doc_avg':>8} {'faith_avg':>10}")
    by_type = defaultdict(list)
    for e in evaluations:
        by_type[e["type"]].append(e)
    for t in ["list", "factual", "temporal", "comparison", "causal"]:
        evs = by_type.get(t, [])
        if not evs:
            continue
        nt = len(evs)
        nd = sum(1 for e in evs if e["decision_correct"])
        nfp = sum(1 for e in evs if e["fp_correct"])
        ids = [e["id_score"] for e in evs if e["id_score"] is not None]
        docs = [e["doc_score"] for e in evs if e["doc_score"] is not None]
        faiths = [e["faith_score"] for e in evs if e["faith_score"] is not None and e["faith_score"] > 0]
        ravg_id = (sum(ids) / len(ids) * 100) if ids else None
        ravg_doc = (sum(docs) / len(docs) * 100) if docs else None
        ravg_faith = (sum(faiths) / len(faiths) * 100) if faiths else None
        print(f"{t:<12} {nt:>3} {f'{nd}/{nt}':>10} {f'{nfp}/{nt}':>6} "
              f"{(f'{ravg_id:.0f}%' if ravg_id is not None else 'n/a'):>8} "
              f"{(f'{ravg_doc:.0f}%' if ravg_doc is not None else 'n/a'):>8} "
              f"{(f'{ravg_faith:.0f}%' if ravg_faith is not None else 'n/a'):>10}")

    # Detail problematic cases
    print(f"\n=== CAS PROBLÉMATIQUES (decision_incorrect ou faith_score=0) ===")
    for e in evaluations:
        problems = []
        if not e["decision_correct"]:
            problems.append(f"decision={e['received_decision']}_attendu={e['expected_answerability']}")
        if e["faith_score"] == 0 and e["received_decision"] == "ANSWER":
            problems.append("faith_score=0")
        if e["id_score"] is not None and e["id_score"] < 0.5 and e["received_decision"] == "ANSWER":
            problems.append(f"ids_missed={e['ids_missing'][:3]}")
        if e["doc_score"] is not None and e["doc_score"] == 0 and e["received_decision"] == "ANSWER":
            problems.append(f"docs_missed={e['doc_missing'][:3]}")
        if problems:
            print(f"  [{e['id']}] {e['type']:<10} : {' | '.join(problems)}")
            print(f"     answer: {e['answer_preview'][:150]}...")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "/app/data/router/v4_stratified_CH46_quality.json"
    main(arg)
