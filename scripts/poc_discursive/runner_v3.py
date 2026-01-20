"""
POC Discursive Relation Discrimination - Runner v3 (Final)

Version finale du POC avec:
- 48 cas de test sur 3 documents (RISE, Conversion Guide, Operations Guide)
- Metriques par document
- Analyse detaillee Type 1 vs Type 2

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
from test_cases_v3 import (
    get_all_test_cases, get_test_cases_by_category,
    ALL_RISE_CASES, ALL_CONVERSION_CASES, ALL_OPERATIONS_CASES,
    ALL_TYPE1_CASES, ALL_TYPE2_CASES,
    DOC_RISE, DOC_CONVERSION, DOC_OPERATIONS
)
from discriminator import DiscursiveDiscriminator


# =============================================================================
# SEUILS D'ECHEC v3
# =============================================================================

# Taux maximum de faux positifs Type 2 (acceptes alors qu'ils devraient etre rejetes)
MAX_TYPE2_FALSE_POSITIVE_RATE = 0.10  # 10%

# Taux minimum de Type 1 correctement acceptes
MIN_TYPE1_ACCEPT_RATE = 0.80  # 80%

# Nombre maximum de justifications sans citation (doit etre 0)
MAX_UNJUSTIFIED_ACCEPTS = 0


def is_verdict_correct(test_case: TestCase, result: DiscriminationResult) -> bool:
    """Determine si le verdict est correct pour un cas de test."""
    return result.verdict == test_case.expected_verdict


class DocumentMetrics:
    """Metriques pour un document specifique."""
    def __init__(self, name: str):
        self.name = name
        self.total = 0
        self.type1_total = 0
        self.type1_correct = 0
        self.type2_total = 0
        self.type2_correct = 0

    @property
    def type1_rate(self) -> float:
        return self.type1_correct / self.type1_total if self.type1_total > 0 else 0.0

    @property
    def type2_rate(self) -> float:
        return self.type2_correct / self.type2_total if self.type2_total > 0 else 0.0

    @property
    def overall_rate(self) -> float:
        total_correct = self.type1_correct + self.type2_correct
        return total_correct / self.total if self.total > 0 else 0.0


class POCRunnerV3:
    """Execute le POC v3 et analyse les resultats."""

    def __init__(self, discriminator: Optional[DiscursiveDiscriminator] = None):
        self.discriminator = discriminator or DiscursiveDiscriminator()
        self.results: list[DiscriminationResult] = []

        # Metriques par document
        self.doc_metrics = {
            "RISE": DocumentMetrics("RISE (doc 020)"),
            "CONV": DocumentMetrics("Conversion Guide (doc 010)"),
            "OPS": DocumentMetrics("Operations Guide (doc 017)")
        }

    def _get_doc_key(self, test_case: TestCase) -> str:
        """Retourne la cle du document pour un cas de test."""
        if "RISE" in test_case.id:
            return "RISE"
        elif "CONV" in test_case.id:
            return "CONV"
        else:
            return "OPS"

    def run_all_tests(self, verbose: bool = True) -> TestSuiteResult:
        test_cases = get_all_test_cases()

        if verbose:
            print(f"\n{'='*70}")
            print("POC v3 - DISCURSIVE RELATION DISCRIMINATION (FINAL)")
            print(f"{'='*70}")
            print(f"Nombre total de cas: {len(test_cases)}")
            print(f"  - Type 1 (ACCEPT attendu): {len(ALL_TYPE1_CASES)}")
            print(f"  - Type 2 (REJECT attendu): {len(ALL_TYPE2_CASES)}")
            print(f"\nPar document:")
            print(f"  - RISE: {len(ALL_RISE_CASES)} cas")
            print(f"  - Conversion Guide: {len(ALL_CONVERSION_CASES)} cas")
            print(f"  - Operations Guide: {len(ALL_OPERATIONS_CASES)} cas")
            print(f"{'='*70}\n")

        self.results = []

        for i, test_case in enumerate(test_cases):
            if verbose:
                doc_key = self._get_doc_key(test_case)
                print(f"[{i+1}/{len(test_cases)}] [{doc_key}] {test_case.id}: {test_case.description[:45]}...")

            result = self.discriminator.discriminate(test_case)
            self.results.append(result)

            if verbose:
                correct = is_verdict_correct(test_case, result)
                status = "OK" if correct else "MISMATCH"
                print(f"         Verdict: {result.verdict.value} (attendu: {test_case.expected_verdict.value}) [{status}]")

        return self._compute_metrics(test_cases)

    def _compute_metrics(self, test_cases: list[TestCase]) -> TestSuiteResult:
        result_map = {r.test_case_id: r for r in self.results}

        suite = TestSuiteResult(
            total_cases=len(test_cases),
            results=self.results
        )

        for tc in test_cases:
            result = result_map.get(tc.id)
            if not result:
                continue

            doc_key = self._get_doc_key(tc)
            doc_metrics = self.doc_metrics[doc_key]
            doc_metrics.total += 1

            if tc.category == TestCaseCategory.CANONICAL_TYPE1:
                suite.type1_total += 1
                doc_metrics.type1_total += 1
                if result.verdict == Verdict.ACCEPT:
                    suite.type1_correct_accept += 1
                    doc_metrics.type1_correct += 1
                elif result.verdict == Verdict.REJECT:
                    suite.type1_incorrect_reject += 1
                else:
                    suite.type1_abstain += 1

            elif tc.category == TestCaseCategory.CANONICAL_TYPE2:
                suite.type2_total += 1
                doc_metrics.type2_total += 1
                if result.verdict == Verdict.REJECT:
                    suite.type2_correct_reject += 1
                    doc_metrics.type2_correct += 1
                elif result.verdict == Verdict.ACCEPT:
                    suite.type2_incorrect_accept += 1
                else:
                    suite.type2_abstain += 1

            # Compter les justifications
            if result.verdict == Verdict.ACCEPT:
                if result.citations and len(result.citations) > 0:
                    suite.justifications_with_citations += 1
                else:
                    suite.justifications_without_citations += 1

        return suite


class POCAnalyzerV3:
    """Analyse les resultats v3."""

    def __init__(self, suite_result: TestSuiteResult, runner: POCRunnerV3):
        self.suite = suite_result
        self.runner = runner

    def analyze(self) -> POCConclusion:
        # Taux faux positifs Type 2
        type2_fp_rate = (
            self.suite.type2_incorrect_accept / self.suite.type2_total
            if self.suite.type2_total > 0 else 0.0
        )

        # Taux Type 1 corrects
        type1_rate = (
            self.suite.type1_correct_accept / self.suite.type1_total
            if self.suite.type1_total > 0 else 0.0
        )

        unjustified = self.suite.justifications_without_citations

        # Collecter les echecs critiques
        critical_failures = []

        if type2_fp_rate > MAX_TYPE2_FALSE_POSITIVE_RATE:
            critical_failures.append(
                f"Taux de faux positifs Type 2: {type2_fp_rate:.1%} > {MAX_TYPE2_FALSE_POSITIVE_RATE:.1%}"
            )

        if type1_rate < MIN_TYPE1_ACCEPT_RATE:
            critical_failures.append(
                f"Taux Type 1 corrects: {type1_rate:.1%} < {MIN_TYPE1_ACCEPT_RATE:.1%}"
            )

        if unjustified > MAX_UNJUSTIFIED_ACCEPTS:
            critical_failures.append(
                f"Acceptations sans citation: {unjustified} > {MAX_UNJUSTIFIED_ACCEPTS}"
            )

        # Calculer taux global
        total_correct = self.suite.type1_correct_accept + self.suite.type2_correct_reject
        total = self.suite.type1_total + self.suite.type2_total
        global_rate = total_correct / total if total > 0 else 0.0

        # Determiner le verdict
        if critical_failures:
            verdict = POCVerdict.FAILURE
            summary = "La distinction Type 1 / Type 2 n'est pas operable de maniere fiable."
        elif global_rate < 0.85:
            verdict = POCVerdict.PARTIAL_SUCCESS
            summary = f"Distinction partiellement operable ({global_rate:.1%}). Ameliorations possibles."
        else:
            verdict = POCVerdict.SUCCESS
            summary = f"La distinction est operable ({global_rate:.1%}). Recommandation: poursuivre avec le KG."

        recommendations = self._generate_recommendations(verdict, critical_failures, global_rate)

        return POCConclusion(
            verdict=verdict,
            summary=summary,
            type2_false_positive_rate=type2_fp_rate,
            unjustified_accepts=unjustified,
            frontier_correct_rate=global_rate,  # Reutilise pour le taux global
            frontier_abstain_count=self.suite.type1_abstain + self.suite.type2_abstain,
            critical_failures=critical_failures,
            recommendations=recommendations
        )

    def _generate_recommendations(self, verdict: POCVerdict, failures: list[str], global_rate: float) -> list[str]:
        if verdict == POCVerdict.FAILURE:
            return [
                "Analyser les cas en echec pour identifier les patterns problematiques",
                "Envisager des checks deterministes supplementaires post-LLM",
                "Si echec persiste: confirmer que le KG ne peut discriminer fiablement"
            ]
        elif verdict == POCVerdict.PARTIAL_SUCCESS:
            return [
                f"La distinction fonctionne a {global_rate:.1%} sur 48 cas",
                "Ajuster les prompts pour les patterns mal geres",
                "Considerer l'ajout de regles deterministes pour les alternatives ('or')",
                "Le KG reste pertinent mais necessite des ameliorations"
            ]
        else:
            return [
                f"La distinction Type 1 / Type 2 est operationnellement viable ({global_rate:.1%})",
                "RECOMMANDATION: Poursuivre le developpement du Knowledge Graph",
                "Le systeme discrimine correctement les relations discursives vs deduites",
                "Prochaine etape: integration dans le pipeline OSMOSE"
            ]

    def print_report(self) -> None:
        print(f"\n{'='*70}")
        print("RAPPORT D'ANALYSE POC v3 (FINAL)")
        print(f"{'='*70}")

        # Type 1
        print(f"\n## TYPE 1 (Relations discursives - ACCEPT attendu)")
        print(f"   Total: {self.suite.type1_total}")
        print(f"   Correctement acceptes: {self.suite.type1_correct_accept}")
        print(f"   Incorrectement rejetes: {self.suite.type1_incorrect_reject}")
        print(f"   Abstentions: {self.suite.type1_abstain}")
        type1_rate = self.suite.type1_correct_accept / self.suite.type1_total if self.suite.type1_total > 0 else 0
        print(f"   Taux de reussite: {type1_rate:.1%}")

        # Type 2
        print(f"\n## TYPE 2 (Relations deduites - REJECT attendu)")
        print(f"   Total: {self.suite.type2_total}")
        print(f"   Correctement rejetes: {self.suite.type2_correct_reject}")
        print(f"   FAUX POSITIFS (acceptes): {self.suite.type2_incorrect_accept} *** CRITIQUE ***")
        print(f"   Abstentions: {self.suite.type2_abstain}")
        type2_rate = self.suite.type2_correct_reject / self.suite.type2_total if self.suite.type2_total > 0 else 0
        print(f"   Taux de reussite: {type2_rate:.1%}")

        # Par document
        print(f"\n## RESULTATS PAR DOCUMENT")
        for key, metrics in self.runner.doc_metrics.items():
            if metrics.total > 0:
                print(f"\n   {metrics.name}:")
                print(f"      Total: {metrics.total} cas")
                print(f"      Type 1: {metrics.type1_correct}/{metrics.type1_total} ({metrics.type1_rate:.1%})")
                print(f"      Type 2: {metrics.type2_correct}/{metrics.type2_total} ({metrics.type2_rate:.1%})")
                print(f"      Global: {metrics.overall_rate:.1%}")

        # Justifications
        print(f"\n## QUALITE DES JUSTIFICATIONS")
        print(f"   Avec citations: {self.suite.justifications_with_citations}")
        print(f"   Sans citations: {self.suite.justifications_without_citations}")

        # Conclusion
        conclusion = self.analyze()

        print(f"\n{'='*70}")
        print("CONCLUSION DU POC v3 (FINAL)")
        print(f"{'='*70}")

        print(f"\n   VERDICT: {conclusion.verdict.value}")
        print(f"\n   {conclusion.summary}")

        if conclusion.critical_failures:
            print(f"\n   ECHECS CRITIQUES:")
            for failure in conclusion.critical_failures:
                print(f"   - {failure}")

        type2_fp = self.suite.type2_incorrect_accept / self.suite.type2_total if self.suite.type2_total > 0 else 0
        total_correct = self.suite.type1_correct_accept + self.suite.type2_correct_reject
        total = self.suite.type1_total + self.suite.type2_total
        global_rate = total_correct / total if total > 0 else 0

        print(f"\n   METRIQUES CLES:")
        print(f"   - Taux global de reussite: {global_rate:.1%}")
        print(f"   - Taux Type 1 (ACCEPT): {type1_rate:.1%} (min: {MIN_TYPE1_ACCEPT_RATE:.1%})")
        print(f"   - Taux faux positifs Type 2: {type2_fp:.1%} (max: {MAX_TYPE2_FALSE_POSITIVE_RATE:.1%})")
        print(f"   - Acceptations sans citation: {conclusion.unjustified_accepts} (max: {MAX_UNJUSTIFIED_ACCEPTS})")

        print(f"\n   RECOMMENDATIONS:")
        for rec in conclusion.recommendations:
            print(f"   - {rec}")

        print(f"\n{'='*70}")


def save_results(suite: TestSuiteResult, conclusion: POCConclusion, runner: POCRunnerV3, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"poc_v3_results_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    # Preparer les metriques par document
    doc_metrics_dict = {}
    for key, metrics in runner.doc_metrics.items():
        doc_metrics_dict[key] = {
            "name": metrics.name,
            "total": metrics.total,
            "type1_total": metrics.type1_total,
            "type1_correct": metrics.type1_correct,
            "type1_rate": metrics.type1_rate,
            "type2_total": metrics.type2_total,
            "type2_correct": metrics.type2_correct,
            "type2_rate": metrics.type2_rate,
            "overall_rate": metrics.overall_rate
        }

    output = {
        "version": "v3",
        "timestamp": timestamp,
        "suite_result": suite.model_dump(),
        "document_metrics": doc_metrics_dict,
        "conclusion": conclusion.model_dump()
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return filepath


def main():
    import argparse

    parser = argparse.ArgumentParser(description="POC v3 Discursive Relation Discrimination (Final)")
    parser.add_argument("--mock", action="store_true", help="Mode mock (sans appel API)")
    parser.add_argument("--output-dir", default="./results", help="Repertoire de sortie")
    parser.add_argument("--quiet", action="store_true", help="Mode silencieux")

    args = parser.parse_args()

    if args.mock:
        print("Mode MOCK active - pas d'appel API")
        discriminator = DiscursiveDiscriminator(api_key=None)
    else:
        discriminator = DiscursiveDiscriminator()

    runner = POCRunnerV3(discriminator)
    suite_result = runner.run_all_tests(verbose=not args.quiet)

    analyzer = POCAnalyzerV3(suite_result, runner)

    if not args.quiet:
        analyzer.print_report()

    conclusion = analyzer.analyze()
    filepath = save_results(suite_result, conclusion, runner, args.output_dir)
    print(f"\nResultats sauvegardes dans: {filepath}")

    if conclusion.verdict == POCVerdict.FAILURE:
        sys.exit(1)
    elif conclusion.verdict == POCVerdict.PARTIAL_SUCCESS:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
