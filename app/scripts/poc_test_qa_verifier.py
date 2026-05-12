"""Test rapide du QAAlignmentVerifier sur 6 cas représentatifs."""
from knowbase.runtime_v4_poc.qa_alignment_verifier import QAAlignmentVerifier

CASES = [
    # (label, question, answer, expected_decision)
    (
        "ALIGNED simple",
        "Quel règlement a remplacé le 428/2009 ?",
        "Le règlement (UE) 2021/821 a remplacé le règlement 428/2009.",
        "ALIGNED",
    ),
    (
        "MISALIGNED off-topic — UNA_006",
        "Quelle est la position de la Russie sur le règlement 2021/821 ?",
        "Regulation (EU) 2021/821 was adopted on 11.6.2021.",
        "MISALIGNED",
    ),
    (
        "MISALIGNED hors-cible — SET_009",
        "Liste les références EU externes citées dans 2021/821.",
        "Australia Group, MTCR, Nuclear Suppliers Group, Wassenaar Arrangement, OPCW.",
        "MISALIGNED",
    ),
    (
        "ABSTAIN_OK",
        "Combien d'autorisations d'export ont été délivrées par la France en 2023 ?",
        "La réponse à votre question n'a pas été trouvée dans les documents disponibles.",
        "ABSTAIN_OK",
    ),
    (
        "ALIGNED multi-hop substantiel — MH_007",
        "Un avocat doit défendre exportateur 2018 sur 428/2009. En 2024, contestable ?",
        "L'exportation a été faite avant le 9 septembre 2021, dispositions continuent de s'appliquer.",
        "ALIGNED",
    ),
    (
        "MISALIGNED extraction brute — COND_007",
        "Si un dossier de certification CS-25 a été ouvert le 1er février 2024, quelle version d'amdt est verrouillée comme certification basis ?",
        "CS-25 has amendment Amdt No: 25/26. CS-25 has amendment Amdt No: 25/24.",
        "MISALIGNED",
    ),
]


def main() -> None:
    verifier = QAAlignmentVerifier()
    print(f"Model: {verifier.model}\n")

    n_correct = 0
    for label, q, a, expected in CASES:
        r = verifier.verify(q, a)
        ok = "✓" if r.decision == expected else "✗"
        if r.decision == expected:
            n_correct += 1
        print(f"{ok} [{label}]")
        print(f"  Q: {q[:120]}")
        print(f"  A: {a[:120]}")
        print(f"  → {r.decision} (conf={r.confidence:.2f}, {r.latency_ms}ms) | expected={expected}")
        print(f"    reason: {r.reason}")
        print()

    print(f"=== Score: {n_correct}/{len(CASES)} ===")


if __name__ == "__main__":
    main()
