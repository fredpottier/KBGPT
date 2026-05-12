"""Pack synthétique 50q pour calibrer les seuils du multi-view scorer (P1.6).

5 catégories x 10 cas chacune (50 total) :
  - exact_match_expected   : answer cite verbatim les identifiers/passages → exact ≥ 0.95
  - fuzzy_valid             : reformulation acceptable conservant les key facts → fuzzy ≥ 0.85
  - semantic_valid          : paraphrase profonde mais sémantiquement équivalente → semantic ≥ 0.75
  - false_positives          : answer plausible mais factuellement incorrecte → toutes vues < seuil
  - mixed                    : cas hybrides, abstain corrects, partial answers

Le pack est domain-agnostic (pas de référence corpus aerospace/réglementaire spécifique).

Usage :
    docker exec knowbase-app python /app/benchmark/evaluators/multi_view_validation_pack.py
    → produit data/benchmark/calibration/multi_view_scorer_validation.json
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from benchmark.evaluators.multi_view_scorer import multi_view_score, DEFAULT_THRESHOLDS


@dataclass
class ValidationCase:
    case_id: str
    category: str  # exact|fuzzy|semantic|false_positive|mixed
    answer: str
    gold_answer: str
    expected_identifiers: Optional[list[str]] = None
    list_items_expected: Optional[list[str]] = None
    answerability: str = "answerable"
    decision: str = "ANSWER"
    expected_dominant: str = "exact"  # exact|fuzzy|semantic|miss|abstain
    expected_min_best: float = 0.0  # score minimum attendu sur la "meilleure" vue


CASES: list[ValidationCase] = [
    # ======================================================================
    # exact_match_expected (10) — answer cite verbatim les passages clés
    # ======================================================================
    ValidationCase("EXACT_01", "exact",
        answer="Regulation (EU) 2021/821 was adopted on 20 May 2021 and applies from 9 September 2021.",
        gold_answer="Regulation (EU) 2021/821 adopted 20 May 2021 applies from 9 September 2021",
        expected_identifiers=["2021/821", "20 May 2021", "9 September 2021"],
        expected_dominant="exact", expected_min_best=0.85),
    ValidationCase("EXACT_02", "exact",
        answer="The maximum thrust is 22,500 lbf at sea level.",
        gold_answer="Maximum thrust 22,500 lbf at sea level",
        expected_identifiers=["22,500 lbf", "sea level"],
        expected_dominant="fuzzy", expected_min_best=0.90),
    ValidationCase("EXACT_03", "exact",
        answer="Article 5 paragraph 2 of GDPR states that personal data shall be accurate.",
        gold_answer="Article 5(2) GDPR : personal data shall be accurate",
        expected_identifiers=["Article 5", "GDPR"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("EXACT_04", "exact",
        answer="ISO 27001:2022 was published in October 2022.",
        gold_answer="ISO 27001:2022 published October 2022",
        expected_identifiers=["ISO 27001:2022", "October 2022"],
        expected_dominant="exact", expected_min_best=0.85),
    ValidationCase("EXACT_05", "exact",
        answer="The fine threshold under CCPA is up to $7,500 per intentional violation.",
        gold_answer="CCPA fine threshold : up to $7,500 per intentional violation",
        expected_identifiers=["$7,500", "CCPA"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("EXACT_06", "exact",
        answer="EU AI Act adopted 13 March 2024 by European Parliament.",
        gold_answer="EU AI Act adopted 13 March 2024",
        expected_identifiers=["13 March 2024", "EU AI Act"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("EXACT_07", "exact",
        answer="HIPAA Privacy Rule effective date : April 14, 2003.",
        gold_answer="HIPAA Privacy Rule effective April 14, 2003",
        expected_identifiers=["HIPAA", "April 14, 2003"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("EXACT_08", "exact",
        answer="The temperature limit is 850 °C for nickel alloys per AMS 5662.",
        gold_answer="Temperature limit 850°C nickel alloys AMS 5662",
        expected_identifiers=["850", "AMS 5662"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("EXACT_09", "exact",
        answer="Le décret 2024-152 du 24 février 2024 modifie le code du travail.",
        gold_answer="Décret 2024-152 du 24 février 2024 modifie code du travail",
        expected_identifiers=["2024-152", "24 février 2024"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("EXACT_10", "exact",
        answer="DSM-5-TR was published by the American Psychiatric Association in March 2022.",
        gold_answer="DSM-5-TR published American Psychiatric Association March 2022",
        expected_identifiers=["DSM-5-TR", "March 2022"],
        expected_dominant="fuzzy", expected_min_best=0.85),

    # ======================================================================
    # fuzzy_valid (10) — reformulation OK, key facts préservés
    # ======================================================================
    ValidationCase("FUZZY_01", "fuzzy",
        answer="The directive entered into force on 25 May 2018, requiring all member states to comply.",
        gold_answer="The directive came into force 25 May 2018, member states must comply",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("FUZZY_02", "fuzzy",
        answer="Maximum allowable cabin pressure differential is 8.6 psi during cruise.",
        gold_answer="Cabin pressure differential limited to 8.6 psi at cruise altitude",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("FUZZY_03", "fuzzy",
        answer="Three primary controls govern dual-use exports : licensing, end-use checks, country lists.",
        gold_answer="Dual-use export governance : licensing requirements, end-use verification, country control lists",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("FUZZY_04", "fuzzy",
        answer="The applicant shall demonstrate that the design meets all certification specifications.",
        gold_answer="Applicants must demonstrate compliance of the design with certification requirements",
        expected_dominant="fuzzy", expected_min_best=0.70),
    ValidationCase("FUZZY_05", "fuzzy",
        answer="GDPR fines reach up to 4% of global annual turnover or €20 million, whichever is higher.",
        gold_answer="GDPR maximum fine : 4% global turnover or 20M EUR, whichever greater",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("FUZZY_06", "fuzzy",
        answer="Encryption AES-256 is mandated for all sensitive data at rest under federal guidelines.",
        gold_answer="Federal rules require AES-256 encryption for sensitive data stored at rest",
        expected_dominant="fuzzy", expected_min_best=0.70),
    ValidationCase("FUZZY_07", "fuzzy",
        answer="A risk assessment must be conducted prior to deploying any new AI system in the EU.",
        gold_answer="Before deploying AI systems in the EU, organizations shall perform a risk assessment",
        expected_dominant="fuzzy", expected_min_best=0.70),
    ValidationCase("FUZZY_08", "fuzzy",
        answer="Inspection intervals are set at every 600 flight hours or 12 calendar months.",
        gold_answer="Inspection due every 600 hours of flight or 12 months calendar time",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("FUZZY_09", "fuzzy",
        answer="Notification to the supervisory authority shall occur within 72 hours of detecting a breach.",
        gold_answer="Within 72h of breach detection, notify the supervisory authority",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("FUZZY_10", "fuzzy",
        answer="The flight crew shall complete recurrent training every 12 months.",
        gold_answer="Recurrent training is required for the flight crew every 12 months",
        expected_dominant="fuzzy", expected_min_best=0.75),

    # ======================================================================
    # semantic_valid (10) — paraphrase profonde, mêmes informations factuelles
    # ======================================================================
    ValidationCase("SEM_01", "semantic",
        answer="When operating in dense traffic environments, controllers continuously coordinate aircraft separation.",
        gold_answer="In high-density airspace, air traffic controllers maintain ongoing aircraft spacing.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_02", "semantic",
        answer="Cybersecurity governance frameworks help organizations identify and manage threats.",
        gold_answer="Frameworks for cyber governance enable companies to detect and address risks.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_03", "semantic",
        answer="The company demonstrated compliance with environmental sustainability obligations through annual reporting.",
        gold_answer="Through yearly reports, the firm proved adherence to environmental sustainability rules.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_04", "semantic",
        answer="Supply chain due diligence is essential for ethical procurement.",
        gold_answer="For ethical purchasing, conducting supply chain due diligence is critical.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_05", "semantic",
        answer="Patient confidentiality is a cornerstone of medical ethics globally.",
        gold_answer="Across the world, keeping patient information confidential anchors medical ethics.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_06", "semantic",
        answer="A robust quality management system reduces the risk of operational failures.",
        gold_answer="Operational failure risk decreases with a strong quality management system.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_07", "semantic",
        answer="Open data policies have catalyzed innovation in public service delivery.",
        gold_answer="The advent of open data has driven innovation across public services.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_08", "semantic",
        answer="Energy efficiency improvements yield long-term cost savings for industrial facilities.",
        gold_answer="Industrial sites that improve energy efficiency see lasting cost reductions.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_09", "semantic",
        answer="Diversification of suppliers mitigates the impact of disruptions in any single market.",
        gold_answer="Having multiple suppliers reduces exposure to disruptions in one specific market.",
        expected_dominant="semantic", expected_min_best=0.65),
    ValidationCase("SEM_10", "semantic",
        answer="Audit trails enable retrospective analysis of system access events.",
        gold_answer="Through audit trails, organizations can investigate past system access activity.",
        expected_dominant="semantic", expected_min_best=0.65),

    # ======================================================================
    # false_positives (10) — answer plausible mais factuellement fausse
    # ======================================================================
    ValidationCase("FP_01", "false_positive",
        answer="GDPR was enacted in 2010 by the United Nations General Assembly.",
        gold_answer="GDPR was adopted in 2016 by the European Union.",
        expected_identifiers=["2016", "European Union"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_02", "false_positive",
        answer="The maximum altitude is 50,000 feet for commercial airliners.",
        gold_answer="Maximum cruising altitude commercial airliners typically 41,000 feet.",
        expected_identifiers=["41,000 feet"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_03", "false_positive",
        answer="ISO 9001 specifies cybersecurity requirements for cloud platforms.",
        gold_answer="ISO 9001 specifies quality management system requirements.",
        expected_identifiers=["quality management"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_04", "false_positive",
        answer="The Eiffel Tower was completed in 1923 in London.",
        gold_answer="The Eiffel Tower was completed in 1889 in Paris.",
        expected_identifiers=["1889", "Paris"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_05", "false_positive",
        answer="Article 17 of the EU AI Act deals with maritime transportation.",
        gold_answer="Article 17 of the EU AI Act addresses high-risk AI system requirements.",
        expected_identifiers=["high-risk"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_06", "false_positive",
        answer="The minimum age for a pilot license is 25 years according to FAA.",
        gold_answer="FAA minimum age for private pilot license is 17 years.",
        expected_identifiers=["17"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_07", "false_positive",
        answer="The currency of Brazil is the peso.",
        gold_answer="The currency of Brazil is the real (BRL).",
        expected_identifiers=["real", "BRL"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_08", "false_positive",
        answer="HIPAA covers all citizens worldwide.",
        gold_answer="HIPAA covers protected health information of US individuals.",
        expected_identifiers=["US"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_09", "false_positive",
        answer="CS-25 applies to small private aircraft under 5700 kg.",
        gold_answer="CS-25 applies to large aeroplanes above 5700 kg.",
        expected_identifiers=["large aeroplanes", "5700 kg"],
        expected_dominant="miss", expected_min_best=0.0),
    ValidationCase("FP_10", "false_positive",
        answer="The Mars rover Perseverance landed in 2025.",
        gold_answer="The Mars rover Perseverance landed in February 2021.",
        expected_identifiers=["February 2021"],
        expected_dominant="miss", expected_min_best=0.0),

    # ======================================================================
    # mixed (10) — abstain corrects, partial answers, lists
    # ======================================================================
    ValidationCase("MIX_01", "mixed",
        answer="La reponse a votre question n'a pas ete trouvee dans les documents disponibles.",
        gold_answer="",
        answerability="unanswerable", decision="ABSTAIN",
        expected_dominant="abstain", expected_min_best=1.0),
    ValidationCase("MIX_02", "mixed",
        answer="The available documents do not specify this information.",
        gold_answer="",
        answerability="unanswerable", decision="ABSTAIN",
        expected_dominant="abstain", expected_min_best=1.0),
    ValidationCase("MIX_03", "mixed",
        answer="The list includes Reg 2021/821, Reg 2019/125, and Reg 952/2013.",
        gold_answer="EU dual-use exports are governed by 3 regulations : 2021/821, 2019/125, 952/2013.",
        list_items_expected=["2021/821", "2019/125", "952/2013"],
        expected_dominant="fuzzy", expected_min_best=0.80),
    ValidationCase("MIX_04", "mixed",
        answer="The standards include ISO 27001 and NIST CSF.",
        gold_answer="Cybersecurity standards used : ISO 27001, NIST CSF, SOC 2, CIS Controls.",
        list_items_expected=["ISO 27001", "NIST CSF", "SOC 2", "CIS Controls"],
        expected_dominant="miss", expected_min_best=0.0),  # partial — manque 2 items
    ValidationCase("MIX_05", "mixed",
        answer="GDPR Article 5 establishes the principles of processing personal data.",
        gold_answer="GDPR Article 5 sets out the data processing principles.",
        expected_identifiers=["Article 5", "GDPR"],
        expected_dominant="fuzzy", expected_min_best=0.85),
    ValidationCase("MIX_06", "mixed",
        answer="No information available on this specific topic in the provided documents.",
        gold_answer="",
        answerability="unanswerable", decision="ABSTAIN",
        expected_dominant="abstain", expected_min_best=1.0),
    ValidationCase("MIX_07", "mixed",
        answer="The pilot proficiency check shall be conducted at least every 6 calendar months.",
        gold_answer="Pilot proficiency check required at minimum every 6 months.",
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("MIX_08", "mixed",
        answer="Based on regulation 2021/821, dual-use items require an export authorization.",
        gold_answer="Per Reg 2021/821, dual-use items need an export license.",
        expected_identifiers=["2021/821"],
        expected_dominant="fuzzy", expected_min_best=0.75),
    ValidationCase("MIX_09", "mixed",
        answer="Multiple options exist : option A is recommended based on cost-benefit analysis.",
        gold_answer="Among options A, B, C : option A recommended after cost-benefit study.",
        expected_dominant="fuzzy", expected_min_best=0.70),
    ValidationCase("MIX_10", "mixed",
        answer="HIPAA Security Rule does not specify exact AES key lengths.",
        gold_answer="HIPAA Security Rule does not mandate a specific encryption algorithm or key length.",
        expected_identifiers=["HIPAA"],
        expected_dominant="fuzzy", expected_min_best=0.65),
]


def run_validation(thresholds: dict[str, float] = DEFAULT_THRESHOLDS) -> dict:
    """Évalue le scorer sur les 50 cases. Retourne précision/recall par catégorie."""
    results = []
    for case in CASES:
        score = multi_view_score(
            answer=case.answer,
            gold_answer=case.gold_answer,
            expected_identifiers=case.expected_identifiers,
            list_items_expected=case.list_items_expected,
            answerability=case.answerability,
            decision=case.decision,
            thresholds=thresholds,
        )
        passed_dominant = (score.dominant_signal == case.expected_dominant)
        passed_score = (score.best >= case.expected_min_best) if case.expected_dominant != "miss" else (score.best < 0.85)
        results.append({
            "case_id": case.case_id,
            "category": case.category,
            "expected_dominant": case.expected_dominant,
            "actual_dominant": score.dominant_signal,
            "actual_exact": score.exact,
            "actual_fuzzy": score.fuzzy,
            "actual_semantic": score.semantic,
            "actual_best": score.best,
            "expected_min_best": case.expected_min_best,
            "passed_dominant": passed_dominant,
            "passed_score": passed_score,
            "abstain_reward": score.abstain_reward_applied,
        })

    # Aggregate
    n = len(results)
    n_dominant_pass = sum(1 for r in results if r["passed_dominant"])
    n_score_pass = sum(1 for r in results if r["passed_score"])
    by_cat: dict[str, dict] = {}
    for r in results:
        cat = r["category"]
        if cat not in by_cat:
            by_cat[cat] = {"n": 0, "dominant_pass": 0, "score_pass": 0}
        by_cat[cat]["n"] += 1
        if r["passed_dominant"]:
            by_cat[cat]["dominant_pass"] += 1
        if r["passed_score"]:
            by_cat[cat]["score_pass"] += 1

    return {
        "n": n,
        "thresholds": thresholds,
        "global_dominant_accuracy": round(n_dominant_pass / n, 3),
        "global_score_accuracy": round(n_score_pass / n, 3),
        "by_category": {
            k: {
                **v,
                "dominant_accuracy": round(v["dominant_pass"] / v["n"], 3),
                "score_accuracy": round(v["score_pass"] / v["n"], 3),
            }
            for k, v in by_cat.items()
        },
        "per_case": results,
    }


def main() -> None:
    output = Path("/app/data/benchmark/calibration/multi_view_scorer_validation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    res = run_validation()
    output.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWritten {output}")
    print(f"Global dominant accuracy: {res['global_dominant_accuracy']}")
    print(f"Global score accuracy   : {res['global_score_accuracy']}")
    print("By category :")
    for k, v in res["by_category"].items():
        print(f"  {k:18s} : dom={v['dominant_accuracy']:.2f} | score={v['score_accuracy']:.2f} (n={v['n']})")


if __name__ == "__main__":
    main()
