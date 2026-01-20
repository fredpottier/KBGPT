"""
POC Discursive Relation Discrimination - Runner v2

Ajustements v2:
- Import de test_cases_v2
- Metriques ajustees pour les frontieres (certains ACCEPT sont attendus)
- Comportement conservateur = ABSTAIN + REJECT (pas juste ABSTAIN)

ATTENTION: Code jetable, non destine a la production.
"""

import json
import os
import sys
from datetime import datetime
from typing import Optional

# Ajouter le chemin pour les imports locaux
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from models import (
    TestCase, TestCaseCategory, DiscriminationResult, TestSuiteResult,
    Verdict, POCVerdict, POCConclusion
)
from test_cases_v2 import get_all_test_cases, get_test_cases_by_category
from discriminator import DiscursiveDiscriminator


# =============================================================================
# SEUILS D'ECHEC v2 (Ajustes)
# =============================================================================

# Taux maximum de faux positifs Type 2 (acceptes alors qu'ils devraient etre rejetes)
MAX_TYPE2_FALSE_POSITIVE_RATE = 0.10  # 10%

# Pour les frontieres: on mesure le taux de verdicts CORRECTS (pas juste ABSTAIN)
MIN_FRONTIER_CORRECT_RATE = 0.60  # 60% des frontieres doivent avoir le bon verdict

# Nombre maximum de justifications sans citation (doit etre 0)
MAX_UNJUSTIFIED_ACCEPTS = 0


def is_verdict_correct(test_case: TestCase, result: DiscriminationResult) -> bool:
    """
    Determine si le verdict est correct pour un cas de test.
    """
    if result.verdict == test_case.expected_verdict:
        return True

    # Pour les frontieres ou ABSTAIN est attendu, REJECT est aussi acceptable
    # (comportement conservateur)
    if test_case.expected_verdict == Verdict.ABSTAIN and result.verdict == Verdict.REJECT:
        return True

    return False


class POCRunnerV2:
    """Execute le POC v2 et analyse les resultats."""

    def __init__(self, discriminator: Optional[DiscursiveDiscriminator] = None):
        self.discriminator = discriminator or DiscursiveDiscriminator()
        self.results: list[DiscriminationResult] = []

    def run_all_tests(self, verbose: bool = True) -> TestSuiteResult:
        test_cases = get_all_test_cases()

        if verbose:
            print(f"\n{'='*70}")
            print("POC v2 - DISCURSIVE RELATION DISCRIMINATION")
            print(f"{'='*70}")
            print(f"Nombre de cas de test: {len(test_cases)}")
            print(f"  - Type 1 (ACCEPT attendu): {len(get_test_cases_by_category(TestCaseCategory.CANONICAL_TYPE1))}")
            print(f"  - Type 2 (REJECT attendu): {len(get_test_cases_by_category(TestCaseCategory.CANONICAL_TYPE2))}")
            frontier_cases = get_test_cases_by_category(TestCaseCategory.FRONTIER)
            frontier_accept = sum(1 for tc in frontier_cases if tc.expected_verdict == Verdict.ACCEPT)
            frontier_abstain = sum(1 for tc in frontier_cases if tc.expected_verdict == Verdict.ABSTAIN)
            print(f"  - Frontieres: {len(frontier_cases)} ({frontier_accept} ACCEPT, {frontier_abstain} ABSTAIN attendus)")
            print(f"{'='*70}\n")

        self.results = []

        for i, test_case in enumerate(test_cases):
            if verbose:
                print(f"[{i+1}/{len(test_cases)}] {test_case.id}: {test_case.description[:50]}...")

            result = self.discriminator.discriminate(test_case)
            self.results.append(result)

            if verbose:
                correct = is_verdict_correct(test_case, result)
                status = "OK" if correct else "MISMATCH"
                extra = ""
                if test_case.expected_verdict == Verdict.ABSTAIN and result.verdict == Verdict.REJECT:
                    extra = " (REJECT acceptable)"
                print(f"         Verdict: {result.verdict.value} (attendu: {test_case.expected_verdict.value}) [{status}]{extra}")

        return self._compute_metrics(test_cases)

    def _compute_metrics(self, test_cases: list[TestCase]) -> TestSuiteResult:
        result_map = {r.test_case_id: r for r in self.results}

        suite = TestSuiteResult(
            total_cases=len(test_cases),
            results=self.results
        )

        # Compteurs specifiques v2
        frontier_correct = 0
        frontier_accept_when_expected = 0
        frontier_abstain_when_expected = 0

        for tc in test_cases:
            result = result_map.get(tc.id)
            if not result:
                continue

            if tc.category == TestCaseCategory.CANONICAL_TYPE1:
                suite.type1_total += 1
                if result.verdict == Verdict.ACCEPT:
                    suite.type1_correct_accept += 1
                elif result.verdict == Verdict.REJECT:
                    suite.type1_incorrect_reject += 1
                else:
                    suite.type1_abstain += 1

            elif tc.category == TestCaseCategory.CANONICAL_TYPE2:
                suite.type2_total += 1
                if result.verdict == Verdict.REJECT:
                    suite.type2_correct_reject += 1
                elif result.verdict == Verdict.ACCEPT:
                    suite.type2_incorrect_accept += 1
                else:
                    suite.type2_abstain += 1

            elif tc.category == TestCaseCategory.FRONTIER:
                suite.frontier_total += 1
                if result.verdict == Verdict.ABSTAIN:
                    suite.frontier_abstain += 1
                elif result.verdict == Verdict.ACCEPT:
                    suite.frontier_accept += 1
                else:
                    suite.frontier_reject += 1

                # Calculer si correct
                if is_verdict_correct(tc, result):
                    frontier_correct += 1
                    if tc.expected_verdict == Verdict.ACCEPT:
                        frontier_accept_when_expected += 1
                    elif tc.expected_verdict == Verdict.ABSTAIN:
                        frontier_abstain_when_expected += 1

            # Compter les justifications
            if result.verdict == Verdict.ACCEPT:
                if result.citations and len(result.citations) > 0:
                    suite.justifications_with_citations += 1
                else:
                    suite.justifications_without_citations += 1

        # Stocker les metriques v2 dans les champs existants (hack temporaire)
        # On reutilise frontier_abstain pour stocker frontier_correct
        self._frontier_correct = frontier_correct
        self._frontier_accept_when_expected = frontier_accept_when_expected
        self._frontier_abstain_when_expected = frontier_abstain_when_expected

        return suite


class POCAnalyzerV2:
    """Analyse les resultats v2."""

    def __init__(self, suite_result: TestSuiteResult, runner: POCRunnerV2):
        self.suite = suite_result
        self.runner = runner

    def analyze(self) -> POCConclusion:
        # Taux faux positifs Type 2
        type2_fp_rate = (
            self.suite.type2_incorrect_accept / self.suite.type2_total
            if self.suite.type2_total > 0 else 0.0
        )

        # Taux de verdicts corrects sur frontieres
        frontier_correct_rate = (
            self.runner._frontier_correct / self.suite.frontier_total
            if self.suite.frontier_total > 0 else 0.0
        )

        unjustified = self.suite.justifications_without_citations

        # Collecter les echecs critiques
        critical_failures = []

        if type2_fp_rate > MAX_TYPE2_FALSE_POSITIVE_RATE:
            critical_failures.append(
                f"Taux de faux positifs Type 2: {type2_fp_rate:.1%} > {MAX_TYPE2_FALSE_POSITIVE_RATE:.1%}"
            )

        if frontier_correct_rate < MIN_FRONTIER_CORRECT_RATE:
            critical_failures.append(
                f"Taux verdicts corrects frontieres: {frontier_correct_rate:.1%} < {MIN_FRONTIER_CORRECT_RATE:.1%}"
            )

        if unjustified > MAX_UNJUSTIFIED_ACCEPTS:
            critical_failures.append(
                f"Acceptations sans citation: {unjustified} > {MAX_UNJUSTIFIED_ACCEPTS}"
            )

        # Determiner le verdict
        if critical_failures:
            verdict = POCVerdict.FAILURE
            summary = "La distinction Type 1 / Type 2 n'est pas operable de maniere fiable."
        elif frontier_correct_rate < 0.80:
            verdict = POCVerdict.PARTIAL_SUCCESS
            summary = "Distinction partiellement operable. Ameliorations possibles."
        else:
            verdict = POCVerdict.SUCCESS
            summary = "La distinction est operable. Piste a approfondir (nouvel ADR requis)."

        recommendations = self._generate_recommendations(verdict, critical_failures)

        return POCConclusion(
            verdict=verdict,
            summary=summary,
            type2_false_positive_rate=type2_fp_rate,
            unjustified_accepts=unjustified,
            frontier_correct_rate=frontier_correct_rate,
            frontier_abstain_count=self.suite.frontier_abstain,
            critical_failures=critical_failures,
            recommendations=recommendations
        )

    def _generate_recommendations(self, verdict: POCVerdict, failures: list[str]) -> list[str]:
        if verdict == POCVerdict.FAILURE:
            return [
                "Analyser les cas en echec pour identifier les patterns",
                "Envisager des checks deterministes post-LLM",
                "Si echec persiste: confirmer pivot Evidence Graph"
            ]
        elif verdict == POCVerdict.PARTIAL_SUCCESS:
            return [
                "La distinction fonctionne sur les cas bien specifies",
                "Ajuster les prompts pour ameliorer les cas frontiere",
                "Considerer des checks quantificateurs/alternatives"
            ]
        else:
            return [
                "La distinction Type 1 / Type 2 est operationnellement viable",
                "Creer un nouvel ADR pour definir l'integration eventuelle",
                "ATTENTION: Cette couche NE DOIT JAMAIS contaminer la couche Evidence"
            ]

    def print_report(self) -> None:
        print(f"\n{'='*70}")
        print("RAPPORT D'ANALYSE POC v2")
        print(f"{'='*70}")

        # Type 1
        print(f"\n## TYPE 1 (Relations discursives - ACCEPT attendu)")
        print(f"   Total: {self.suite.type1_total}")
        print(f"   Correctement acceptes: {self.suite.type1_correct_accept}")
        print(f"   Incorrectement rejetes: {self.suite.type1_incorrect_reject}")
        print(f"   Abstentions: {self.suite.type1_abstain}")

        # Type 2
        print(f"\n## TYPE 2 (Relations deduites - REJECT attendu)")
        print(f"   Total: {self.suite.type2_total}")
        print(f"   Correctement rejetes: {self.suite.type2_correct_reject}")
        print(f"   FAUX POSITIFS (acceptes): {self.suite.type2_incorrect_accept} *** CRITIQUE ***")
        print(f"   Abstentions: {self.suite.type2_abstain}")

        # Frontieres v2
        print(f"\n## FRONTIERES (verdicts attendus variables)")
        print(f"   Total: {self.suite.frontier_total}")
        print(f"   Verdicts corrects: {self.runner._frontier_correct}")
        print(f"   - ACCEPT quand attendu: {self.runner._frontier_accept_when_expected}")
        print(f"   - ABSTAIN/REJECT quand ABSTAIN attendu: {self.runner._frontier_abstain_when_expected}")
        print(f"   Distribution reelle: {self.suite.frontier_accept} ACCEPT, {self.suite.frontier_abstain} ABSTAIN, {self.suite.frontier_reject} REJECT")

        # Justifications
        print(f"\n## QUALITE DES JUSTIFICATIONS")
        print(f"   Avec citations: {self.suite.justifications_with_citations}")
        print(f"   Sans citations: {self.suite.justifications_without_citations}")

        # Conclusion
        conclusion = self.analyze()

        print(f"\n{'='*70}")
        print("CONCLUSION DU POC v2")
        print(f"{'='*70}")

        print(f"\n   VERDICT: {conclusion.verdict.value}")
        print(f"\n   {conclusion.summary}")

        if conclusion.critical_failures:
            print(f"\n   ECHECS CRITIQUES:")
            for failure in conclusion.critical_failures:
                print(f"   - {failure}")

        type2_fp = self.suite.type2_incorrect_accept / self.suite.type2_total if self.suite.type2_total > 0 else 0
        frontier_correct = self.runner._frontier_correct / self.suite.frontier_total if self.suite.frontier_total > 0 else 0

        print(f"\n   METRIQUES CLES:")
        print(f"   - Taux faux positifs Type 2: {type2_fp:.1%} (max: {MAX_TYPE2_FALSE_POSITIVE_RATE:.1%})")
        print(f"   - Taux verdicts corrects frontieres: {frontier_correct:.1%} (min: {MIN_FRONTIER_CORRECT_RATE:.1%})")
        print(f"   - Nombre reel d'ABSTAIN: {self.suite.frontier_abstain}")
        print(f"   - Acceptations sans citation: {conclusion.unjustified_accepts} (max: {MAX_UNJUSTIFIED_ACCEPTS})")

        print(f"\n   RECOMMENDATIONS:")
        for rec in conclusion.recommendations:
            print(f"   - {rec}")

        print(f"\n{'='*70}")


def save_results(suite: TestSuiteResult, conclusion: POCConclusion, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"poc_v2_results_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    output = {
        "version": "v2",
        "timestamp": timestamp,
        "suite_result": suite.model_dump(),
        "conclusion": conclusion.model_dump()
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return filepath


def main():
    import argparse

    parser = argparse.ArgumentParser(description="POC v2 Discursive Relation Discrimination")
    parser.add_argument("--mock", action="store_true", help="Mode mock (sans appel API)")
    parser.add_argument("--output-dir", default="./results", help="Repertoire de sortie")
    parser.add_argument("--quiet", action="store_true", help="Mode silencieux")

    args = parser.parse_args()

    if args.mock:
        print("Mode MOCK active - pas d'appel API")
        discriminator = DiscursiveDiscriminator(api_key=None)
    else:
        discriminator = DiscursiveDiscriminator()

    runner = POCRunnerV2(discriminator)
    suite_result = runner.run_all_tests(verbose=not args.quiet)

    analyzer = POCAnalyzerV2(suite_result, runner)

    if not args.quiet:
        analyzer.print_report()

    conclusion = analyzer.analyze()
    filepath = save_results(suite_result, conclusion, args.output_dir)
    print(f"\nResultats sauvegardes dans: {filepath}")

    if conclusion.verdict == POCVerdict.FAILURE:
        sys.exit(1)
    elif conclusion.verdict == POCVerdict.PARTIAL_SUCCESS:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
