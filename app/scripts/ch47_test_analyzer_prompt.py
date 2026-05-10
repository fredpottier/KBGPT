"""
CH-47.4 alt — Test du nouveau prompt Analyzer sur les 4 questions misclassifiées.

Vérifie que le prompt amélioré classifie correctement hypothetical/conditional/mechanism
en `causal` (au lieu de `factual` qui activait le V4 path et menait à ABSTAIN).
"""
from __future__ import annotations
import sys
import time

sys.path.insert(0, "/app/src")

from knowbase.facts_first.question_analyzer import get_question_analyzer, reset_question_analyzer

QUESTIONS = [
    # 4 questions classées "factual" → ABSTAIN dans le bench (avec ancien prompt)
    ("q_52", "hypothetical→causal_attendu",
     "Si un État membre voulait restreindre une autorisation générale Union, quel mécanisme du règlement 2021/821 le permettrait ?"),
    ("q_54", "hypothetical→causal_attendu",
     "Si un exportateur voulait contester une décision de refus d'autorisation au titre du 2021/821, quel recours aurait-il ?"),
    ("q_51", "hypothetical→causal_attendu",
     "Si l'EASA publiait demain CS-25 Amendment 29 avec une énergie d'impact à 30 J, quelle valeur s'appliquerait ?"),
    ("q_117", "conditional→causal_attendu",
     "Si plus d'informations sont nécessaires pour évaluer une transaction, les autorités compétentes peuvent-elles prolonger le délai d'évaluation ?"),
    # Cas multi-domain (test domain-agnostic)
    ("test_med", "causal_attendu (médical)",
     "Si un patient diabétique présente une infection postopératoire, quel protocole d'antibiothérapie est recommandé ?"),
    ("test_finance", "causal_attendu (finance)",
     "Si une banque centrale veut juguler l'inflation, quel mécanisme de politique monétaire utilisera-t-elle ?"),
    # Cas factual qui doit RESTER factual
    ("test_factual", "factual_attendu",
     "Quelle est la date de publication officielle du règlement 2021/821 ?"),
    ("test_factual2", "factual_attendu (médical)",
     "Quelle est la dose maximale quotidienne d'ibuprofène pour un adulte ?"),
]


def main():
    reset_question_analyzer()  # force re-load avec nouveau prompt
    analyzer = get_question_analyzer()
    print(f"Analyzer ready (model_override={analyzer.model_override})")
    print()
    print(f"{'qid':<14} {'expected':<32} {'primary_type':<14} {'conf':>6} {'secondary':<14} {'wall ms':>8}")
    print("-" * 100)

    n_correct = 0
    n_total = 0
    for qid, expected, question in QUESTIONS:
        t0 = time.time()
        try:
            res = analyzer.analyze(question)
        except Exception as exc:
            print(f"{qid:<14} ERROR: {exc}")
            continue
        wall = int((time.time() - t0) * 1000)
        primary = res.primary_type
        conf = res.primary_confidence
        secondary = res.secondary_type or "-"
        print(f"{qid:<14} {expected:<32} {primary:<14} {conf:>6.2f} {secondary:<14} {wall:>7}ms")
        # Check correctness
        n_total += 1
        if "factual" in expected and primary == "factual":
            n_correct += 1
        elif "causal" in expected and primary == "causal":
            n_correct += 1

    print()
    print(f"=== Score: {n_correct}/{n_total} correct ({n_correct / max(n_total, 1) * 100:.0f}%) ===")


if __name__ == "__main__":
    main()
