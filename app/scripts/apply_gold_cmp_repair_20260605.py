#!/usr/bin/env python
"""
apply_gold_cmp_repair_20260605.py — Répare les 3 comparisons semi-désancrées
(CMP_0003/0007/0011) en les reciblant sur des paires FAA/EASA VÉRIFIÉES dans le
KG staged (les deux côtés présents, claims verbatim contrôlés le 05/06/2026).

Problème : leurs paires gold d'origine avaient UN côté disparu de l'extraction
staged + une question trop vague (la paire attendue était indevinable parmi des
dizaines de contrastes valides) → le juge n'était pas interprétable.

Réparation : question PRÉCISÉE sur l'aspect de la paire + gold ré-ancré sur les
claims réels. Type comparison conservé, champ `revision` daté.

    python app/scripts/apply_gold_cmp_repair_20260605.py
"""

import json

REV_DATE = "2026-06-05"

EDITS = {
    "AERO_CMP_0003": {
        "question": "What is the difference between the seat belt integrity issue addressed by FAA AC 25.562-1B and the seatbelt condition described in EASA ETSO-C127b?",
        "answer": "FAA AC 25.562-1B requires that the seat belt not be cut or torn by features of the seat or the belt adjuster mechanism, while EASA ETSO-C127b describes seatbelt misalignment — a condition where the seatbelt and/or shackle is positioned to give the impression that the belt has been properly tightened when in fact there is slack in the system or the shackle will not carry the force generated in an emergency landing or turbulence.",
        "exact_identifiers": ["AC 25.562-1B", "ETSO-C127b"],
        "supporting_doc_ids": ["AC_25.562-1B_e14eda4f", "ETSO-C127b_8c0c076e"],
        "reason": "paire gold d'origine semi-désancrée (côté EASA « test for misalignment by positioning the seat in taxi/take-off/landing » absent du staged) + question trop vague ; reciblée sur une paire FAA/EASA vérifiée des deux côtés (claims verbatim contrôlés)",
    },
    "AERO_CMP_0007": {
        "question": "How do FAA regulations and EASA's NPA 2013-20 differ in their view of seat occupant protection during emergency landings?",
        "answer": "The FAA regulation (14 CFR Part 25) requires the airplane to be designed to protect each occupant under emergency landing conditions on land or water, while EASA's NPA 2013-20 found that in survivable accident impacts the level of protection of passenger and cabin crew seats is not optimal on some large aeroplanes.",
        "exact_identifiers": ["NPA 2013-20"],
        "supporting_doc_ids": ["CFR_part25_seats_extract_3abc9981", "NPA_2013-20_seat_crashworthiness_fdd93d4d"],
        "reason": "paire gold d'origine semi-désancrée (côté FAA « rupture of hydraulic lines » absent du staged) + question trop vague ; reciblée sur une paire vérifiée (CFR Part 25 / NPA 2013-20)",
    },
    "AERO_CMP_0011": {
        "question": "How do FAA and EASA guidance differ in their concerns about underseat baggage in seat design?",
        "answer": "FAA guidance (AC 23.562-1) requires the seat to contain adequate design features to preclude underseat baggage from restricting the seat displacement during energy absorption, while EASA (ETSO-C127b) requires that the life preserver retention device not allow the life preserver to come free during turbulence and the stowage and removal of underseat baggage.",
        "exact_identifiers": ["AC 23.562-1", "ETSO-C127b"],
        "supporting_doc_ids": ["AC_23.562-1_0d9f78dc", "ETSO-C127b_8c0c076e"],
        "reason": "paire gold d'origine semi-désancrée (côté FAA « affect occupant positioning » absent ; les candidats restants étaient FAA-vs-FAA) + question trop vague ; reciblée sur le topic « underseat baggage » avec paire FAA/EASA vérifiée",
    },
}


def patch(path: str) -> int:
    items = json.load(open(path, encoding="utf-8"))
    n = 0
    for q in items:
        e = EDITS.get(q.get("id"))
        if not e:
            continue
        gt = q["ground_truth"]
        q["revision"] = {
            "date": REV_DATE,
            "reason": e["reason"],
            "previous_question": q.get("question"),
            "previous_answer": gt.get("answer"),
        }
        q["question"] = e["question"]
        gt["answer"] = e["answer"]
        gt["exact_identifiers"] = e["exact_identifiers"]
        gt["supporting_doc_ids"] = e["supporting_doc_ids"]
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    return n


if __name__ == "__main__":
    for p in (
        "benchmark/questions/gold_set_aero_150q.json",
        "benchmark/questions/gold_set_aero_50q.json",
    ):
        print(p, "->", patch(p), "questions reciblées")
