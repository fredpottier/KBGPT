"""Installe le contexte domaine « Alcool & santé (épidémiologie) » pour un tenant.

Corpus cible : études et méta-analyses sur l'alcool et la santé (mortalité,
cardiovasculaire, cancers, AVC, démence/cerveau, diabète, foie, autres
comorbidités) + recommandations nationales (guidelines). Le point différenciant
de ce corpus = il est RICHE EN CONTRADICTIONS DATÉES (effet « protecteur »
observationnel vs « aucun bénéfice » génétique/récent ; guidelines qui se
renversent), idéal pour démontrer la détection de contradictions + la lignée.

⚠️ Le contexte domaine n'agit qu'à l'INGESTION (le runtime ne le lit pas).
À installer AVANT d'ingérer le corpus alcool, sur le tenant dédié.

Usage :
    docker compose exec app python app/scripts/set_domain_context_alcohol_health.py
    (option : --tenant alcohol_health)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_store import get_domain_context_store

BACKUP_DIR = Path("/data/staging_new_docs")


def build_profile(tenant: str) -> DomainContextProfile:
    return DomainContextProfile(
        tenant_id=tenant,
        domain_summary=(
            "Epidemiologie de l'alcool et de la sante : cohortes prospectives, meta-analyses, "
            "randomisation mendelienne (genetique), essais randomises, rapports Global Burden "
            "of Disease et recommandations nationales. Outcomes : mortalite toute cause, "
            "cardiovasculaire, AVC, cancers (sein, oesophage, colon, foie), demence et volume "
            "cerebral, diabete, hypertension, fibrillation atriale, pancreatite, comorbidites. "
            "Corpus riche en contradictions datees (protecteur vs nocif)."
        ),
        industry="public_health_epidemiology",
        sub_domains=[
            "Cardiovascular epidemiology (CHD, stroke, atrial fibrillation, hypertension)",
            "Oncology / carcinogenesis (breast, oesophageal, colorectal, liver cancers)",
            "Neurology & cognition (dementia, brain volume)",
            "Metabolic disease (type 2 diabetes)",
            "Hepatology & gastroenterology (cirrhosis, pancreatitis, gallstones)",
            "Study methodology & bias (abstainer/sick-quitter bias, Mendelian randomization)",
            "Public-health guidelines & position statements",
        ],
        target_users=[
            "Epidemiologists",
            "Public health policy makers",
            "Clinicians",
            "Science communicators / journalists",
        ],
        document_types=[
            "Prospective cohort study",
            "Systematic review / meta-analysis",
            "Mendelian randomization study",
            "Randomized controlled trial",
            "Public-health guideline",
            "Position statement / editorial",
            "Global Burden of Disease report",
            "IARC monograph",
        ],
        common_acronyms={
            "RR": "Relative Risk",
            "HR": "Hazard Ratio",
            "OR": "Odds Ratio",
            "CI": "Confidence Interval",
            "CVD": "Cardiovascular Disease",
            "CHD": "Coronary Heart Disease",
            "CAD": "Coronary Artery Disease",
            "MI": "Myocardial Infarction",
            "AF": "Atrial Fibrillation",
            "T2DM": "Type 2 Diabetes Mellitus",
            "BP": "Blood Pressure",
            "HDL": "High-Density Lipoprotein",
            "GBD": "Global Burden of Disease",
            "MR": "Mendelian Randomization",
            "TMREL": "Theoretical Minimum Risk Exposure Level",
            "NDE": "Non-Drinker Equivalence",
            "IARC": "International Agency for Research on Cancer",
            "WHO": "World Health Organization",
            "NHMRC": "National Health and Medical Research Council (Australia)",
            "CCSA": "Canadian Centre on Substance Use and Addiction",
            "NIAAA": "National Institute on Alcohol Abuse and Alcoholism (US)",
            "UKB": "UK Biobank",
            "CKB": "China Kadoorie Biobank",
            "MACH": "Moderate Alcohol and Cardiovascular Health (trial)",
        },
        key_concepts=[
            "all-cause mortality", "J-shaped curve", "U-shaped association",
            "dose-response", "relative risk", "hazard ratio", "standard drink",
            "grams per day", "drinks per week", "light drinking", "moderate drinking",
            "heavy drinking", "abstainer bias", "sick-quitter effect", "former drinkers",
            "lifelong abstainers", "reference group", "residual confounding",
            "reverse causation", "theoretical minimum risk exposure level",
            "no safe level", "cardioprotection", "Group 1 carcinogen", "carcinogenicity",
            "ischemic stroke", "hemorrhagic stroke", "incident hypertension",
            "brain grey matter volume", "study design", "observational study",
            "Mendelian randomization", "randomized controlled trial",
            "alcohol-attributable fraction", "low-risk drinking guideline",
        ],
        versioning_hints=(
            "Studies and guidelines are identified by FIRST AUTHOR + YEAR (Holmes 2014, "
            "Zhao 2023) or ORGANISATION + YEAR (NHMRC 2020, WHO 2023, CCSA 2023). The YEAR "
            "is the key lifecycle axis: a later analysis on the SAME question commonly "
            "UPDATES or CONTRADICTS an earlier one. Notable supersession/evolution: the "
            "Global Burden of Disease alcohol analysis evolved from GBD 2016 (Griswold 2018, "
            "'no safe level for anyone') to GBD 2020 (Bryazka 2022, 'age-specific: zero for "
            "the young, small amounts may benefit adults 40+') — same consortium, opposite "
            "nuance. National guidelines are revised over time and the newer version "
            "supersedes the older (e.g. Canada's prior low-risk limits -> CCSA 2023, much "
            "lower). Capture the publication year and any explicit 'updates/replaces/"
            "supersedes prior guidance' statements."
        ),
        identification_semantics=(
            "Rule: First-author surname + 4-digit year -> study_id (Holmes 2014, Zhao 2023, "
            "Biddinger 2022).\n"
            "Rule: Organisation acronym + year -> guideline_id (NHMRC 2020, WHO 2023, "
            "CCSA 2023, NIAAA).\n"
            "Rule: 'GBD' + cycle year -> gbd_report_id (GBD 2016, GBD 2020).\n"
            "Rule: cohort/biobank name -> data_source (UK Biobank, China Kadoorie Biobank, "
            "Million Veteran Program).\n"
            "Counter-example: RR 0.80, HR 1.4, OR 1.03 -> effect-size estimates, NOT "
            "identifiers.\n"
            "Counter-example: 12 g/day, 25 g/day, 2 drinks/week, 10 standard drinks/week -> "
            "DOSE / exposure levels, NOT identifiers.\n"
            "Counter-example: 4.90 mm Hg, 4.1% of cancers, 15% higher odds -> outcome "
            "magnitudes, NOT identifiers."
        ),
        axis_reclassification_rules=json.dumps([]),
        axis_policy=json.dumps({
            "strip_prefixes": ["Revision", "Update", "Edition"],
            "expected_axes": ["year", "guideline_version"],
            "excluded_axes": ["model_generation", "product_release"],
            "plausibility_overrides": {
                "lifecycle_status": {"reject_patterns": [r"^\d{4}-\d{2}-\d{2}$"]}
            },
            "year_range": {"min": 1980, "max_relative": 2},
            "strict_expected": False,
        }),
        hygiene_entity_stoplist="",
        active_packs=[],
        context_priority="high",
        llm_injection_prompt=(
            "[DOMAIN CONTEXT - Alcohol & Health Epidemiology]\n\n"
            "BUSINESS CONTEXT: A corpus of epidemiological studies, meta-analyses, "
            "Mendelian randomization studies, trials, Global Burden of Disease reports and "
            "national public-health guidelines on ALCOHOL CONSUMPTION and HEALTH OUTCOMES "
            "(all-cause mortality, cardiovascular disease, stroke, multiple cancers, "
            "dementia and brain health, type 2 diabetes, hypertension, atrial fibrillation, "
            "pancreatitis, liver disease and other comorbidities).\n\n"
            "EXTRACTION GUIDANCE: For each finding, capture FOUR things precisely: "
            "(1) the OUTCOME (e.g. all-cause mortality, breast cancer, ischemic stroke); "
            "(2) the DIRECTION and EFFECT SIZE (protective RR<1 vs harmful RR>1, with the "
            "value and confidence interval); (3) the DOSE / exposure (grams/day, drinks/"
            "week, light/moderate/heavy); (4) the STUDY DESIGN (observational cohort, "
            "meta-analysis, MENDELIAN RANDOMIZATION/genetic, randomized trial, or guideline) "
            "and the PUBLICATION YEAR. The study design and year are CRITICAL: a 'protective' "
            "observational association and a 'harmful / no-benefit' genetic (Mendelian) "
            "finding on the SAME outcome are a GENUINE, well-known tension in this field — "
            "preserve both verbatim so the contradiction can be surfaced. Treat guideline "
            "recommendations (e.g. 'no more than 2 standard drinks per week', 'no safe "
            "level') as NORMATIVE claims tied to an organisation and a year; newer guidelines "
            "supersede older ones. Preserve numeric values and units (RR/HR/OR, g/day, "
            "drinks/week, mm Hg, %, years of life lost) EXACTLY — they are effect sizes and "
            "doses, never document identifiers. Identify studies by first author + year, "
            "guidelines by organisation + year."
        ),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health",
                    help="tenant cible (default: alcohol_health)")
    args = ap.parse_args()
    tenant = args.tenant
    store = get_domain_context_store()

    old = store.get_profile(tenant)
    if old is not None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = BACKUP_DIR / f"domain_context_{tenant}_backup_{stamp}.json"
        backup.write_text(
            json.dumps(dict(old.__dict__), default=str, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"backup ancien profil -> {backup}")

    profile = build_profile(tenant)
    store.save_profile(profile)
    print(f"profil '{tenant}' ecrit (industry={profile.industry}).")

    check = store.get_profile(tenant)
    print("relecture:", check.industry, "|", len(check.common_acronyms), "acronymes |",
          len(check.key_concepts), "concepts")


if __name__ == "__main__":
    main()
