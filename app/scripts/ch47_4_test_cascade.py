"""
CH-47.4 — Test isolé de l'AnalyzerCascade DeBERTa S2.

Vérifie sur 8 questions (les 3 ABSTAIN du bench + 5 questions multi-types) si la cascade
DeBERTa rattrape les misclassifications de l'Analyzer LLM.
"""
from __future__ import annotations
import sys
import time

sys.path.insert(0, "/app/src")

from knowbase.facts_first.analyzer_cascade import get_analyzer_cascade

TEST_QUESTIONS = [
    # 3 hypothetical qui étaient ABSTAIN (factual misclass)
    ("q_52", "hypothetical (attendu)", "Si un État membre voulait restreindre une autorisation générale Union, quel mécanisme du règlement 2021/821 le permettrait ?"),
    ("q_54", "hypothetical (attendu)", "Si un exportateur voulait contester une décision de refus d'autorisation au titre du 2021/821, quel recours aurait-il ?"),
    ("q_51", "hypothetical (attendu)", "Si l'EASA publiait demain CS-25 Amendment 29 avec une énergie d'impact à 30 J, quelle valeur s'appliquerait ?"),
    # 1 conditional
    ("q_117", "conditional/causal (attendu)", "Si plus d'informations sont nécessaires pour évaluer une transaction, les autorités compétentes peuvent-elles prolonger le délai d'évaluation ?"),
    # 1 multi_hop
    ("q_88", "multi_hop/factual (attendu)", "Quelle est la valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre, et pourquoi une valeur plus faible apparaît-elle ?"),
    # 2 questions multi-domaines (test domain-agnostic)
    ("test_med", "causal (attendu, médical)", "Pourquoi les inhibiteurs ACE sont-ils contre-indiqués pendant la grossesse ?"),
    ("test_finance", "causal (attendu, finance)", "Pourquoi la Banque Centrale Européenne ajuste-t-elle ses taux directeurs en fonction de l'inflation ?"),
    # 1 factual qui doit RESTER factual
    ("test_factual", "factual (attendu)", "Quelle est la capitale de la France ?"),
]


def main():
    cascade = get_analyzer_cascade()
    print(f"Cascade ready. Threshold: {cascade.confidence_threshold}")
    print(f"Promotable types: {cascade.promotable_types}")
    print()
    print(f"{'qid':<14} {'expected':<32} {'LLM (simul)':<10} {'DeBERTa top1':<14} {'conf':>6} {'top2':<14} {'conf':>6} {'PROMOTED':<10}")
    print("-" * 120)

    for qid, expected, question in TEST_QUESTIONS:
        # Simuler ce que l'Analyzer LLM dit (= "factual" pour le worst case ABSTAIN)
        # Pour le test, on suppose que le LLM dit "factual" sur tout pour voir si DeBERTa promeut
        for simulated_llm_type in ["factual"]:
            t0 = time.time()
            res = cascade.cascade(question, simulated_llm_type)
            wall = int((time.time() - t0) * 1000)
            promoted_flag = "✓ PROMOTED" if res.promoted else "  kept"
            print(f"{qid:<14} {expected:<32} {simulated_llm_type:<10} "
                  f"{res.deberta_top1:<14} {res.deberta_confidence:>6.3f} "
                  f"{res.deberta_top2:<14} {res.deberta_top2_confidence:>6.3f} "
                  f"{promoted_flag:<10} ({wall}ms)")
    print()
    print("Note: the cascade only promotes IF (LLM=factual) AND (DeBERTa top1 in {causal/comparison/temporal})")
    print("      AND (DeBERTa confidence ≥ 0.85). Otherwise LLM type is kept.")


if __name__ == "__main__":
    main()
