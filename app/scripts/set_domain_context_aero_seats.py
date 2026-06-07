"""Installe le contexte domaine « sièges/crashworthiness » pour le tenant default.

Contexte : le tenant `default` portait encore l'ancien contexte « Aerospace
certification & dual-use export control » (corpus réglementaire européen de
décembre 2025) lors des imports SAP et aéro — avec deux bugs hérités :
une règle d'axe SAP résiduelle et `year_range.min: 1990` qui rejetait les
années des documents du corpus (AC 23.562-1 = 1983, AC 21-25 = 1989).

Ce script :
1. sauvegarde l'ancien profil dans /data/staging_new_docs/ (réversible) ;
2. installe le profil dédié au corpus sièges (AC/CFR/ETSO, HIC, essais
   dynamiques, convention de révision à suffixe lettre, dates US M/D/YY).

Effet : à la PROCHAINE ingestion uniquement (le runtime ne lit pas le
contexte domaine). Usage :
    docker-compose exec app python app/scripts/set_domain_context_aero_seats.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_store import get_domain_context_store

TENANT = "default"
BACKUP_DIR = Path("/data/staging_new_docs")


def build_profile() -> DomainContextProfile:
    return DomainContextProfile(
        tenant_id=TENANT,
        domain_summary=(
            "Certification aeronautique des sieges passagers et systemes de retenue "
            "(crashworthiness) FAA/EASA. Advisory Circulars (series AC 21-25, 25-17, "
            "25.562-1, 20-146, 23.562-1, 25.785-1, 25.853-1), 14 CFR Part 25, standards "
            "equipement ETSO/TSO (C127, C39), NPA EASA, rapports de recherche DOT/FAA "
            "et brevets US de sieges a absorption d'energie."
        ),
        industry="aerospace_certification",
        sub_domains=[
            "Seat & restraint certification (FAA AC / 14 CFR Part 25)",
            "Equipment qualification (TSO / ETSO)",
            "Cabin interiors crashworthiness",
            "Crashworthiness research (DOT/FAA)",
            "Seat technology patents (energy absorbers)",
        ],
        target_users=[
            "Certification engineers",
            "Seat design engineers",
            "Compliance officers",
            "Test laboratory engineers",
        ],
        document_types=[
            "Advisory Circular",
            "Federal regulation (14 CFR)",
            "ETSO/TSO standard",
            "NPA (EASA)",
            "Research report (DOT/FAA)",
            "Patent",
        ],
        common_acronyms={
            "FAA": "Federal Aviation Administration",
            "EASA": "European Union Aviation Safety Agency",
            "AC": "Advisory Circular",
            "CFR": "Code of Federal Regulations",
            "FAR": "Federal Aviation Regulations",
            "TSO": "Technical Standard Order",
            "TSOA": "TSO Authorization",
            "ETSO": "European Technical Standard Order",
            "NPA": "Notice of Proposed Amendment",
            "CS": "Certification Specification",
            "CS-25": "Certification Specifications for Large Aeroplanes",
            "AMC": "Acceptable Means of Compliance",
            "GM": "Guidance Material",
            "HIC": "Head Injury Criterion",
            "ATD": "Anthropomorphic Test Device",
            "SAE": "Society of Automotive Engineers",
            "AS8049": "SAE Aerospace Standard for aircraft seats",
            "DOT": "Department of Transportation (US)",
            "CAMI": "Civil Aerospace Medical Institute",
            "ANM": "FAA Transport Airplane Directorate",
            "AIR": "FAA Aircraft Certification Service",
            "SFAR": "Special Federal Aviation Regulation",
            "TC": "Type Certificate",
            "STC": "Supplemental Type Certificate",
            "ICA": "Instructions for Continued Airworthiness",
            "NPRM": "Notice of Proposed Rulemaking",
            "CG": "Center of Gravity",
            "IFE": "In-Flight Entertainment",
        },
        key_concepts=[
            "dynamic test", "static test", "emergency landing conditions",
            "head injury criterion", "lumbar load", "femur load",
            "seat restraint system", "safety belt", "shoulder harness",
            "torso restraint", "occupant protection", "energy absorber",
            "crashworthiness", "floor deformation", "pitch and roll deformation",
            "forward longitudinal velocity change",
            "downward vertical velocity change",
            "test pulse", "peak deceleration", "yaw angle",
            "solid strike", "glancing blow", "head path", "head excursion",
            "side-facing seats", "oblique seats", "berth", "litter",
            "seat cushion flammability", "fire protection",
            "structural substantiation", "modified seats",
            "major change", "minor change", "TSO approval",
            "injury criteria", "spinal injury", "submarining",
        ],
        versioning_hints=(
            "FAA/EASA letter-suffix revision convention: a trailing capital letter on "
            "a document ID is a REVISION of the same document (AC 25.562-1 -> "
            "25.562-1A -> 25.562-1B; ETSO-C127a -> b -> c; TSO-C39 -> C39b). Later "
            "letters supersede earlier ones; the replacing document usually states "
            "the cancellation explicitly on page 1 (AC X, dated M/D/YY, is canceled). "
            "14 CFR paragraphs evolve via amendments Amdt 25-NN; quoted historical "
            "amendment blocks keep their original numbering and dates. US date format "
            "M/D/YY or M/D/YYYY is standard in document headers (Date: 01/19/96). "
            "Patent numbers (US5842669, US20200262563) identify inventions, not versions."
        ),
        identification_semantics=(
            "Rule: AC NN-NN or AC NN.NNN-N + optional trailing letter -> "
            "advisory_circular_id (AC 21-25B, AC 25.562-1A).\n"
            "Rule: paragraph 25.NNN / 14 CFR 25.NNN / Part 25.NNN with optional "
            "(a)(1) -> cfr_paragraph_id.\n"
            "Rule: TSO-CNNN / ETSO-CNNN + optional letter -> tso_id.\n"
            "Rule: Amdt 25-NN or Amendment 25-NN -> cfr_amendment_id, NOT a date.\n"
            "Rule: NPA YYYY-NN -> npa_id, NOT a date.\n"
            "Rule: AS8049 + optional revision letter -> SAE standard id.\n"
            "Rule: US + patent number -> patent_id.\n"
            "Counter-example: 16g, 14 g -> test acceleration level, NOT an identifier.\n"
            "Counter-example: HIC of 1000, 1,500 lbs, 680 kg -> threshold values, "
            "NOT identifiers.\n"
            "Counter-example: Date: M/D/YY in a header -> document date, NOT an identifier."
        ),
        axis_reclassification_rules=json.dumps([
            {
                "rule_id": "doc_version_not_product_release",
                "priority": 90,
                "description": "Document Version X.Y in evidence = doc revision, not product release",
                "conditions": {
                    "value_pattern": r"^\d+\.\d+$",
                    "current_role": "revision",
                    "evidence_quote_contains_any": [
                        "document version", "doc version", "document revision",
                    ],
                },
                "action": {"new_role": "unknown", "confidence_override": 0.3},
            }
        ]),
        axis_policy=json.dumps({
            "strip_prefixes": ["Revision", "Change", "Amendment"],
            "expected_axes": ["revision", "version", "edition"],
            "excluded_axes": ["trial_phase", "model_generation"],
            "plausibility_overrides": {
                "lifecycle_status": {"reject_patterns": [r"^\d{4}-\d{2}-\d{2}$"]}
            },
            # min 1950 : le corpus contient des docs de 1983/1989 et des
            # references plus anciennes (l'ancien min=1990 les rejetait).
            "year_range": {"min": 1950, "max_relative": 2},
            "strict_expected": True,
        }),
        hygiene_entity_stoplist="",
        active_packs=["aerospace_compliance"],
        context_priority="high",
        llm_injection_prompt=(
            "[DOMAIN CONTEXT - Aircraft Seat Certification & Crashworthiness]\n\n"
            "BUSINESS CONTEXT: FAA/EASA certification of passenger seats and "
            "restraint systems for civil aircraft. Corpus: FAA Advisory Circulars "
            "(AC 21-25 series - TSO seat modifications; AC 25-17 - cabin interiors "
            "crashworthiness handbook; AC 25.562-1 series - dynamic seat evaluation; "
            "AC 20-146 - dynamic test methodology; AC 23.562-1 - small airplanes; "
            "AC 25.785-1 - seats, berths, safety belts; AC 25.853-1 - flammability), "
            "14 CFR Part 25 (paragraphs 25.561, 25.562, 25.785, 25.853), ETSO/TSO "
            "equipment standards (ETSO-C127, TSO-C39), EASA NPA, DOT/FAA research "
            "reports, US patents on energy-absorbing seats.\n\n"
            "KEY CONCEPTS: dynamic tests (16g longitudinal, 14g vertical pulses), "
            "Head Injury Criterion (HIC <= 1000), lumbar compressive load "
            "(<= 1,500 lb), occupant protection in emergency landing, ATD "
            "instrumentation, floor deformation (pitch/roll), side-facing seats, "
            "energy absorbers, seat cushion flammability.\n\n"
            "EXTRACTION GUIDANCE: Treat document identifiers (AC 21-25B, "
            "25.562(b)(1), ETSO-C127c, AS8049C, patent numbers) as primary subjects "
            "and preserve them VERBATIM including the trailing revision letter. A "
            "trailing letter is a document revision (AC 25.562-1B supersedes "
            "25.562-1A); supersession and cancellation statements are critical facts "
            "to capture. FAA headers use US date format M/D/YY (Date: 01/19/96 = "
            "document date). Distinguish FAA (AC/CFR/TSO) from EASA (ETSO/CS/NPA) "
            "authorities. Numeric values with units (g levels, lb/kg loads, HIC "
            "values, time in seconds) are test parameters - preserve exact values "
            "and units."
        ),
    )


def main() -> None:
    store = get_domain_context_store()

    old = store.get_profile(TENANT)
    if old is not None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = BACKUP_DIR / f"domain_context_{TENANT}_backup_{stamp}.json"
        backup.write_text(
            json.dumps(dict(old.__dict__), default=str, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"backup ancien profil -> {backup}")

    profile = build_profile()
    store.save_profile(profile)
    print(f"profil '{TENANT}' remplace (industry={profile.industry}).")

    check = store.get_profile(TENANT)
    print("relecture:", check.industry, "|", len(check.common_acronyms), "acronymes |",
          len(check.key_concepts), "concepts")
    print("axis_policy:", check.axis_policy)


if __name__ == "__main__":
    main()
