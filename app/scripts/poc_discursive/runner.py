"""
POC Discursive Relation Discrimination - Runner et Analyseur

Ce module execute la suite de tests et analyse les resultats
selon les criteres d'echec definis dans l'ADR.

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
from test_cases import get_all_test_cases, get_test_cases_by_category
from discriminator import DiscursiveDiscriminator


# =============================================================================
# SEUILS D'ECHEC (Definis dans l'ADR)
# =============================================================================

# Taux maximum de faux positifs Type 2 (acceptes alors qu'ils devraient etre rejetes)
MAX_TYPE2_FALSE_POSITIVE_RATE = 0.10  # 10%

# Taux minimum d'ABSTAIN sur les cas frontieres
MIN_FRONTIER_ABSTAIN_RATE = 0.40  # 40% (inverse: max 60% de decisions fermes)

# Nombre maximum de justifications sans citation (doit etre 0)
MAX_UNJUSTIFIED_ACCEPTS = 0

# Cas frontieres acceptant plusieurs verdicts (ABSTAIN ou REJECT)
# TC-FR-04: "not recommended" != "not supported" - REJECT est aussi acceptable
FRONTIER_ACCEPTS_REJECT = {"TC-FR-04"}


def is_verdict_acceptable(test_case: TestCase, result: DiscriminationResult) -> bool:
    """
    Determine si le verdict est acceptable pour un cas de test.

    Pour la plupart des cas, le verdict doit correspondre exactement.
    Pour certains cas frontieres (TC-FR-04), REJECT est aussi acceptable.
    """
    if result.verdict == test_case.expected_verdict:
        return True

    # Cas special: certains frontieres acceptent REJECT en plus d'ABSTAIN
    if test_case.id in FRONTIER_ACCEPTS_REJECT:
        if test_case.expected_verdict == Verdict.ABSTAIN and result.verdict == Verdict.REJECT:
            return True

    return False


class POCRunner:
    """Execute le POC et analyse les resultats."""

    def __init__(self, discriminator: Optional[DiscursiveDiscriminator] = None):
        """
        Initialise le runner.

        Args:
            discriminator: Instance du discriminateur (cree par defaut si absent)
        """
        self.discriminator = discriminator or DiscursiveDiscriminator()
        self.results: list[DiscriminationResult] = []

    def run_all_tests(self, verbose: bool = True) -> TestSuiteResult:
        """
        Execute tous les cas de test.

        Args:
            verbose: Afficher la progression

        Returns:
            TestSuiteResult avec tous les resultats et metriques
        """
        test_cases = get_all_test_cases()

        if verbose:
            print(f"\n{'='*70}")
            print("POC DISCURSIVE RELATION DISCRIMINATION")
            print(f"{'='*70}")
            print(f"Nombre de cas de test: {len(test_cases)}")
            print(f"  - Type 1 (ACCEPT attendu): {len(get_test_cases_by_category(TestCaseCategory.CANONICAL_TYPE1))}")
            print(f"  - Type 2 (REJECT attendu): {len(get_test_cases_by_category(TestCaseCategory.CANONICAL_TYPE2))}")
            print(f"  - Frontieres (ABSTAIN attendu): {len(get_test_cases_by_category(TestCaseCategory.FRONTIER))}")
            print(f"{'='*70}\n")

        self.results = []

        for i, test_case in enumerate(test_cases):
            if verbose:
                print(f"[{i+1}/{len(test_cases)}] {test_case.id}: {test_case.description[:50]}...")

            result = self.discriminator.discriminate(test_case)
            self.results.append(result)

            if verbose:
                acceptable = is_verdict_acceptable(test_case, result)
                status = "OK" if acceptable else "MISMATCH"
                extra = ""
                if test_case.id in FRONTIER_ACCEPTS_REJECT and result.verdict == Verdict.REJECT:
                    extra = " (REJECT acceptable pour ce cas)"
                print(f"         Verdict: {result.verdict.value} (attendu: {test_case.expected_verdict.value}) [{status}]{extra}")

        return self._compute_metrics(test_cases)

    def _compute_metrics(self, test_cases: list[TestCase]) -> TestSuiteResult:
        """Calcule les metriques de la suite de tests."""

        # Creer le mapping cas -> resultat
        result_map = {r.test_case_id: r for r in self.results}

        # Initialiser les compteurs
        suite = TestSuiteResult(
            total_cases=len(test_cases),
            results=self.results
        )

        # Compter par categorie
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
                    suite.type2_incorrect_accept += 1  # CRITIQUE
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

            # Compter les justifications
            if result.verdict == Verdict.ACCEPT:
                if result.citations and len(result.citations) > 0:
                    suite.justifications_with_citations += 1
                else:
                    suite.justifications_without_citations += 1

        return suite


class POCAnalyzer:
    """Analyse les resultats et determine le verdict du POC."""

    def __init__(self, suite_result: TestSuiteResult):
        """
        Initialise l'analyseur.

        Args:
            suite_result: Resultats de la suite de tests
        """
        self.suite = suite_result

    def analyze(self) -> POCConclusion:
        """
        Analyse les resultats et retourne la conclusion du POC.

        Returns:
            POCConclusion avec verdict et recommendations
        """
        # Calculer les taux critiques
        type2_fp_rate = (
            self.suite.type2_incorrect_accept / self.suite.type2_total
            if self.suite.type2_total > 0 else 0.0
        )

        frontier_abstain_rate = (
            self.suite.frontier_abstain / self.suite.frontier_total
            if self.suite.frontier_total > 0 else 0.0
        )

        unjustified = self.suite.justifications_without_citations

        # Collecter les echecs critiques
        critical_failures = []

        if type2_fp_rate > MAX_TYPE2_FALSE_POSITIVE_RATE:
            critical_failures.append(
                f"Taux de faux positifs Type 2: {type2_fp_rate:.1%} > {MAX_TYPE2_FALSE_POSITIVE_RATE:.1%}"
            )

        if frontier_abstain_rate < MIN_FRONTIER_ABSTAIN_RATE:
            critical_failures.append(
                f"Taux d'abstention frontieres: {frontier_abstain_rate:.1%} < {MIN_FRONTIER_ABSTAIN_RATE:.1%}"
            )

        if unjustified > MAX_UNJUSTIFIED_ACCEPTS:
            critical_failures.append(
                f"Acceptations sans citation: {unjustified} > {MAX_UNJUSTIFIED_ACCEPTS}"
            )

        # Determiner le verdict
        if critical_failures:
            verdict = POCVerdict.FAILURE
            summary = "La distinction Type 1 / Type 2 n'est pas operable de maniere fiable."
        elif frontier_abstain_rate > 0.80:
            verdict = POCVerdict.PARTIAL_SUCCESS
            summary = "Distinction possible mais systeme trop conservateur. Valeur ajoutee incertaine."
        else:
            verdict = POCVerdict.SUCCESS
            summary = "La distinction est operable. Piste a approfondir (nouvel ADR requis)."

        # Generer les recommendations
        recommendations = self._generate_recommendations(verdict, critical_failures)

        return POCConclusion(
            verdict=verdict,
            summary=summary,
            type2_false_positive_rate=type2_fp_rate,
            frontier_abstain_rate=frontier_abstain_rate,
            unjustified_accepts=unjustified,
            critical_failures=critical_failures,
            recommendations=recommendations
        )

    def _generate_recommendations(
        self,
        verdict: POCVerdict,
        failures: list[str]
    ) -> list[str]:
        """Genere les recommendations basees sur le verdict."""

        if verdict == POCVerdict.FAILURE:
            return [
                "Abandonner cette piste sans regret",
                "Confirmer le pivot Evidence Graph comme seule voie viable",
                "Archiver ce POC avec les resultats pour documentation"
            ]

        elif verdict == POCVerdict.PARTIAL_SUCCESS:
            return [
                "Le systeme est fonctionnel mais tres conservateur",
                "Evaluer si la valeur ajoutee justifie un investissement supplementaire",
                "Possibilite: ajuster les prompts pour reduire la prudence excessive"
            ]

        else:  # SUCCESS
            return [
                "La distinction Type 1 / Type 2 est operationnellement viable",
                "Creer un nouvel ADR pour definir l'integration eventuelle au produit",
                "ATTENTION: Cette couche NE DOIT JAMAIS contaminer la couche Evidence",
                "Definir clairement le statut epistemique de ces relations (non-prouvees)"
            ]

    def print_report(self) -> None:
        """Affiche un rapport complet des resultats."""

        print(f"\n{'='*70}")
        print("RAPPORT D'ANALYSE POC")
        print(f"{'='*70}")

        # Metriques Type 1
        print(f"\n## TYPE 1 (Relations discursives - ACCEPT attendu)")
        print(f"   Total: {self.suite.type1_total}")
        print(f"   Correctement acceptes: {self.suite.type1_correct_accept}")
        print(f"   Incorrectement rejetes: {self.suite.type1_incorrect_reject}")
        print(f"   Abstentions: {self.suite.type1_abstain}")

        # Metriques Type 2
        print(f"\n## TYPE 2 (Relations deduites - REJECT attendu)")
        print(f"   Total: {self.suite.type2_total}")
        print(f"   Correctement rejetes: {self.suite.type2_correct_reject}")
        print(f"   FAUX POSITIFS (acceptes): {self.suite.type2_incorrect_accept} *** CRITIQUE ***")
        print(f"   Abstentions: {self.suite.type2_abstain}")

        # Metriques Frontieres
        print(f"\n## FRONTIERES (ABSTAIN attendu majoritairement)")
        print(f"   Total: {self.suite.frontier_total}")
        print(f"   Abstentions: {self.suite.frontier_abstain}")
        print(f"   Acceptes: {self.suite.frontier_accept}")
        print(f"   Rejetes: {self.suite.frontier_reject}")

        # Justifications
        print(f"\n## QUALITE DES JUSTIFICATIONS")
        print(f"   Avec citations: {self.suite.justifications_with_citations}")
        print(f"   Sans citations: {self.suite.justifications_without_citations} *** CRITIQUE si > 0 ***")

        # Conclusion
        conclusion = self.analyze()

        print(f"\n{'='*70}")
        print("CONCLUSION DU POC")
        print(f"{'='*70}")

        print(f"\n   VERDICT: {conclusion.verdict.value}")
        print(f"\n   {conclusion.summary}")

        if conclusion.critical_failures:
            print(f"\n   ECHECS CRITIQUES:")
            for failure in conclusion.critical_failures:
                print(f"   - {failure}")

        print(f"\n   METRIQUES CLES:")
        print(f"   - Taux faux positifs Type 2: {conclusion.type2_false_positive_rate:.1%} (max: {MAX_TYPE2_FALSE_POSITIVE_RATE:.1%})")
        print(f"   - Taux abstention frontieres: {conclusion.frontier_abstain_rate:.1%} (min: {MIN_FRONTIER_ABSTAIN_RATE:.1%})")
        print(f"   - Acceptations sans citation: {conclusion.unjustified_accepts} (max: {MAX_UNJUSTIFIED_ACCEPTS})")

        print(f"\n   RECOMMENDATIONS:")
        for rec in conclusion.recommendations:
            print(f"   - {rec}")

        print(f"\n{'='*70}")


def save_results(suite: TestSuiteResult, conclusion: POCConclusion, output_dir: str) -> str:
    """
    Sauvegarde les resultats dans un fichier JSON.

    Args:
        suite: Resultats de la suite de tests
        conclusion: Conclusion du POC
        output_dir: Repertoire de sortie

    Returns:
        Chemin du fichier de sortie
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"poc_results_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    output = {
        "timestamp": timestamp,
        "suite_result": suite.model_dump(),
        "conclusion": conclusion.model_dump()
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return filepath


def main():
    """Point d'entree principal du POC."""
    import argparse

    parser = argparse.ArgumentParser(description="POC Discursive Relation Discrimination")
    parser.add_argument("--mock", action="store_true", help="Mode mock (sans appel API)")
    parser.add_argument("--output-dir", default="./results", help="Repertoire de sortie")
    parser.add_argument("--quiet", action="store_true", help="Mode silencieux")

    args = parser.parse_args()

    # Creer le discriminateur
    if args.mock:
        print("Mode MOCK active - pas d'appel API")
        discriminator = DiscursiveDiscriminator(api_key=None)
    else:
        discriminator = DiscursiveDiscriminator()

    # Executer les tests
    runner = POCRunner(discriminator)
    suite_result = runner.run_all_tests(verbose=not args.quiet)

    # Analyser les resultats
    analyzer = POCAnalyzer(suite_result)

    if not args.quiet:
        analyzer.print_report()

    # Sauvegarder les resultats
    conclusion = analyzer.analyze()
    filepath = save_results(suite_result, conclusion, args.output_dir)
    print(f"\nResultats sauvegardes dans: {filepath}")

    # Code de sortie base sur le verdict
    if conclusion.verdict == POCVerdict.FAILURE:
        sys.exit(1)
    elif conclusion.verdict == POCVerdict.PARTIAL_SUCCESS:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
