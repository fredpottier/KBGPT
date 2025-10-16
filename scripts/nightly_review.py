#!/usr/bin/env python3
"""
Script de Revue Nocturne - Analyse complète du projet.

Fonctionnalités:
- Code Review (qualité, dead code, complexité)
- Test Analysis (couverture, tests manquants)
- Frontend Validation (API endpoints, santé services)
- DB Safety (snapshots avant tests)
- Rapport HTML/JSON complet

Usage:
    python scripts/nightly_review.py [OPTIONS]

Options:
    --skip-tests        Skip test execution
    --skip-frontend     Skip frontend validation
    --skip-db-safety    Skip database snapshots
    --html-only         Generate HTML report from last JSON
    --help              Show this help message

Exemple:
    python scripts/nightly_review.py
    python scripts/nightly_review.py --skip-tests
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime
import webbrowser

# Ajouter le répertoire parent au path pour imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Modules avec analyse Claude (intelligente)
from scripts.nightly_review.modules.code_reviewer_claude import run_code_review_with_claude
from scripts.nightly_review.modules.architecture_analyzer_claude import run_architecture_analysis_with_claude
from scripts.nightly_review.modules.test_analyzer_claude import run_test_analysis_with_claude

# Modules classiques (statiques)
from scripts.nightly_review.modules.frontend_validator import run_frontend_validation
from scripts.nightly_review.modules.db_safety import create_db_snapshots, verify_db_integrity
from scripts.nightly_review.modules.report_generator import ReportGenerator


class NightlyReview:
    """Orchestrateur de la revue nocturne."""

    def __init__(self, project_root: Path, options: dict):
        """
        Initialise la revue nocturne.

        Args:
            project_root: Racine du projet
            options: Options d'exécution
        """
        self.project_root = project_root
        self.options = options
        self.report_dir = project_root / "reports" / "nightly"
        self.start_time = datetime.now()

        # Résultats
        self.results = {
            "code_review": {},
            "architecture_analysis": {},
            "test_analysis": {},
            "frontend_validation": {},
            "db_safety": {}
        }

    def run(self):
        """Exécute la revue complète."""
        print("=" * 80)
        print("🌙 REVUE NOCTURNE - DÉMARRAGE")
        print("=" * 80)
        print(f"Projet: {self.project_root.name}")
        print(f"Démarré: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print()

        try:
            # Étape 1: Sécurité des données
            if not self.options.get("skip_db_safety"):
                self._step_db_safety()

            # Étape 2: Code Review
            self._step_code_review()

            # Étape 3: Architecture Analysis
            self._step_architecture_analysis()

            # Étape 4: Test Analysis
            if not self.options.get("skip_tests"):
                self._step_test_analysis()

            # Étape 5: Frontend Validation
            if not self.options.get("skip_frontend"):
                self._step_frontend_validation()

            # Étape 6: Vérification intégrité
            if not self.options.get("skip_db_safety"):
                self._step_verify_integrity()

            # Étape 7: Génération rapport
            self._step_generate_report()

            # Résumé final
            self._print_summary()

        except KeyboardInterrupt:
            print("\n\n⚠️ Revue interrompue par l'utilisateur")
            sys.exit(1)
        except Exception as e:
            print(f"\n\n❌ Erreur durant la revue: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def _step_db_safety(self):
        """Étape 1: Snapshots des bases de données."""
        print("\n" + "=" * 80)
        print("ÉTAPE 1/6: SÉCURITÉ DES DONNÉES")
        print("=" * 80 + "\n")

        self.results["db_safety"] = create_db_snapshots(self.project_root)

        print(f"\n✅ Étape 1 terminée - {self.results['db_safety'].get('total_snapshots', 0)} snapshots créés\n")

    def _step_code_review(self):
        """Étape 2: Revue de code avec Claude."""
        print("\n" + "=" * 80)
        print("ÉTAPE 2/7: REVUE DE CODE (Statique + Claude)")
        print("=" * 80 + "\n")

        self.results["code_review"] = run_code_review_with_claude(self.project_root)

        issues = self.results["code_review"].get("total_issues", 0)
        print(f"\n✅ Étape 2 terminée - {issues} problèmes détectés\n")

    def _step_architecture_analysis(self):
        """Étape 3: Analyse d'architecture avec Claude Architecte."""
        print("\n" + "=" * 80)
        print("ÉTAPE 3/7: ANALYSE D'ARCHITECTURE (Claude Architecte)")
        print("=" * 80 + "\n")

        self.results["architecture_analysis"] = run_architecture_analysis_with_claude(self.project_root)

        total_issues = self.results["architecture_analysis"].get("total_issues", 0)
        recommendations = len(self.results["architecture_analysis"].get("details", {}).get("recommendations", []))
        print(f"\n✅ Étape 3 terminée - {total_issues} problèmes architecturaux, {recommendations} recommandations\n")

    def _step_test_analysis(self):
        """Étape 4: Analyse des tests avec Claude QA."""
        print("\n" + "=" * 80)
        print("ÉTAPE 4/7: ANALYSE DES TESTS (Exécution + Claude QA)")
        print("=" * 80 + "\n")

        self.results["test_analysis"] = run_test_analysis_with_claude(self.project_root)

        coverage = self.results["test_analysis"].get("coverage_percent", 0)
        print(f"\n✅ Étape 4 terminée - Couverture: {coverage:.1f}%\n")

    def _step_frontend_validation(self):
        """Étape 5: Validation frontend."""
        print("\n" + "=" * 80)
        print("ÉTAPE 5/7: VALIDATION FRONTEND & API")
        print("=" * 80 + "\n")

        self.results["frontend_validation"] = run_frontend_validation(self.project_root)

        total = self.results["frontend_validation"].get("total_endpoints", 0)
        working = self.results["frontend_validation"].get("working_endpoints", 0)
        print(f"\n✅ Étape 5 terminée - {working}/{total} endpoints fonctionnels\n")

    def _step_verify_integrity(self):
        """Étape 6: Vérification intégrité."""
        print("\n" + "=" * 80)
        print("ÉTAPE 6/7: VÉRIFICATION INTÉGRITÉ")
        print("=" * 80 + "\n")

        integrity_results = verify_db_integrity(self.project_root)

        # Ajouter aux résultats DB safety
        self.results["db_safety"]["integrity"] = integrity_results

        issues = integrity_results.get("issues_found", 0)
        print(f"\n✅ Étape 6 terminée - {issues} problèmes d'intégrité détectés\n")

    def _step_generate_report(self):
        """Étape 7: Génération du rapport."""
        print("\n" + "=" * 80)
        print("ÉTAPE 7/7: GÉNÉRATION DU RAPPORT")
        print("=" * 80 + "\n")

        generator = ReportGenerator(self.project_root, self.report_dir)

        # Rapport HTML
        html_file = generator.generate_html_report(
            self.results["code_review"],
            self.results["architecture_analysis"],
            self.results["test_analysis"],
            self.results["frontend_validation"],
            self.results["db_safety"]
        )
        print(f"📄 Rapport HTML généré: {html_file}")

        # Rapport JSON
        json_file = generator.generate_json_export(
            self.results["code_review"],
            self.results["architecture_analysis"],
            self.results["test_analysis"],
            self.results["frontend_validation"],
            self.results["db_safety"]
        )
        print(f"📋 Export JSON généré: {json_file}")

        # Ouvrir le rapport dans le navigateur
        if self.options.get("open_browser", True):
            print(f"\n🌐 Ouverture du rapport dans le navigateur...")
            webbrowser.open(f"file:///{html_file}")

        print(f"\n✅ Étape 7 terminée - Rapports générés\n")

    def _print_summary(self):
        """Affiche le résumé final."""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        print("\n" + "=" * 80)
        print("📊 RÉSUMÉ DE LA REVUE NOCTURNE")
        print("=" * 80)

        # Code Review
        code_issues = self.results["code_review"].get("total_issues", 0)
        print(f"\n📋 Code Review:")
        print(f"   • {code_issues} problèmes de qualité détectés")
        print(f"   • {len(self.results['code_review'].get('details', {}).get('dead_code', []))} éléments de code mort")
        print(f"   • {len(self.results['code_review'].get('details', {}).get('complexity', []))} fonctions complexes")

        # Tests
        if self.results.get("test_analysis"):
            total_tests = self.results["test_analysis"].get("total_tests", 0)
            passed = self.results["test_analysis"].get("passed", 0)
            coverage = self.results["test_analysis"].get("coverage_percent", 0)
            print(f"\n🧪 Tests:")
            print(f"   • {total_tests} tests exécutés ({passed} réussis)")
            print(f"   • {coverage:.1f}% de couverture")
            print(f"   • {len(self.results['test_analysis'].get('details', {}).get('missing_tests', []))} fonctions sans tests")

        # Frontend
        if self.results.get("frontend_validation"):
            total_endpoints = self.results["frontend_validation"].get("total_endpoints", 0)
            working = self.results["frontend_validation"].get("working_endpoints", 0)
            print(f"\n🌐 Frontend & API:")
            print(f"   • {working}/{total_endpoints} endpoints fonctionnels")
            health_rate = self.results["frontend_validation"].get("details", {}).get("summary", {}).get("api_health_rate", 0)
            print(f"   • {health_rate:.1f}% de santé API")

        # DB Safety
        if self.results.get("db_safety"):
            snapshots = self.results["db_safety"].get("total_snapshots", 0)
            print(f"\n💾 Sécurité Données:")
            print(f"   • {snapshots} snapshots créés")
            print(f"   • Sauvegarde dans: {self.results['db_safety'].get('backup_dir', 'N/A')}")

        # Durée
        print(f"\n⏱️ Durée totale: {duration:.1f} secondes ({duration/60:.1f} minutes)")

        print("\n" + "=" * 80)
        print("✅ REVUE NOCTURNE TERMINÉE AVEC SUCCÈS")
        print("=" * 80)
        print()


def main():
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(
        description="Système de revue nocturne automatique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python scripts/nightly_review.py                    # Revue complète
  python scripts/nightly_review.py --skip-tests       # Sans tests
  python scripts/nightly_review.py --skip-frontend    # Sans validation frontend
  python scripts/nightly_review.py --no-browser       # Sans ouverture navigateur
"""
    )

    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip l'exécution des tests (plus rapide)"
    )

    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Skip la validation frontend/API"
    )

    parser.add_argument(
        "--skip-db-safety",
        action="store_true",
        help="Skip les snapshots de bases de données"
    )

    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Ne pas ouvrir le rapport dans le navigateur"
    )

    args = parser.parse_args()

    # Options
    options = {
        "skip_tests": args.skip_tests,
        "skip_frontend": args.skip_frontend,
        "skip_db_safety": args.skip_db_safety,
        "open_browser": not args.no_browser
    }

    # Lancer la revue
    review = NightlyReview(project_root, options)
    review.run()


if __name__ == "__main__":
    main()
