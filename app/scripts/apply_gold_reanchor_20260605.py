#!/usr/bin/env python
"""
apply_gold_reanchor_20260605.py — Ré-ancrage du gold-set aéro sur le wording staged.

Suite du triage des 56 questions answerable à juge ≤0.5 du run_20260604_223733 :
chaque modification ci-dessous a été vérifiée individuellement contre le KG
staged (recherche substring sur Claim.text, tenant=default).

3 familles de modifications (champ `revision` daté, pattern eb0113b) :
  RELABEL   — l'ancre factuelle a disparu des claims staged → unanswerable
  RETARGET  — un claim staged verbatim voisin existe → question/réponse réécrites dessus
  REANCHOR  — la réponse gold est réécrite sur le wording du claim staged réel

NON touché (vrais échecs système, ancres vérifiées présentes) :
  FACT_0006/0019/0024, LIFE_0017, MH_0002/0003/0013, CMP_0012/0013/0017, FP_0002/0008/0012
NON touché (décision à prendre avec Fred — paires comparison semi-désancrées) :
  CMP_0003 (côté EASA absent), CMP_0007 (côté FAA absent), CMP_0011 (côté FAA absent)

    python app/scripts/apply_gold_reanchor_20260605.py
"""

import json

REV_DATE = "2026-06-05"

# --- RELABEL answerable → unanswerable (ancre absente du KG staged) ---
RELABELS = {
    "AERO_FACT_0014": "ancre absente du KG staged : aucun claim AS6316 'all subsections of Section 3 apply unless otherwise specified'",
    "AERO_MH_0007": "ancre absente du KG staged : meme ancre AS6316 Section 3 que AERO_FACT_0014",
    "AERO_FACT_0026": "ancre absente du KG staged : claim 'memorandum / Sec. 25.785(c)(2) of Amendment 25-32' non extrait (question contenait aussi l'OCR 'Amendment 2532')",
    "AERO_FACT_0042": "ancre absente du KG staged : le memo PSAIR100-9/8/2003 n'apparait dans aucun claim (perte de couverture staged a tracer)",
    "AERO_MH_0010": "ancre absente du KG staged : meme ancre PSAIR100-9/8/2003 que AERO_FACT_0042",
    "AERO_LIFE_0001": "ancre absente du KG staged : aucun claim 'longitudinal heart path analysis modifies...' (les claims heart path restants ne decrivent pas le processus d'ajustement)",
    "AERO_LIFE_0005": "ancre absente du KG staged : aucun claim 'moved the test criteria to a new Appendix J'",
    "AERO_LIFE_0006": "ancre absente du KG staged : aucun claim 'paragraph 5e(5)(d) ... deleted' (seul 'New paragraph 5e(5)(d)1 includes...' subsiste)",
    "AERO_LIFE_0008": "ancre absente du KG staged : aucun claim 'paragraph (c) was deleted'",
    "AERO_LIFE_0013": "ancre absente du KG staged : aucun claim 'redesignated as 5e(5)(d)2/3'",
    "AERO_LIST_0014": "ancre absente du KG staged : aucun claim 'limits of wear and damage ... warrant replacement'",
}

# --- RETARGET / REANCHOR (claims staged verbatim vérifiés) ---
EDITS = {
    "AERO_LIFE_0003": {
        "question": "What is the status of Section 25.791 before Amendment 25-32?",
        "answer": "Section 25.791 did not exist prior to Amendment 25-32.",
        "exact_identifiers": ["Amendment 25-32"],
        "reason": "retarget 25.789→25.791 : le claim staged verbatim est 'Section 25.791 did not exist prior to Amendment 25-32.' (le 25.789 du gold legacy n'a pas d'equivalent staged)",
    },
    "AERO_LIFE_0015": {
        "question": "What new requirement was added concerning cabin areas likely to become wet in service?",
        "answer": "A new requirement that areas likely to become wet in service have slip resistant floors (§ 25.793).",
        "exact_identifiers": ["§ 25.793"],
        "reason": "retarget : 'Section 25.793 did not exist' absent du staged ; re-ancre sur le claim verbatim 'Added a new requirement that areas likely to become wet in service have slip resistant floors (§ 25.793).'",
    },
    "AERO_FACT_0037": {
        "question": "Which UL standard is mentioned for testing the sharpness of edges on equipment, and what are its edition and revision dates?",
        "answer": "UL 1439, Standard for Tests for Sharpness of Edges on Equipment, Edition 4, February 26, 1998, with revisions through 6/1/2004.",
        "exact_identifiers": ["1998", "2004"],
        "reason": "reformulation : la notion de 'third standard' venait du wording legacy ; le claim staged enumere autrement ('either of the standards listed in NASA-STD-3000...') mais porte UL 1439 verbatim",
    },
    "AERO_FACT_0023": {
        "question": "According to the HIC computation procedure described in the regulation, what is the HIC value defined as?",
        "answer": "The maximum value of the set of computations obtained from the procedure is the HIC.",
        "exact_identifiers": ["HIC"],
        "reason": "desambiguisation : question identique a AERO_FACT_0045 ('What does the document specify regarding HIC?') avec un gold different ; scope precise sur l'ancre verifiee 'The maximum value of the set of computations obtained from this procedure is the HIC.'",
    },
    "AERO_FACT_0045": {
        "question": "What is evaluated to generate the baseline certification tests?",
        "answer": "The primary structural load path, and other components that influence occupant injury criteria, are evaluated to generate the baseline certification tests.",
        "exact_identifiers": [],
        "reason": "desambiguisation (doublon de AERO_FACT_0023) + re-ancrage sur les claims staged verbatim 'The primary structural load path is evaluated to generate the baseline certification tests.' / 'Other components that influence occupant injury criteria...'",
    },
    "AERO_LIST_0006": {
        "answer": "An assessment is required: any changes to common components such as seatbelts, cushions, IFE system hardware, or seat back tray tables require an assessment.",
        "reason": "re-ancrage : le but de l'assessment ('verify structural integrity and occupant injury performance') a ete perdu par la decomposition staged ; le claim restant dit seulement 'require an assessment' (perte de couverture a tracer)",
    },
    "AERO_LIST_0008": {
        "answer": "An assessment is required: any changes to common components such as seatbelts, cushions, IFE system hardware, or seat back tray tables require an assessment.",
        "reason": "re-ancrage : meme ancre que AERO_LIST_0006 (claim staged 'require an assessment' sans le but de l'assessment)",
    },
    "AERO_LIST_0015": {
        "answer": "An assessment is required: any changes to common components such as seatbelts, cushions, IFE system hardware, or seat back tray tables require an assessment.",
        "reason": "re-ancrage : meme ancre que AERO_LIST_0006",
    },
}


def patch(path: str) -> int:
    items = json.load(open(path, encoding="utf-8"))
    assert isinstance(items, list)
    n = 0
    for q in items:
        qid = q.get("id")
        if qid in RELABELS:
            gt = q["ground_truth"]
            q["revision"] = {
                "date": REV_DATE,
                "reason": RELABELS[qid],
                "previous_answerability": gt.get("answerability"),
            }
            gt["answerability"] = "unanswerable"
            n += 1
        elif qid in EDITS:
            e = EDITS[qid]
            gt = q["ground_truth"]
            q["revision"] = {
                "date": REV_DATE,
                "reason": e["reason"],
                "previous_question": q.get("question") if "question" in e else None,
                "previous_answer": gt.get("answer"),
            }
            if "question" in e:
                q["question"] = e["question"]
            gt["answer"] = e["answer"]
            if "exact_identifiers" in e:
                gt["exact_identifiers"] = e["exact_identifiers"]
            n += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    return n


if __name__ == "__main__":
    for p in (
        "benchmark/questions/gold_set_aero_150q.json",
        "benchmark/questions/gold_set_aero_50q.json",
    ):
        print(p, "->", patch(p), "questions modifiees")
