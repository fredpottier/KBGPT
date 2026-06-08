"""build_gold_differential.py — Construit le gold-set DIFFÉRENCIANT KG vs RAG (#462).

Questions ciblant ce qu'un RAG seul rate structurellement : contradictions
inter-sources, lignée/version en vigueur, bitemporel, comparaison inter-docs,
fait éclaté, faux présupposé. Chaque question est ancrée sur du contenu RÉEL du
KG aéro. Le script VÉRIFIE que les ancres (valeurs/docs) existent vraiment dans
le tenant `aero` avant d'écrire le JSON (anti-hallucination du gold).

Usage : docker exec -e PYTHONIOENCODING=utf-8 knowbase-app python //app/scripts/build_gold_differential.py
Sortie : benchmark/questions/gold_set_aero_differential.json
"""
from __future__ import annotations
import json
from pathlib import Path
from knowbase.common.clients.neo4j_client import get_neo4j_client

TENANT = "aero"
OUT = Path("benchmark/questions/gold_set_aero_differential.json")

# Chaque entrée : (id, type, question, answer, exact_identifiers, anchors_to_verify)
# anchors_to_verify = sous-chaînes qui DOIVENT exister dans un claim aero (preuve).
Q = [
    # ───────── COMPARISON / CONTRADICTION inter-sources ─────────
    ("DIFF_CMP_01", "comparison",
     "Do the FAA and EASA specify the same maximum allowable average burn length for self-extinguishing seat materials?",
     "No — they diverge. FAA AC 25-17 specifies 3 inches and CFR Part 25 specifies 8 inches, while EASA ETSO-C127c allows 6 inches.",
     ["3 inches", "6 inches", "8 inches"], ["may not exceed 3 inches", "may not exceed 6 inches", "may not exceed 8 inches"]),
    ("DIFF_CMP_02", "comparison",
     "Is the peak floor deceleration timing requirement identical between the FAA (CFR Part 25) and the EASA NPA 2013-20?",
     "No. CFR Part 25 requires peak floor deceleration within 0.09 seconds; EASA NPA 2013-20 requires it within 0.08 seconds.",
     ["0.08", "0.09"], ["0.08 seconds", "0.09 seconds"]),
    ("DIFF_CMP_03", "comparison",
     "Are the specimen conditioning relative-humidity requirements the same in CFR Part 25 and in AC 25-17A?",
     "No. CFR Part 25 specifies 55% relative humidity, whereas AC 25-17 / AC 25-17A specify 50%.",
     ["55%", "50%"], ["55%", "50 percent"]),
    ("DIFF_CMP_04", "comparison",
     "How did AC 25-17A change the acceptable average burn rate compared with AC 25-17 (1991)?",
     "AC 25-17 (1991) required the average burn rate not to exceed 4 inches per minute; AC 25-17A raised it to 20 inches per minute.",
     ["4 inches", "20 inches"], ["four inches per minute", "20-inches per minute"]),
    ("DIFF_CMP_05", "comparison",
     "Do AC 25-17 (1991) and AC 25-17A specify the same burner nozzle flow rate?",
     "No. AC 25-17 (1991): about 2.25 gallons/hour; AC 25-17A: 6.0 gal/hr.",
     ["2.25", "6.0"], ["2.25 gallons/hour", "6.0"]),
    ("DIFF_CMP_06", "comparison",
     "Is the calorimeter placement distance the same in AC 25-17A and in CFR Part 25?",
     "No. AC 25-17A places the calorimeter at 8 inches (203 mm); CFR Part 25 at 4 inches (102 mm).",
     ["8-inches", "4"], ["8-inches (203 mm)", "4 ± 1/8 inches"]),
    ("DIFF_CMP_07", "comparison",
     "Across the AC references, is the impact pulse produced as a deceleration or as an acceleration?",
     "The descriptions differ: AC 23.562-1 describes it as a deceleration; AC 25.562-1A describes an acceleration sled (controlled acceleration).",
     ["deceleration", "acceleration"], ["impact pulse as a deceleration", "controlled accel"]),
    ("DIFF_CMP_08", "comparison",
     "What distinguishes ETSO-C127b from ETSO-C127a?",
     "ETSO-C127b supersedes ETSO-C127a; it carries the updated MPS/elective requirements relative to ETSO-C127a.",
     ["ETSO-C127b", "ETSO-C127a"], ["ETSO-C127"]),

    # ───────── LIFECYCLE / LIGNÉE — version en vigueur ─────────
    ("DIFF_LIN_01", "lifecycle",
     "Is AC 21-25A still the applicable advisory circular today?",
     "No. AC 21-25A has been superseded by AC 21-25B (lineage: AC 21-25B replaced AC 21-25A, which replaced AC 21-25).",
     ["AC 21-25B"], ["21-25"]),
    ("DIFF_LIN_02", "lifecycle",
     "What is the current in-force revision of AC 25.785-1?",
     "AC 25.785-1B — it superseded AC 25.785-1A, which superseded AC 25.785-1.",
     ["AC 25.785-1B"], ["25.785-1"]),
    ("DIFF_LIN_03", "lifecycle",
     "Is the 1991 edition of AC 25-17 still valid for seat fire-protection compliance?",
     "No. The 1991 edition has been cancelled and superseded by AC 25-17A.",
     ["AC 25-17A"], ["25-17"]),
    ("DIFF_LIN_04", "lifecycle",
     "How many successive revisions has AC 21-25 had, and which one governs?",
     "Three: AC 21-25 -> AC 21-25A -> AC 21-25B; AC 21-25B governs.",
     ["AC 21-25B"], ["21-25"]),
    ("DIFF_LIN_05", "lifecycle",
     "Has ETSO-C127a been replaced by a later revision?",
     "Yes, by ETSO-C127b.",
     ["ETSO-C127b"], ["ETSO-C127"]),
    ("DIFF_LIN_06", "lifecycle",
     "Which document supersedes AC 20-146?",
     "AC 20-146A (AC 20-146 is cancelled).",
     ["AC 20-146A"], ["20-146"]),

    # ───────── BITEMPOREL — à la date T ─────────
    ("DIFF_TMP_01", "lifecycle",
     "Which FAA advisory circular governed seat fire-protection compliance in 1995, before AC 25-17A existed?",
     "AC 25-17 (the 1991 edition), effective from 1991; AC 25-17A only became effective in 2009.",
     ["AC 25-17", "1991"], ["25-17"]),
    ("DIFF_TMP_02", "lifecycle",
     "Did Appendix J of the seat dynamic-test guidance exist in 2005?",
     "No. Appendix J did not exist prior to Amendment 25-72 (introduced with AC 25-17A, effective 2009).",
     ["25-72"], ["Appendix J did not exist prior to Amendment 25-72"]),
    ("DIFF_TMP_03", "lifecycle",
     "Was Section 25.791 in force before Amendment 25-32?",
     "No. Section 25.791 did not exist prior to Amendment 25-32.",
     ["25.791", "25-32"], ["25.791 did not exist prior to Amendment 25-32"]),
    ("DIFF_TMP_04", "lifecycle",
     "Which crashworthiness guidance applied to seats in the mid-1980s?",
     "AC 23.562-1, effective March 1983.",
     ["AC 23.562-1", "1983"], ["23.562-1"]),
    ("DIFF_TMP_05", "lifecycle",
     "Were the EASA '9g seat' requirements of NPA 2013-20 already applicable in 2010?",
     "No. NPA 2013-20 dates from 2013, so it was not applicable in 2010.",
     ["2013"], ["9g seats"]),
    ("DIFF_TMP_06", "lifecycle",
     "Before Amendment 25-32 introduced § 25.791, was there a § 25.791 requirement to comply with?",
     "No. Section 25.791 did not exist prior to Amendment 25-32.",
     ["25-32"], ["25.791 did not exist prior to Amendment 25-32"]),

    # ───────── FAIT ÉCLATÉ / multi-passages ─────────
    ("DIFF_AGG_01", "list",
     "What are the specimen conditioning requirements (temperature and relative humidity) before the seat-cushion flammability test?",
     "Specimens are conditioned at 70 +/- 5 degrees F; relative humidity is 50% in AC 25-17/25-17A and 55% in CFR Part 25.",
     ["70", "50", "55"], ["70", "50 percent", "55%"]),
    ("DIFF_AGG_02", "multi_hop",
     "What are the two dynamic sled-test pulse levels required by the 25.562 seat tests (horizontal and vertical)?",
     "16g for the horizontal test and 14g for the vertical test.",
     ["16g", "14g"], ["16g", "14g vertical"]),
    ("DIFF_AGG_03", "list",
     "What injury-protection limits apply to an occupant in the 25.562 dynamic tests (HIC and femur load)?",
     "Head Injury Criterion (HIC) limit of 1,000 and a femur axial compressive load not exceeding 2,250 lb.",
     ["1,000", "2,250"], ["HIC", "2,250"]),
    ("DIFF_AGG_04", "list",
     "What burner nozzle characteristics does AC 25-17 (1991) specify (spray angle and flow rate)?",
     "An 80-degree spray angle, nominally rated at 2.25 gallons/hour at 100 psi.",
     ["80-degree", "2.25"], ["80-degree spray angle", "2.25 gallons/hour"]),

    # ───────── FAUX PRÉSUPPOSÉ subtil ─────────
    ("DIFF_FP_01", "false_premise",
     "Why is the HIC limit of 2000 in AC 20-146A more permissive than the CFR value?",
     "False premise: the HIC limit is 1,000, not 2000. There is no 2000 HIC limit to compare.",
     ["1,000", "2000"], ["HIC"]),
    ("DIFF_FP_02", "false_premise",
     "Which section sets the maximum femur axial load of 3000 lb in the § 25.562 tests?",
     "False premise: the femur axial compressive load limit is 2,250 lb, not 3000 lb.",
     ["2,250", "3000"], ["2,250"]),
    ("DIFF_FP_03", "false_premise",
     "How does ETSO-C127c set the maximum average burn length at 3 inches?",
     "False premise: ETSO-C127c sets the burn length at 6 inches; 3 inches is the FAA AC 25-17 value, not the ETSO one.",
     ["6 inches", "3 inches"], ["may not exceed 6 inches"]),
    ("DIFF_FP_04", "false_premise",
     "Which paragraph of AC 21-25C describes computer modeling for TSO seat changes?",
     "False premise: there is no AC 21-25C; the latest revision is AC 21-25B.",
     ["AC 21-25C", "AC 21-25B"], ["21-25"]),
    ("DIFF_FP_05", "false_premise",
     "What is the 18g vertical sled test required by § 25.562?",
     "False premise: the § 25.562 vertical test is 14g, not 18g (the horizontal test is 16g).",
     ["14g", "18g", "16g"], ["14g", "16g"]),
    ("DIFF_FP_06", "false_premise",
     "How does NPA 2013-20 require a 55 ft/s downward vertical velocity change?",
     "False premise: NPA 2013-20 requires a downward vertical velocity change of 35 ft/s (10.7 m/s), not 55 ft/s.",
     ["35 ft", "55 ft"], ["35 ft/s"]),

    # ───────── SOCLE FACTUEL DIRECT (vrai usage — KG ~ RAG attendu) ─────────
    ("DIFF_FACT_01", "factual",
     "What is the Head Injury Criterion (HIC) limit in the § 25.562 dynamic tests?",
     "1,000.", ["1,000"], ["HIC"]),
    ("DIFF_FACT_02", "factual",
     "What forward load level defines a Type I (Transport/Large Aeroplane) seat under ETSO-C39b?",
     "9g forward.", ["9g"], ["forward load of 9g"]),
    ("DIFF_FACT_03", "factual",
     "What maximum femur axial compressive load is allowed in the § 25.562 tests?",
     "2,250 lb (10.0 kN).", ["2,250"], ["2,250"]),
    ("DIFF_FACT_04", "factual",
     "What downward vertical velocity change does NPA 2013-20 require for the vertical test?",
     "35 ft/s (10.7 m/s).", ["35 ft"], ["35 ft/s"]),
]


def main() -> int:
    drv = get_neo4j_client().driver
    out = []
    missing = []
    with drv.session() as s:
        for qid, qtype, question, answer, ids, anchors in Q:
            # vérifie chaque ancre dans le KG aero
            for a in anchors:
                r = s.run(
                    "MATCH (c:Claim {tenant_id:$t}) WHERE c.text CONTAINS $a RETURN count(c) AS n",
                    t=TENANT, a=a).single()
                if not r or r["n"] == 0:
                    missing.append((qid, a))
            out.append({
                "id": qid,
                "question": question,
                "primary_type": qtype,
                "secondary_types": [],
                "language": "en",
                "ground_truth": {
                    "answer": answer,
                    "exact_identifiers": ids,
                    "supporting_doc_ids": [],
                    "answerability": "answerable",
                    "false_premise": qtype == "false_premise",
                },
                "source_set": "aero_kg_grounded_differential",
                "category": qtype,
            })

    print(f"Questions construites : {len(out)}")
    from collections import Counter
    print("Par type :", dict(Counter(q["primary_type"] for q in out)))
    if missing:
        print(f"\n⚠️ ANCRES INTROUVABLES dans le KG ({len(missing)}) — à corriger AVANT usage :")
        for qid, a in missing:
            print(f"   {qid} : '{a}'")
    else:
        print("\n✅ Toutes les ancres vérifiées présentes dans le KG aero.")

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nÉcrit : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
