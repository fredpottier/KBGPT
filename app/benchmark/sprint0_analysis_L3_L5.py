#!/usr/bin/env python3
"""Sprint 0 — Livrables 3 et 5 : Stratification refus + false_answer_rate

Livrable 3 : Stratifie les false_idk par score Qdrant max du chunk le plus proche
Livrable 5 : Calcule le false_answer_rate formel
"""

import json
import statistics

BASE = "benchmark/results/20260324_phaseC"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def analyze_system(system_name, results_path, judge_path):
    """Analyse un systeme (OSMOSIS ou RAG)."""
    results = load(results_path)
    judge = load(judge_path)

    # Index judgments par question_id
    jmap = {j["question_id"]: j.get("judgment", {}) for j in judge["judgments"]}

    # Collecter les donnees
    rows = []
    for r in results["results"]:
        qid = r["question_id"]
        j = jmap.get(qid, {})

        # Scores Qdrant des chunks
        chunks = r["response"].get("results", r["response"].get("chunks", []))
        scores = [c.get("score", 0) for c in chunks if c.get("score")]
        max_score = max(scores) if scores else 0
        avg_score = statistics.mean(scores) if scores else 0
        min_score = min(scores) if scores else 0

        # Verdict du juge
        says_idk = j.get("says_idk_when_info_exists", False)
        answers_correctly = j.get("answers_correctly", False)
        factual = j.get("factual_correctness", 0)
        relevant = j.get("answer_relevant", False)

        # Classification du resultat
        answer = r["response"].get("answer", "")
        answer_len = len(answer)

        # Detecter si la reponse est un refus
        idk_markers = [
            "ne sais pas", "pas disponible", "not available", "cannot find",
            "ne dispose pas", "aucune information", "no information",
            "not found", "pas de reponse", "je ne peux pas",
            "information not available", "pas en mesure"
        ]
        is_refusal = any(m in answer.lower() for m in idk_markers) or answer_len < 50

        rows.append({
            "qid": qid,
            "max_score": max_score,
            "avg_score": avg_score,
            "min_score": min_score,
            "n_chunks": len(chunks),
            "says_idk": says_idk,
            "answers_correctly": answers_correctly,
            "factual": factual,
            "relevant": relevant,
            "is_refusal": is_refusal,
            "answer_len": answer_len,
        })

    return rows


def livrable_3(rows, system_name):
    """Stratification des refus par score Qdrant."""
    print(f"\n{'='*60}")
    print(f"LIVRABLE 3 — Stratification refus [{system_name}]")
    print(f"{'='*60}")

    # Refus = says_idk OU is_refusal
    refusals = [r for r in rows if r["says_idk"] or r["is_refusal"]]
    non_refusals = [r for r in rows if not (r["says_idk"] or r["is_refusal"])]

    print(f"\nTotal questions: {len(rows)}")
    print(f"Refus detectes: {len(refusals)} ({100*len(refusals)/len(rows):.1f}%)")
    print(f"Reponses: {len(non_refusals)} ({100*len(non_refusals)/len(rows):.1f}%)")

    # Stratifier par score Qdrant
    buckets = {
        "score >= 0.85 (excellent retrieval)": [],
        "0.75 <= score < 0.85 (bon retrieval)": [],
        "0.65 <= score < 0.75 (moyen retrieval)": [],
        "score < 0.65 (mauvais retrieval)": [],
    }

    for r in refusals:
        s = r["max_score"]
        if s >= 0.85:
            buckets["score >= 0.85 (excellent retrieval)"].append(r)
        elif s >= 0.75:
            buckets["0.75 <= score < 0.85 (bon retrieval)"].append(r)
        elif s >= 0.65:
            buckets["0.65 <= score < 0.75 (moyen retrieval)"].append(r)
        else:
            buckets["score < 0.65 (mauvais retrieval)"].append(r)

    print(f"\nStratification des {len(refusals)} refus par score Qdrant max:")
    for label, items in buckets.items():
        pct = 100 * len(items) / max(len(refusals), 1)
        avg = statistics.mean([r["max_score"] for r in items]) if items else 0
        print(f"  {label}: {len(items)} ({pct:.0f}%) — score moyen: {avg:.3f}")

    # Diagnostic
    prompt_problem = len(buckets["score >= 0.85 (excellent retrieval)"]) + len(buckets["0.75 <= score < 0.85 (bon retrieval)"])
    retrieval_problem = len(buckets["0.65 <= score < 0.75 (moyen retrieval)"]) + len(buckets["score < 0.65 (mauvais retrieval)"])
    print(f"\n  => PROMPT problem (score >= 0.75): {prompt_problem} ({100*prompt_problem/max(len(refusals),1):.0f}%)")
    print(f"  => RETRIEVAL problem (score < 0.75): {retrieval_problem} ({100*retrieval_problem/max(len(refusals),1):.0f}%)")

    # Statistiques score pour refusals vs non-refusals
    if refusals and non_refusals:
        ref_scores = [r["max_score"] for r in refusals]
        nref_scores = [r["max_score"] for r in non_refusals]
        print(f"\n  Score max moyen — refusals: {statistics.mean(ref_scores):.3f}, reponses: {statistics.mean(nref_scores):.3f}")
        print(f"  Score max median — refusals: {statistics.median(ref_scores):.3f}, reponses: {statistics.median(nref_scores):.3f}")

    return {
        "total": len(rows),
        "refusals": len(refusals),
        "refusal_rate": len(refusals) / len(rows),
        "prompt_problem": prompt_problem,
        "retrieval_problem": retrieval_problem,
        "prompt_pct": prompt_problem / max(len(refusals), 1),
        "retrieval_pct": retrieval_problem / max(len(refusals), 1),
        "avg_score_refusals": statistics.mean([r["max_score"] for r in refusals]) if refusals else 0,
        "avg_score_responses": statistics.mean([r["max_score"] for r in non_refusals]) if non_refusals else 0,
    }


def livrable_5(rows, system_name):
    """Calcul formel du false_answer_rate."""
    print(f"\n{'='*60}")
    print(f"LIVRABLE 5 — false_answer_rate [{system_name}]")
    print(f"{'='*60}")

    total = len(rows)

    # Categories mutuellement exclusives
    correct = [r for r in rows if r["answers_correctly"]]
    false_idk = [r for r in rows if r["says_idk"]]
    # false_answer = repond (pas IDK) mais incorrectement
    false_answer = [r for r in rows if not r["says_idk"] and not r["answers_correctly"] and r["relevant"]]
    # irrelevant = pas IDK, pas correct, pas relevant
    irrelevant = [r for r in rows if not r["says_idk"] and not r["answers_correctly"] and not r["relevant"]]

    print(f"\nTotal: {total}")
    print(f"  Correct (answers_correctly=true): {len(correct)} ({100*len(correct)/total:.1f}%)")
    print(f"  False IDK (says_idk=true): {len(false_idk)} ({100*len(false_idk)/total:.1f}%)")
    print(f"  False Answer (repond mais incorrect, relevant): {len(false_answer)} ({100*len(false_answer)/total:.1f}%)")
    print(f"  Irrelevant (repond mais hors-sujet): {len(irrelevant)} ({100*len(irrelevant)/total:.1f}%)")
    uncategorized = total - len(correct) - len(false_idk) - len(false_answer) - len(irrelevant)
    if uncategorized:
        print(f"  Non categorise: {uncategorized}")

    # Score composite
    print(f"\n  false_answer_rate = {100*len(false_answer)/total:.1f}%")
    print(f"  false_idk_rate = {100*len(false_idk)/total:.1f}%")
    print(f"  total_error_rate = {100*(len(false_answer)+len(false_idk))/total:.1f}%")

    # Factual moyen par categorie
    for label, items in [("Correct", correct), ("False IDK", false_idk), ("False Answer", false_answer), ("Irrelevant", irrelevant)]:
        if items:
            avg_f = statistics.mean([r["factual"] for r in items])
            avg_s = statistics.mean([r["max_score"] for r in items])
            print(f"  {label}: factual_avg={avg_f:.3f}, qdrant_score_avg={avg_s:.3f}")

    return {
        "total": total,
        "correct": len(correct),
        "correct_rate": len(correct) / total,
        "false_idk": len(false_idk),
        "false_idk_rate": len(false_idk) / total,
        "false_answer": len(false_answer),
        "false_answer_rate": len(false_answer) / total,
        "irrelevant": len(irrelevant),
        "irrelevant_rate": len(irrelevant) / total,
        "total_error_rate": (len(false_answer) + len(false_idk)) / total,
    }


def main():
    results = {}

    # OSMOSIS T1 human (100 questions — le set principal)
    osm_rows = analyze_system(
        "OSMOSIS",
        f"{BASE}/osmosis_T1_human.json",
        f"{BASE}/judge_osmosis_T1_human.json",
    )
    results["osmosis_L3"] = livrable_3(osm_rows, "OSMOSIS T1 Human")
    results["osmosis_L5"] = livrable_5(osm_rows, "OSMOSIS T1 Human")

    # RAG T1 human (100 questions — comparaison)
    rag_rows = analyze_system(
        "RAG",
        f"{BASE}/rag_claim_T1_human.json",
        f"{BASE}/judge_rag_claim_T1_human.json",
    )
    results["rag_L3"] = livrable_3(rag_rows, "RAG T1 Human")
    results["rag_L5"] = livrable_5(rag_rows, "RAG T1 Human")

    # OSMOSIS T1 KG (30 questions)
    osm_kg_rows = analyze_system(
        "OSMOSIS KG",
        f"{BASE}/osmosis_T1_kg.json",
        f"{BASE}/judge_osmosis_T1_kg.json",
    )
    results["osmosis_kg_L3"] = livrable_3(osm_kg_rows, "OSMOSIS T1 KG")
    results["osmosis_kg_L5"] = livrable_5(osm_kg_rows, "OSMOSIS T1 KG")

    # RAG T1 KG (30 questions)
    rag_kg_rows = analyze_system(
        "RAG KG",
        f"{BASE}/rag_claim_T1_kg.json",
        f"{BASE}/judge_rag_claim_T1_kg.json",
    )
    results["rag_kg_L3"] = livrable_3(rag_kg_rows, "RAG T1 KG")
    results["rag_kg_L5"] = livrable_5(rag_kg_rows, "RAG T1 KG")

    # Sauvegarder
    with open("benchmark/results/sprint0_L3_L5_analysis.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n\nResultats sauves dans benchmark/results/sprint0_L3_L5_analysis.json")


if __name__ == "__main__":
    main()
