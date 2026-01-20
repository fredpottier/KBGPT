#!/usr/bin/env python3
"""
POC v4 Runner - Version avec rapport détaillé pour ChatGPT
Utilise les cas de test v4 générés par ChatGPT

Rapport inclut:
- Tableau par catégorie avec Expected/Obtained/Why
- Quality gate sur les evidence bundles
- Score strict vs Score épistémique
- Détail des overrides déterministes
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import TestCase, Verdict, DiscriminationResult, TestCaseCategory, Citation, Confidence
from discriminator import DiscursiveDiscriminator
from test_cases_v4 import ALL_TEST_CASES, TYPE1_CASES, TYPE2_CASES, FRONTIER_CASES


@dataclass
class BundleQuality:
    """Qualité d'un evidence bundle"""
    case_id: str
    num_extracts: int
    total_chars: int
    avg_extract_len: float
    has_empty_extract: bool
    has_title_only: bool  # Extraits < 50 chars
    is_valid: bool


@dataclass
class DetailedResult:
    """Résultat détaillé d'un cas de test"""
    case_id: str
    description: str
    category: str
    expected: str
    obtained: str
    is_match: bool
    is_safe: bool  # Pour score épistémique
    reasoning: str
    citations: list
    override_applied: bool
    override_reason: Optional[str]
    bundle_quality: BundleQuality


def analyze_bundle_quality(tc: TestCase) -> BundleQuality:
    """Analyse la qualité du bundle d'évidences"""
    extracts = []

    # Collecter tous les extraits
    if tc.evidence_bundle.concept_a:
        extracts.extend(tc.evidence_bundle.concept_a.extracts)
    if tc.evidence_bundle.concept_b:
        extracts.extend(tc.evidence_bundle.concept_b.extracts)
    if tc.evidence_bundle.scope:
        extracts.append(tc.evidence_bundle.scope)

    num_extracts = len(extracts)
    total_chars = sum(len(e.text) for e in extracts)
    avg_len = total_chars / num_extracts if num_extracts > 0 else 0
    has_empty = any(len(e.text.strip()) == 0 for e in extracts)
    has_title_only = any(len(e.text.strip()) < 50 for e in extracts)

    # Un bundle est valide s'il a au moins 1 extrait substantiel (>50 chars)
    is_valid = num_extracts > 0 and not has_empty and any(len(e.text.strip()) >= 50 for e in extracts)

    return BundleQuality(
        case_id=tc.id,
        num_extracts=num_extracts,
        total_chars=total_chars,
        avg_extract_len=avg_len,
        has_empty_extract=has_empty,
        has_title_only=has_title_only,
        is_valid=is_valid
    )


def run_single_case(discriminator: DiscursiveDiscriminator, tc: TestCase, mock: bool = False) -> DetailedResult:
    """Exécute un cas et retourne un résultat détaillé"""

    bundle_quality = analyze_bundle_quality(tc)

    if mock:
        # Mode mock: retourne le verdict attendu
        mock_citations = [
            Citation(extract_id=e.id, quote=e.text[:100])
            for e in (tc.evidence_bundle.concept_a.extracts if tc.evidence_bundle.concept_a else [])
        ]
        result = DiscriminationResult(
            test_case_id=tc.id,
            verdict=tc.expected_verdict,
            confidence=Confidence.HIGH,
            raw_reasoning=f"[MOCK] Verdict attendu: {tc.expected_verdict.value}",
            citations=mock_citations,
            abstain_reason=None
        )
        override_applied = False
        override_reason = None
    else:
        # Appel réel au discriminateur
        result = discriminator.discriminate(tc)

        # Vérifier si un override a été appliqué
        override_applied = False
        override_reason = None

        # Logique d'override déterministe (copie de discriminator.py)
        relation = tc.evidence_bundle.proposed_relation.upper()
        extracts_text = " ".join(
            e.text for e in (tc.evidence_bundle.concept_a.extracts if tc.evidence_bundle.concept_a else [])
        ).lower()

        if "HAS_EXACT" in relation and " or " in extracts_text:
            if result.verdict != Verdict.REJECT:
                override_applied = True
                override_reason = "HAS_EXACT + 'or' dans extraits → REJECT"
        elif "ALWAYS" in relation and "unless" in extracts_text:
            if result.verdict != Verdict.REJECT:
                override_applied = True
                override_reason = "ALWAYS + 'unless' dans extraits → REJECT"

    # Déterminer si c'est un match
    is_match = result.verdict == tc.expected_verdict

    # Score épistémique: ABSTAIN sur Type 2 compte comme "safe"
    is_safe = is_match
    if not is_match and result.verdict == Verdict.ABSTAIN:
        if tc.category in [TestCaseCategory.CANONICAL_TYPE2, TestCaseCategory.FRONTIER]:
            is_safe = True  # ABSTAIN au lieu de REJECT = prudent = OK

    # Extraire les quotes des citations
    citation_quotes = [c.quote if hasattr(c, 'quote') else str(c) for c in (result.citations[:3] if result.citations else [])]

    return DetailedResult(
        case_id=tc.id,
        description=tc.description[:80] + "..." if len(tc.description) > 80 else tc.description,
        category=tc.category.value,
        expected=tc.expected_verdict.value,
        obtained=result.verdict.value,
        is_match=is_match,
        is_safe=is_safe,
        reasoning=result.raw_reasoning[:500] if result.raw_reasoning else "",
        citations=citation_quotes,
        override_applied=override_applied,
        override_reason=override_reason,
        bundle_quality=bundle_quality
    )


def print_detailed_report(results: list[DetailedResult], output_file: Optional[str] = None):
    """Affiche le rapport détaillé"""

    lines = []

    def p(text=""):
        lines.append(text)
        print(text)

    p("\n" + "=" * 80)
    p("POC v4 - RAPPORT DÉTAILLÉ (ChatGPT Test Set)")
    p("=" * 80)

    # Statistiques globales
    total = len(results)
    type1_results = [r for r in results if "TYPE1" in r.category]
    type2_results = [r for r in results if "TYPE2" in r.category]
    frontier_results = [r for r in results if "FRONTIER" in r.category]

    p(f"\nNombre total de cas: {total}")
    p(f"  - Type 1 (ACCEPT attendu): {len(type1_results)}")
    p(f"  - Type 2 (REJECT attendu): {len(type2_results)}")
    p(f"  - Frontier (REJECT attendu): {len(frontier_results)}")

    # =========================================================================
    # SECTION 1: TABLEAU DÉTAILLÉ PAR CAS
    # =========================================================================
    p("\n" + "=" * 80)
    p("SECTION 1: DÉTAIL DE CHAQUE CAS")
    p("=" * 80)

    for i, r in enumerate(results, 1):
        status = "[OK]" if r.is_match else "[MISMATCH]"
        safe_tag = " [SAFE]" if r.is_safe and not r.is_match else ""
        p(f"\n[{i}/{total}] {r.case_id}: {r.description}")
        p(f"    Category: {r.category}")
        p(f"    Expected: {r.expected} | Obtained: {r.obtained} {status}{safe_tag}")
        if r.override_applied:
            p(f"    Override: {r.override_reason}")
        p(f"    Reasoning: {r.reasoning[:200]}...")
        if r.citations:
            p(f"    Citations: {len(r.citations)} extrait(s)")

    # =========================================================================
    # SECTION 2: QUALITY GATE SUR LES BUNDLES
    # =========================================================================
    p("\n" + "=" * 80)
    p("SECTION 2: QUALITY GATE - EVIDENCE BUNDLES")
    p("=" * 80)

    invalid_bundles = [r for r in results if not r.bundle_quality.is_valid]
    title_only_bundles = [r for r in results if r.bundle_quality.has_title_only]

    p(f"\nBundles invalides (0 extrait ou vide): {len(invalid_bundles)}")
    for r in invalid_bundles:
        p(f"  - {r.case_id}: {r.bundle_quality.num_extracts} extraits, {r.bundle_quality.total_chars} chars")

    p(f"\nBundles avec extraits 'titre only' (<50 chars): {len(title_only_bundles)}")
    for r in title_only_bundles:
        p(f"  - {r.case_id}: avg={r.bundle_quality.avg_extract_len:.0f} chars")

    p("\nStatistiques des bundles:")
    avg_extracts = sum(r.bundle_quality.num_extracts for r in results) / len(results)
    avg_chars = sum(r.bundle_quality.total_chars for r in results) / len(results)
    p(f"  - Moyenne extraits/cas: {avg_extracts:.1f}")
    p(f"  - Moyenne chars/cas: {avg_chars:.0f}")

    # =========================================================================
    # SECTION 3: SCORES STRICT vs ÉPISTÉMIQUE
    # =========================================================================
    p("\n" + "=" * 80)
    p("SECTION 3: SCORES STRICT vs ÉPISTÉMIQUE")
    p("=" * 80)

    # Score strict
    strict_correct = sum(1 for r in results if r.is_match)
    strict_rate = strict_correct / total * 100

    # Score épistémique (ABSTAIN sur Type 2/Frontier = safe)
    epistemic_correct = sum(1 for r in results if r.is_safe)
    epistemic_rate = epistemic_correct / total * 100

    p(f"\nSCORE STRICT: {strict_correct}/{total} ({strict_rate:.1f}%)")
    p(f"  - Verdict exact match uniquement")

    p(f"\nSCORE ÉPISTÉMIQUE: {epistemic_correct}/{total} ({epistemic_rate:.1f}%)")
    p(f"  - ABSTAIN sur Type 2/Frontier compte comme safe")

    # =========================================================================
    # SECTION 4: ANALYSE PAR CATÉGORIE
    # =========================================================================
    p("\n" + "=" * 80)
    p("SECTION 4: ANALYSE PAR CATÉGORIE")
    p("=" * 80)

    # TYPE 1
    p("\n## TYPE 1 (Relations discursives - ACCEPT attendu)")
    type1_accept = sum(1 for r in type1_results if r.obtained == "ACCEPT")
    type1_reject = sum(1 for r in type1_results if r.obtained == "REJECT")
    type1_abstain = sum(1 for r in type1_results if r.obtained == "ABSTAIN")
    p(f"   Total: {len(type1_results)}")
    p(f"   ACCEPT (correct): {type1_accept}")
    p(f"   REJECT (incorrect): {type1_reject}")
    p(f"   ABSTAIN: {type1_abstain}")
    p(f"   Taux de réussite: {type1_accept/len(type1_results)*100:.1f}%")

    # TYPE 2
    p("\n## TYPE 2 (Relations déduites - REJECT attendu)")
    type2_accept = sum(1 for r in type2_results if r.obtained == "ACCEPT")
    type2_reject = sum(1 for r in type2_results if r.obtained == "REJECT")
    type2_abstain = sum(1 for r in type2_results if r.obtained == "ABSTAIN")
    p(f"   Total: {len(type2_results)}")
    p(f"   REJECT (correct): {type2_reject}")
    p(f"   ACCEPT (FAUX POSITIF): {type2_accept} {'*** CRITIQUE ***' if type2_accept > 0 else ''}")
    p(f"   ABSTAIN (safe): {type2_abstain}")
    p(f"   Taux strict: {type2_reject/len(type2_results)*100:.1f}%")
    p(f"   Taux épistémique: {(type2_reject+type2_abstain)/len(type2_results)*100:.1f}%")

    # FRONTIER
    p("\n## FRONTIER (Cas limites - REJECT attendu)")
    fr_accept = sum(1 for r in frontier_results if r.obtained == "ACCEPT")
    fr_reject = sum(1 for r in frontier_results if r.obtained == "REJECT")
    fr_abstain = sum(1 for r in frontier_results if r.obtained == "ABSTAIN")
    p(f"   Total: {len(frontier_results)}")
    p(f"   REJECT (correct): {fr_reject}")
    p(f"   ACCEPT (incorrect): {fr_accept} {'*** ATTENTION ***' if fr_accept > 0 else ''}")
    p(f"   ABSTAIN (acceptable): {fr_abstain}")
    p(f"   Taux strict: {fr_reject/len(frontier_results)*100:.1f}%")
    p(f"   Taux épistémique: {(fr_reject+fr_abstain)/len(frontier_results)*100:.1f}%")

    # =========================================================================
    # SECTION 5: OVERRIDES DÉTERMINISTES
    # =========================================================================
    p("\n" + "=" * 80)
    p("SECTION 5: OVERRIDES DÉTERMINISTES")
    p("=" * 80)

    overrides = [r for r in results if r.override_applied]
    p(f"\nNombre d'overrides appliqués: {len(overrides)}")
    for r in overrides:
        p(f"  - {r.case_id}: {r.override_reason}")

    # =========================================================================
    # SECTION 6: KPIs PRODUIT
    # =========================================================================
    p("\n" + "=" * 80)
    p("SECTION 6: KPIs PRODUIT")
    p("=" * 80)

    # KPI #1: Faux positifs Type 2
    fp_rate = type2_accept / len(type2_results) * 100 if type2_results else 0
    kpi1_pass = fp_rate <= 5
    p(f"\nKPI #1 - Faux positifs Type 2: {fp_rate:.1f}% {'✓ PASS' if kpi1_pass else '✗ FAIL'}")
    p(f"   (seuil: <= 5%, idéal: 0%)")

    # KPI #2: Comportement sur frontières
    frontier_accept = sum(1 for r in frontier_results if r.obtained == "ACCEPT")
    kpi2_pass = frontier_accept == 0
    p(f"\nKPI #2 - ACCEPT sur frontières: {frontier_accept} {'✓ PASS' if kpi2_pass else '✗ FAIL'}")
    p(f"   (ABSTAIN ou REJECT attendu sur HAS_EXACT avec 'or')")

    # KPI #3: Densité utile Type 1
    kpi3_rate = type1_accept / len(type1_results) * 100 if type1_results else 0
    kpi3_pass = kpi3_rate >= 80
    p(f"\nKPI #3 - Taux ACCEPT Type 1: {kpi3_rate:.1f}% {'✓ PASS' if kpi3_pass else '✗ FAIL'}")
    p(f"   (seuil: >= 80%)")

    # =========================================================================
    # VERDICT FINAL
    # =========================================================================
    p("\n" + "=" * 80)
    p("VERDICT FINAL")
    p("=" * 80)

    all_kpis_pass = kpi1_pass and kpi2_pass and kpi3_pass

    if all_kpis_pass:
        verdict = "SUCCESS"
        message = "Le KG peut être densifié sans contamination. Tous les KPIs sont respectés."
    elif kpi1_pass and kpi3_pass:
        verdict = "PARTIAL_SUCCESS"
        message = "Le KG est densifiable mais attention aux cas frontières."
    else:
        verdict = "FAILURE"
        message = "Risque de contamination du KG. Réviser les prédicats ou le prompt."

    p(f"\n   VERDICT: {verdict}")
    p(f"\n   {message}")
    p(f"\n   Score strict: {strict_rate:.1f}%")
    p(f"   Score épistémique: {epistemic_rate:.1f}%")

    p("\n" + "=" * 80)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="POC v4 Runner - ChatGPT Test Set")
    parser.add_argument("--mock", action="store_true", help="Mode mock (sans appel API)")
    parser.add_argument("--output-dir", default="./results", help="Répertoire de sortie")
    parser.add_argument("--quiet", action="store_true", help="Mode silencieux")
    args = parser.parse_args()

    if args.mock:
        print("Mode MOCK activé - pas d'appel API\n")

    # Créer le répertoire de sortie
    os.makedirs(args.output_dir, exist_ok=True)

    # Initialiser le discriminateur
    discriminator = DiscursiveDiscriminator()

    # Exécuter tous les cas
    results = []
    for i, tc in enumerate(ALL_TEST_CASES, 1):
        if not args.quiet:
            print(f"[{i}/{len(ALL_TEST_CASES)}] {tc.id}...", end=" ", flush=True)

        result = run_single_case(discriminator, tc, mock=args.mock)
        results.append(result)

        if not args.quiet:
            status = "OK" if result.is_match else "MISMATCH"
            safe = " (safe)" if result.is_safe and not result.is_match else ""
            print(f"{result.obtained} ({result.expected}) [{status}]{safe}")

    # Générer le rapport
    report = print_detailed_report(results)

    # Sauvegarder les résultats JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(args.output_dir, f"poc_v4_results_{timestamp}.json")

    output_data = {
        "timestamp": timestamp,
        "mode": "mock" if args.mock else "api",
        "total_cases": len(results),
        "results": [asdict(r) for r in results],
        "summary": {
            "type1": {
                "total": len([r for r in results if "TYPE1" in r.category]),
                "accept": sum(1 for r in results if "TYPE1" in r.category and r.obtained == "ACCEPT"),
                "reject": sum(1 for r in results if "TYPE1" in r.category and r.obtained == "REJECT"),
                "abstain": sum(1 for r in results if "TYPE1" in r.category and r.obtained == "ABSTAIN"),
            },
            "type2": {
                "total": len([r for r in results if "TYPE2" in r.category]),
                "accept": sum(1 for r in results if "TYPE2" in r.category and r.obtained == "ACCEPT"),
                "reject": sum(1 for r in results if "TYPE2" in r.category and r.obtained == "REJECT"),
                "abstain": sum(1 for r in results if "TYPE2" in r.category and r.obtained == "ABSTAIN"),
            },
            "frontier": {
                "total": len([r for r in results if "FRONTIER" in r.category]),
                "accept": sum(1 for r in results if "FRONTIER" in r.category and r.obtained == "ACCEPT"),
                "reject": sum(1 for r in results if "FRONTIER" in r.category and r.obtained == "REJECT"),
                "abstain": sum(1 for r in results if "FRONTIER" in r.category and r.obtained == "ABSTAIN"),
            },
            "scores": {
                "strict": sum(1 for r in results if r.is_match) / len(results) * 100,
                "epistemic": sum(1 for r in results if r.is_safe) / len(results) * 100,
            },
            "kpis": {
                "type2_false_positive_rate": sum(1 for r in results if "TYPE2" in r.category and r.obtained == "ACCEPT") / len([r for r in results if "TYPE2" in r.category]) * 100 if [r for r in results if "TYPE2" in r.category] else 0,
                "frontier_accepts": sum(1 for r in results if "FRONTIER" in r.category and r.obtained == "ACCEPT"),
                "type1_accept_rate": sum(1 for r in results if "TYPE1" in r.category and r.obtained == "ACCEPT") / len([r for r in results if "TYPE1" in r.category]) * 100 if [r for r in results if "TYPE1" in r.category] else 0,
            }
        }
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nRésultats sauvegardés dans: {output_file}")


if __name__ == "__main__":
    main()
